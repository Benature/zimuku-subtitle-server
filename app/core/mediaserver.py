import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .config import ConfigManager, SettingKey

logger = logging.getLogger(__name__)

_UNWATCHED_PAGE_SIZE = 1000
_YEAR_SUFFIX_PATTERN = re.compile(r"\s*\(\d{4}\)\s*$")

MEDIA_SERVER_TYPES = ("jellyfin", "emby", "plex")

# 旧版 jellyfin_* 设置键（仅用于兼容回退，不再出现在设置定义中）
_LEGACY_JELLYFIN_KEYS = {
    "enabled": "jellyfin_enabled",
    "base_url": "jellyfin_base_url",
    "api_key": "jellyfin_api_key",
    "user_id": "jellyfin_user_id",
}


def normalize_media_server_title(title: str) -> str:
    """与媒体库作品分组标题保持一致的规范化：去掉尾部年份标记并 casefold。"""
    return _YEAR_SUFFIX_PATTERN.sub("", title or "").strip().casefold()


@dataclass
class UnwatchedIndex:
    """媒体服务器未观看内容索引（作品标题均已规范化）。"""

    titles: set[str] = field(default_factory=set)
    item_count: int = 0

    def matches(self, work_title: str) -> bool:
        return normalize_media_server_title(work_title) in self.titles

    def collect(self, name: Optional[str]) -> None:
        normalized = normalize_media_server_title(str(name or ""))
        if normalized:
            self.titles.add(normalized)
            self.item_count += 1


class BaseMediaServerClient:
    """媒体服务器客户端基类：读取用户未观看状态。

    任何请求失败都只记录日志并返回 None/失败信息，不影响主流程。
    """

    server_type = ""
    server_name = "Media Server"

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        user_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        timeout: float = 15.0,
    ):
        self._enabled = (
            enabled if enabled is not None else ConfigManager.get_bool(SettingKey.MEDIA_SERVER_ENABLED, False)
        )
        base_url_value = base_url if base_url is not None else ConfigManager.get(SettingKey.MEDIA_SERVER_BASE_URL)
        self._base_url = (base_url_value or "").rstrip("/")
        self._api_key = api_key if api_key is not None else ConfigManager.get(SettingKey.MEDIA_SERVER_API_KEY)
        self._user_id = user_id if user_id is not None else ConfigManager.get(SettingKey.MEDIA_SERVER_USER_ID)
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    def _auth_headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._auth_headers(),
            timeout=self._timeout,
        )

    async def fetch_unwatched(self) -> Optional[UnwatchedIndex]:
        """拉取当前用户未观看的剧集/电影索引；未启用或失败时返回 None（调用方回退原排序）。"""
        if not self._enabled or not self.configured:
            return None
        try:
            async with self._build_client() as client:
                return await self._fetch_unwatched(client)
        except Exception as exc:
            logger.warning("拉取 %s 未观看列表失败，按原优先级补全: %s", self.server_name, exc)
            return None

    async def _fetch_unwatched(self, client: httpx.AsyncClient) -> Optional[UnwatchedIndex]:
        raise NotImplementedError

    async def test_connection(self) -> tuple[bool, str]:
        """测试服务器连接与凭据有效性，返回 (是否成功, 描述信息)。"""
        if not self.configured:
            return False, f"{self.server_name} 地址或 API Key 未配置"
        try:
            async with self._build_client() as client:
                return await self._test_connection(client)
        except Exception as exc:
            return False, f"连接失败: {exc}"

    async def _test_connection(self, client: httpx.AsyncClient) -> tuple[bool, str]:
        raise NotImplementedError


class EmbyLikeClient(BaseMediaServerClient):
    """Jellyfin / Emby 共用的 API 家族（Emby 分叉自 Jellyfin 同源代码，接口一致）。

    认证统一通过请求头传递（不使用 ``?api_key=`` 查询参数，避免密钥进入访问日志）。
    """

    async def _resolve_user_id(self, client: httpx.AsyncClient) -> Optional[str]:
        """返回配置的用户 ID；未配置时回退到服务器首个用户。"""
        if self._user_id:
            return self._user_id
        response = await client.get("/Users")
        response.raise_for_status()
        users = response.json()
        if not users:
            return None
        logger.info("%s 用户ID未配置，回退到首个用户: %s", self.server_name, users[0].get("Name"))
        return users[0].get("Id")

    async def _fetch_unwatched(self, client: httpx.AsyncClient) -> Optional[UnwatchedIndex]:
        user_id = await self._resolve_user_id(client)
        if not user_id:
            logger.warning("%s 未找到可用用户，跳过未观看优先级", self.server_name)
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
                if isinstance(item, dict):
                    name = item.get("SeriesName") if item.get("Type") == "Episode" else item.get("Name")
                    index.collect(name)
            if len(items) < _UNWATCHED_PAGE_SIZE:
                break
            start_index += len(items)

        logger.info("%s 未观看索引：%s 个条目，覆盖 %s 部作品", self.server_name, index.item_count, len(index.titles))
        return index

    async def _test_connection(self, client: httpx.AsyncClient) -> tuple[bool, str]:
        response = await client.get("/System/Info")
        response.raise_for_status()
        info = response.json()
        server = info.get("ServerName") or self.server_name
        version = info.get("Version") or "unknown"
        if not await self._resolve_user_id(client):
            return False, f"已连接 {server} ({version})，但未找到可用用户"
        return True, f"连接成功：{server} ({version})"


class JellyfinClient(EmbyLikeClient):
    """Jellyfin 客户端，认证走 ``Authorization: MediaBrowser Token="..."``（兼容 Jellyfin 12+）。"""

    server_type = "jellyfin"
    server_name = "Jellyfin"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f'MediaBrowser Token="{self._api_key}"'}


class EmbyClient(EmbyLikeClient):
    """Emby 客户端，认证走 ``X-Emby-Token`` 请求头。"""

    server_type = "emby"
    server_name = "Emby"

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Emby-Token": self._api_key}


class PlexClient(BaseMediaServerClient):
    """Plex 客户端，认证走 ``X-Plex-Token`` 请求头。

    Plex 的观看状态按 token 所属账号统计，无需用户 ID；
    按媒体库（剧集→单集 type=4、电影→type=1）过滤 ``unwatched=1`` 拉取未观看条目。
    """

    server_type = "plex"
    server_name = "Plex"

    def _auth_headers(self) -> dict[str, str]:
        return {"X-Plex-Token": self._api_key, "Accept": "application/json"}

    @staticmethod
    def _container(payload: dict) -> dict:
        return payload.get("MediaContainer", {}) if isinstance(payload, dict) else {}

    async def _fetch_unwatched(self, client: httpx.AsyncClient) -> Optional[UnwatchedIndex]:
        response = await client.get("/library/sections")
        response.raise_for_status()
        directories = self._container(response.json()).get("Directory") or []

        index = UnwatchedIndex()
        for section in directories:
            if not isinstance(section, dict):
                continue
            section_key = section.get("key")
            section_type = section.get("type")
            if not section_key or section_type not in ("show", "movie"):
                continue
            params = {"type": 4 if section_type == "show" else 1, "unwatched": 1}
            section_response = await client.get(f"/library/sections/{section_key}/all", params=params)
            section_response.raise_for_status()
            metadata = self._container(section_response.json()).get("Metadata") or []
            for item in metadata:
                if not isinstance(item, dict):
                    continue
                name = item.get("grandparentTitle") if section_type == "show" else item.get("title")
                index.collect(name)

        logger.info("Plex 未观看索引：%s 个条目，覆盖 %s 部作品", index.item_count, len(index.titles))
        return index

    async def _test_connection(self, client: httpx.AsyncClient) -> tuple[bool, str]:
        response = await client.get("/identity")
        response.raise_for_status()
        info = self._container(response.json())
        version = info.get("version") or "unknown"
        return True, f"连接成功：Plex ({version})"


_CLIENT_CLASSES = {
    JellyfinClient.server_type: JellyfinClient,
    EmbyClient.server_type: EmbyClient,
    PlexClient.server_type: PlexClient,
}


def build_media_server_client(
    server_type: Optional[str] = None,
    **kwargs,
) -> Optional[BaseMediaServerClient]:
    """按设置构建媒体服务器客户端；类型非法时返回 None。

    未显式传参时从系统设置读取；新设置未配置但存在旧版 ``jellyfin_*`` 设置时
    自动按 Jellyfin 兼容回退。
    """
    if server_type is None:
        resolved = _resolve_settings()
        if resolved is None:
            return None
        server_type, kwargs = resolved

    client_class = _CLIENT_CLASSES.get((server_type or "").strip().lower())
    if client_class is None:
        logger.warning("未知的媒体服务器类型: %s", server_type)
        return None
    return client_class(**kwargs)


def _resolve_settings() -> Optional[tuple[str, dict]]:
    server_type = ConfigManager.get(SettingKey.MEDIA_SERVER_TYPE) or "jellyfin"
    kwargs = {
        "base_url": ConfigManager.get(SettingKey.MEDIA_SERVER_BASE_URL),
        "api_key": ConfigManager.get(SettingKey.MEDIA_SERVER_API_KEY),
        "user_id": ConfigManager.get(SettingKey.MEDIA_SERVER_USER_ID),
        "enabled": ConfigManager.get_bool(SettingKey.MEDIA_SERVER_ENABLED, False),
    }

    if not kwargs["base_url"]:
        legacy_url = ConfigManager.get(_LEGACY_JELLYFIN_KEYS["base_url"])
        if legacy_url:
            logger.info("检测到旧版 jellyfin_* 设置，按 Jellyfin 兼容回退")
            server_type = "jellyfin"
            kwargs = {
                "base_url": legacy_url,
                "api_key": ConfigManager.get(_LEGACY_JELLYFIN_KEYS["api_key"]),
                "user_id": ConfigManager.get(_LEGACY_JELLYFIN_KEYS["user_id"]),
                "enabled": ConfigManager.get_bool(_LEGACY_JELLYFIN_KEYS["enabled"], False),
            }

    return server_type, kwargs


async def fetch_unwatched_index() -> Optional[UnwatchedIndex]:
    """按当前系统设置拉取媒体服务器未观看索引（未启用/失败时返回 None）。"""
    client = build_media_server_client()
    if client is None:
        return None
    return await client.fetch_unwatched()
