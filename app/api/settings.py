from fastapi import APIRouter

from ..core.config import SettingKey
from ..core.jellyfin import JellyfinClient
from ..db.models import Setting
from ..services.scheduler_service import scheduler_service
from ..services.settings_service import SettingsService
from .errors import raise_for_service_error
from .schemas import JellyfinTestResponse, SettingUpdateRequest

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


@router.post("/jellyfin/test", response_model=JellyfinTestResponse)
async def test_jellyfin_connection() -> JellyfinTestResponse:
    """测试 Jellyfin 服务器连接与用户解析"""
    connected, message = await JellyfinClient().test_connection()
    return JellyfinTestResponse(message=message, connected=connected)
