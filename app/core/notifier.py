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
    """飞书自定义机器人通知器，发送失败仅记录日志，不影响主流程。"""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: float = 10.0,
    ):
        self._webhook_url = webhook_url if webhook_url is not None else ConfigManager.get(SettingKey.FEISHU_WEBHOOK_URL)
        self._secret = secret if secret is not None else ConfigManager.get(SettingKey.FEISHU_WEBHOOK_SECRET)
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._webhook_url)

    async def send_text(self, content: str) -> bool:
        if not self._webhook_url:
            logger.debug("飞书 webhook 未配置，跳过通知")
            return False

        payload: dict = {"msg_type": "text", "content": {"text": content}}
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

    async def send_scheduled_report(self, stats: ScheduledJobStats) -> bool:
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
        return await self.send_text("\n".join(lines))

    async def send_test(self) -> bool:
        return await self.send_text("【Zimuku Subtitle Server】飞书通知测试消息")
