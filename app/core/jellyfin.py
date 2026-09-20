import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .config import ConfigManager, SettingKey

logger = logging.getLogger(__name__)

_UNWATCHED_PAGE_SIZE = 1000
_YEAR_SUFFIX_PATTERN = re.compile(r"\s*\(\d{4}\)\s*$")


def normalize_jellyfin_title(title: str) -> str:
    """与媒体库作品分组标题保持一致的规范化：去掉尾部年份标记并 casefold。"""
    return _YEAR_SUFFIX_PATTERN.sub("", title or "").strip().casefold()


@dataclass
class UnwatchedIndex:
    """Jellyfin 未观看内容索引（作品标题均已规范化）。"""

    titles: set[str] = field(default_factory=set)
    item_count: int = 0

    def matches(self, work_title: str) -> bool:
        return normalize_jellyfin_title(work_title) in self.titles


class JellyfinClient:
    """Jellyfin API 客户端，用于读取用户未观看状态。

    认证统一使用 ``Authorization: MediaBrowser Token="..."`` 请求头（兼容 Jellyfin 12+），
    不使用 ``?api_key=`` 查询参数，避免密钥进入反向代理/访问日志。
    任何请求失败都只记录日志并返回 None/失败信息，不影响主流程。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        timeout: float = 15.0,
    ):
        self._enabled = enabled if enabled is not None else ConfigManager.get_bool(SettingKey.JELLYFIN_ENABLED, False)
        base_url_value = base_url if base_url is not None else ConfigManager.get(SettingKey.JELLYFIN_BASE_URL)
        self._base_url = (base_url_value or "").rstrip("/")
        self._api_key = api_key if api_key is not None else ConfigManager.get(SettingKey.JELLYFIN_API_KEY)
        self._user_id = user_id if user_id is not None else ConfigManager.get(SettingKey.JELLYFIN_USER_ID)
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f'MediaBrowser Token="{self._api_key}"'},
            timeout=self._timeout,
        )

    async def _resolve_user_id(self, client: httpx.AsyncClient) -> Optional[str]:
        """返回配置的用户 ID；未配置时回退到 Jellyfin 首个用户。"""
        if self._user_id:
            return self._user_id
        response = await client.get("/Users")
        response.raise_for_status()
        users = response.json()
        if not users:
            return None
        logger.info("Jellyfin 用户ID未配置，回退到首个用户: %s", users[0].get("Name"))
        return users[0].get("Id")

    async def fetch_unwatched(self) -> Optional[UnwatchedIndex]:
        """拉取当前用户未观看的剧集/电影索引；未启用或失败时返回 None（调用方回退原排序）。"""
        if not self._enabled or not self.configured:
            return None
        try:
            async with self._build_client() as client:
                user_id = await self._resolve_user_id(client)
                if not user_id:
                    logger.warning("Jellyfin 未找到可用用户，跳过未观看优先级")
                    return None

                index = UnwatchedIndex()
                start_index = 0
                while True:
                    response = await client.get(
                        f"/Users/{user_id}/Items",
                        params={
                            "Recursive": "true",
                            "IncludeItemTypes": "Episode,Movie",
                            "Filters": "IsUnplayed",
                            "StartIndex": start_index,
                            "Limit": _UNWATCHED_PAGE_SIZE,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    items = payload.get("Items", []) if isinstance(payload, dict) else payload
                    for item in items:
                        self._collect_title(index, item)
                    if len(items) < _UNWATCHED_PAGE_SIZE:
                        break
                    start_index += len(items)

                logger.info(
                    "Jellyfin 未观看索引：%s 个条目，覆盖 %s 部作品",
                    index.item_count,
                    len(index.titles),
                )
                return index
        except Exception as exc:
            logger.warning("拉取 Jellyfin 未观看列表失败，按原优先级补全: %s", exc)
            return None

    @staticmethod
    def _collect_title(index: UnwatchedIndex, item) -> None:
        if not isinstance(item, dict):
            return
        name = item.get("SeriesName") if item.get("Type") == "Episode" else item.get("Name")
        normalized = normalize_jellyfin_title(str(name or ""))
        if normalized:
            index.titles.add(normalized)
            index.item_count += 1

    async def test_connection(self) -> tuple[bool, str]:
        """测试 Jellyfin 连接与用户解析，返回 (是否成功, 描述信息)。"""
        if not self.configured:
            return False, "Jellyfin 地址或 API Key 未配置"
        try:
            async with self._build_client() as client:
                response = await client.get("/System/Info")
                response.raise_for_status()
                info = response.json()
                server = info.get("ServerName") or "Jellyfin"
                version = info.get("Version") or "unknown"
                if not await self._resolve_user_id(client):
                    return False, f"已连接 {server} ({version})，但未找到可用用户"
                return True, f"连接成功：{server} ({version})"
        except Exception as exc:
            return False, f"连接失败: {exc}"
