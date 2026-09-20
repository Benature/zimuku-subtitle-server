import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from .config import ConfigManager, SettingKey

logger = logging.getLogger(__name__)

MAX_FAILURE_ITEMS = 10
FEISHU_OPEN_API_BASE = "https://open.feishu.cn/open-apis"


@dataclass
class ScheduledJobStats:
    """定时扫描补字幕任务的运行结果摘要"""

    scanned_files: int = 0
    missing_subtitle: int = 0
    matched: int = 0
    failed: int = 0
    failed_files: List[str] = field(default_factory=list)
    titles: List[str] = field(default_factory=list)
    remaining_works: int = 0


def generate_feishu_sign(secret: str, timestamp: Optional[int] = None) -> tuple[str, str]:
    """按飞书加签算法生成 (timestamp, sign)。"""
    ts = str(timestamp or int(time.time()))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return ts, base64.b64encode(digest).decode("utf-8")


class FeishuNotifier:
    """飞书自定义机器人通知器，发送失败仅记录日志，不影响主流程。

    自定义机器人 webhook 无法直接内嵌外部图片；配置自建应用凭据（app_id/app_secret）后，
    可先将封面图上传到飞书获得 image_key，再以卡片消息内嵌显示。
    """

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self._webhook_url = webhook_url if webhook_url is not None else ConfigManager.get(SettingKey.FEISHU_WEBHOOK_URL)
        self._secret = secret if secret is not None else ConfigManager.get(SettingKey.FEISHU_WEBHOOK_SECRET)
        self._app_id = app_id if app_id is not None else ConfigManager.get(SettingKey.FEISHU_APP_ID)
        self._app_secret = app_secret if app_secret is not None else ConfigManager.get(SettingKey.FEISHU_APP_SECRET)
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._webhook_url)

    @property
    def image_upload_configured(self) -> bool:
        return bool(self._app_id and self._app_secret)

    async def _post_webhook(self, payload: dict) -> bool:
        """向自定义机器人 webhook 投递消息，返回是否成功。"""
        if not self._webhook_url:
            logger.debug("飞书 webhook 未配置，跳过通知")
            return False

        if self._secret:
            timestamp, sign = generate_feishu_sign(self._secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._webhook_url, json=payload)
                response.raise_for_status()
                result = response.json()
        except Exception as exc:
            logger.error("飞书通知发送失败: %s", exc)
            return False

        if result.get("code") != 0:
            logger.error("飞书通知返回错误: %s", result)
            return False

        logger.info("飞书通知发送成功")
        return True

    async def send_text(self, content: str) -> bool:
        return await self._post_webhook({"msg_type": "text", "content": {"text": content}})

    async def _get_tenant_access_token(self, client: httpx.AsyncClient) -> str:
        """用自建应用凭据换取 tenant_access_token，失败时抛异常。"""
        response = await client.post(
            f"{FEISHU_OPEN_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {result.get('msg', result)}")
        return result["tenant_access_token"]

    async def _upload_image(self, client: httpx.AsyncClient, token: str, image_bytes: bytes) -> str:
        """上传图片到飞书并返回 image_key，失败时抛异常。"""
        response = await client.post(
            f"{FEISHU_OPEN_API_BASE}/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("backdrop.jpg", image_bytes, "image/jpeg")},
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") != 0:
            raise RuntimeError(f"上传封面图失败: {result.get('msg', result)}")
        return result["data"]["image_key"]

    @staticmethod
    def _build_report_lines(stats: ScheduledJobStats) -> list[str]:
        lines = [
            "【字幕定时补全完成】",
            f"扫描文件数：{stats.scanned_files}",
        ]
        if stats.titles:
            lines.append(f"本次补全作品：{'、'.join(f'《{title}》' for title in stats.titles)}")
        lines.extend(
            [
                f"缺失字幕：{stats.missing_subtitle}",
                f"补全成功：{stats.matched}",
                f"补全失败：{stats.failed}",
            ]
        )
        if stats.remaining_works > 0:
            lines.append(f"剩余待补作品：{stats.remaining_works} 部（下次运行继续）")
        if stats.failed_files:
            lines.append("失败列表：")
            lines.extend(f"- {name}" for name in stats.failed_files[:MAX_FAILURE_ITEMS])
            remaining = len(stats.failed_files) - MAX_FAILURE_ITEMS
            if remaining > 0:
                lines.append(f"... 其余 {remaining} 个略")
        return lines

    async def send_scheduled_report(self, stats: ScheduledJobStats, images: Optional[dict[str, bytes]] = None) -> bool:
        """发送定时任务汇总；有封面图且配置了自建应用凭据时以卡片消息内嵌封面，否则纯文本。"""
        lines = self._build_report_lines(stats)
        if images and self.image_upload_configured:
            try:
                if await self._send_card_report(stats, lines, images):
                    return True
                logger.warning("封面图全部上传失败，回退纯文本通知")
            except Exception as exc:
                logger.error("飞书卡片通知发送失败，回退纯文本: %s", exc)
        return await self.send_text("\n".join(lines))

    async def _send_card_report(self, stats: ScheduledJobStats, lines: list[str], images: dict[str, bytes]) -> bool:
        """上传封面图并以交互式卡片消息发送（摘要 + 每部作品一张横屏封面），全部上传失败时返回 False。"""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            token = await self._get_tenant_access_token(client)
            image_keys: dict[str, str] = {}
            for title, image_bytes in images.items():
                try:
                    image_keys[title] = await self._upload_image(client, token, image_bytes)
                except Exception as exc:
                    logger.warning("《%s》封面上传失败，跳过该图: %s", title, exc)
        if not image_keys:
            return False

        elements: list[dict] = [{"tag": "markdown", "content": "\n".join(lines[1:])}]
        for title in stats.titles:
            image_key = image_keys.get(title)
            if not image_key:
                continue
            elements.extend(
                [
                    {"tag": "hr"},
                    {"tag": "markdown", "content": f"**《{title}》**"},
                    {"tag": "img", "img_key": image_key, "alt": {"tag": "plain_text", "content": title}},
                ]
            )

        card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": lines[0]}},
            "elements": elements,
        }
        return await self._post_webhook({"msg_type": "interactive", "card": card})

    async def send_test(self) -> bool:
        return await self.send_text("【Zimuku Subtitle Server】飞书通知测试消息")
