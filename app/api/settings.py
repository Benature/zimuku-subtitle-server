from fastapi import APIRouter

from ..core.config import SettingKey
from ..core.mediaserver import build_media_server_client
from ..db.models import Setting
from ..services.scheduler_service import scheduler_service
from ..services.settings_service import SettingsService
from .errors import raise_for_service_error
from .schemas import MediaServerTestResponse, SettingUpdateRequest

router = APIRouter(prefix="/settings", tags=["Settings"])

SCHEDULE_SETTING_KEYS = {SettingKey.SCHEDULE_ENABLED, SettingKey.SCHEDULE_CRON}


@router.get("/", response_model=list[Setting])
async def list_settings():
    """获取所有配置"""
    return SettingsService.get_all_settings()


@router.post("/", response_model=Setting)
async def update_setting(update: SettingUpdateRequest):
    """更新或创建配置"""
    try:
        setting = SettingsService.set_setting(update.key, update.value, update.description)
    except Exception as exc:
        raise_for_service_error(exc)

    if update.key in SCHEDULE_SETTING_KEYS:
        scheduler_service.reload()

    return setting


@router.post("/media-server/test", response_model=MediaServerTestResponse)
async def test_media_server_connection() -> MediaServerTestResponse:
    """测试媒体服务器（Jellyfin/Emby/Plex）连接与凭据有效性"""
    client = build_media_server_client()
    if client is None:
        return MediaServerTestResponse(message="媒体服务器类型配置非法", connected=False)
    connected, message = await client.test_connection()
    return MediaServerTestResponse(message=message, connected=connected)
