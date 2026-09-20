import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from ..db.models import Setting

logger = logging.getLogger(__name__)


class SettingKey:
    BASE_URL = "base_url"
    PROXY = "proxy"
    CACHE_EXPIRY_HOURS = "cache_expiry_hours"
    TRASH_RETENTION_DAYS = "trash_retention_days"
    AUTO_ALIGN_AFTER_DOWNLOAD = "auto_align_after_download"
    SCHEDULE_ENABLED = "schedule_enabled"
    SCHEDULE_CRON = "schedule_cron"
    SCHEDULE_MAX_WORKS_PER_RUN = "schedule_max_works_per_run"
    FEISHU_NOTIFY_ENABLED = "feishu_notify_enabled"
    FEISHU_WEBHOOK_URL = "feishu_webhook_url"
    FEISHU_WEBHOOK_SECRET = "feishu_webhook_secret"
    JELLYFIN_ENABLED = "jellyfin_enabled"
    JELLYFIN_BASE_URL = "jellyfin_base_url"
    JELLYFIN_API_KEY = "jellyfin_api_key"
    JELLYFIN_USER_ID = "jellyfin_user_id"
    DOWNLOAD_PATH = "download_path"
    TEMP_PATH = "temp_path"
    EXTRACTED_PATH = "extracted_path"
    TRASH_PATH = "trash_path"


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    default: str
    description: str
    kind: str = "string"


@dataclass(frozen=True)
class StoragePaths:
    root: str
    downloads: str
    temp: str
    extracted: str
    database: str
    trash: str


SETTINGS_DEFINITIONS = {
    SettingKey.BASE_URL: SettingDefinition(
        key=SettingKey.BASE_URL,
        default="https://zimuku.org",
        description="字幕网站地址",
    ),
    SettingKey.PROXY: SettingDefinition(
        key=SettingKey.PROXY,
        default="",
        description="HTTP 代理地址（如需代理访问字幕网站）",
    ),
    SettingKey.CACHE_EXPIRY_HOURS: SettingDefinition(
        key=SettingKey.CACHE_EXPIRY_HOURS,
        default="24",
        description="搜索缓存有效期（小时）",
        kind="int",
    ),
    SettingKey.TRASH_RETENTION_DAYS: SettingDefinition(
        key=SettingKey.TRASH_RETENTION_DAYS,
        default="365",
        description="字幕回收站保留时长（天），过期后将彻底删除；0 表示永久保留",
        kind="int",
    ),
    SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD: SettingDefinition(
        key=SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD,
        default="true",
        description="字幕下载完成后自动执行音轨对齐（对齐前自动备份原字幕，可随时还原）",
        kind="bool",
    ),
    SettingKey.SCHEDULE_ENABLED: SettingDefinition(
        key=SettingKey.SCHEDULE_ENABLED,
        default="false",
        description="启用定时扫描媒体库并自动补全缺失字幕（cron 触发）",
        kind="bool",
    ),
    SettingKey.SCHEDULE_CRON: SettingDefinition(
        key=SettingKey.SCHEDULE_CRON,
        default="0 3 * * *",
        description="定时扫描补字幕的 cron 表达式（5 段式：分 时 日 月 周）",
    ),
    SettingKey.SCHEDULE_MAX_WORKS_PER_RUN: SettingDefinition(
        key=SettingKey.SCHEDULE_MAX_WORKS_PER_RUN,
        default="1",
        description="每次定时运行最多补全的作品（剧集/电影）数量，缺字幕最多者优先；0 表示不限",
        kind="int",
    ),
    SettingKey.FEISHU_NOTIFY_ENABLED: SettingDefinition(
        key=SettingKey.FEISHU_NOTIFY_ENABLED,
        default="false",
        description="定时任务完成后发送飞书机器人通知",
        kind="bool",
    ),
    SettingKey.FEISHU_WEBHOOK_URL: SettingDefinition(
        key=SettingKey.FEISHU_WEBHOOK_URL,
        default="",
        description="飞书自定义机器人 Webhook 地址",
    ),
    SettingKey.FEISHU_WEBHOOK_SECRET: SettingDefinition(
        key=SettingKey.FEISHU_WEBHOOK_SECRET,
        default="",
        description="飞书机器人加签密钥（机器人未开启加签则留空）",
    ),
    SettingKey.JELLYFIN_ENABLED: SettingDefinition(
        key=SettingKey.JELLYFIN_ENABLED,
        default="false",
        description="启用 Jellyfin 联动：批量补字幕时优先处理尚未观看的作品",
        kind="bool",
    ),
    SettingKey.JELLYFIN_BASE_URL: SettingDefinition(
        key=SettingKey.JELLYFIN_BASE_URL,
        default="",
        description="Jellyfin 服务器地址（如 http://192.168.1.10:8096）",
    ),
    SettingKey.JELLYFIN_API_KEY: SettingDefinition(
        key=SettingKey.JELLYFIN_API_KEY,
        default="",
        description="Jellyfin API Key（仅通过 Authorization 请求头传递）",
    ),
    SettingKey.JELLYFIN_USER_ID: SettingDefinition(
        key=SettingKey.JELLYFIN_USER_ID,
        default="",
        description="Jellyfin 用户 ID（32 位 GUID，留空则自动使用首个用户）",
    ),
}

PATH_ENV_MAP = {
    SettingKey.DOWNLOAD_PATH: "ZIMUKU_DOWNLOAD_PATH",
    SettingKey.TEMP_PATH: "ZIMUKU_TEMP_PATH",
    SettingKey.EXTRACTED_PATH: "ZIMUKU_EXTRACTED_PATH",
    SettingKey.TRASH_PATH: "ZIMUKU_TRASH_PATH",
}

BOOL_SETTING_KEYS = {
    SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD,
    SettingKey.SCHEDULE_ENABLED,
    SettingKey.FEISHU_NOTIFY_ENABLED,
    SettingKey.JELLYFIN_ENABLED,
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_path(value: str) -> str:
    expanded = os.path.expanduser(value.strip())
    return os.path.abspath(expanded)


def _ensure_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _get_optional_env_path(env_name: Optional[str], default_path: str) -> str:
    if not env_name:
        return default_path
    env_value = os.getenv(env_name)
    if not env_value:
        return default_path
    return _normalize_path(env_value)


def get_storage_paths() -> StoragePaths:
    root_value = os.getenv("ZIMUKU_STORAGE_PATH")
    storage_root = _normalize_path(root_value) if root_value else str(_project_root() / "storage")

    downloads = _get_optional_env_path(
        PATH_ENV_MAP[SettingKey.DOWNLOAD_PATH],
        os.path.join(storage_root, "downloads"),
    )
    temp = _get_optional_env_path(
        PATH_ENV_MAP[SettingKey.TEMP_PATH],
        os.path.join(storage_root, "tmp"),
    )
    extracted = _get_optional_env_path(
        PATH_ENV_MAP[SettingKey.EXTRACTED_PATH],
        os.path.join(storage_root, "extracted"),
    )
    database = _get_optional_env_path("ZIMUKU_DB_PATH", os.path.join(storage_root, "zimuku.db"))
    trash = _get_optional_env_path(
        PATH_ENV_MAP[SettingKey.TRASH_PATH],
        os.path.join(storage_root, "trash"),
    )

    return StoragePaths(
        root=storage_root,
        downloads=downloads,
        temp=temp,
        extracted=extracted,
        database=database,
        trash=trash,
    )


class ConfigManager:
    """系统配置管理器，支持从数据库动态读取与更新"""

    _DEFAULTS = {key: definition.default for key, definition in SETTINGS_DEFINITIONS.items()}
    _DESCRIPTIONS = {key: definition.description for key, definition in SETTINGS_DEFINITIONS.items()}

    @classmethod
    def _load_setting(cls, key: str) -> Optional[Setting]:
        from ..db.session import session_scope

        with session_scope() as session:
            statement = select(Setting).where(Setting.key == key)
            return session.exec(statement).first()

    @classmethod
    def get(cls, key: str, default: Any = None) -> str:
        """获取配置"""
        if key in PATH_ENV_MAP:
            return cls.get_path(key)

        try:
            setting = cls._load_setting(key)
            if setting:
                return setting.value
        except Exception as e:
            logger.error(f"从数据库读取配置出错 ({key}): {e}")

        env_val = os.getenv(f"ZIMUKU_{key.upper()}")
        if env_val:
            return env_val

        return default if default is not None else cls._DEFAULTS.get(key, "")

    @classmethod
    def set(cls, key: str, value: str, description: Optional[str] = None):
        """设置配置"""
        normalized_value = cls.normalize_value(key, value)

        from ..db.session import session_scope

        with session_scope() as session:
            statement = select(Setting).where(Setting.key == key)
            setting = session.exec(statement).first()
            if setting:
                setting.value = normalized_value
                if description:
                    setting.description = description
            else:
                setting = Setting(
                    key=key,
                    value=normalized_value,
                    description=description or cls._DESCRIPTIONS.get(key),
                )
            session.add(setting)
            session.commit()
            session.refresh(setting)
            return setting

    @classmethod
    def list_settings(cls) -> list[Setting]:
        from ..db.session import session_scope

        with session_scope() as session:
            statement = select(Setting).order_by(Setting.key)
            return list(session.exec(statement).all())

    @classmethod
    def get_int(cls, key: str, default: int) -> int:
        value = cls.get(key, str(default))
        try:
            return int(value)
        except (TypeError, ValueError):
            logger.warning("配置 %s=%r 不是合法整数，回退到默认值 %s", key, value, default)
            return default

    @classmethod
    def get_bool(cls, key: str, default: bool) -> bool:
        value = str(cls.get(key, "true" if default else "false")).strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
        logger.warning("配置 %s=%r 不是合法布尔值，回退到默认值 %s", key, value, default)
        return default

    @classmethod
    def get_path(cls, key: str) -> str:
        paths = get_storage_paths()
        derived_paths = {
            SettingKey.DOWNLOAD_PATH: paths.downloads,
            SettingKey.TEMP_PATH: paths.temp,
            SettingKey.EXTRACTED_PATH: paths.extracted,
            SettingKey.TRASH_PATH: paths.trash,
        }
        env_name = PATH_ENV_MAP.get(key)
        if env_name and os.getenv(env_name):
            return _ensure_directory(derived_paths[key])

        try:
            setting = cls._load_setting(key)
            if setting and setting.value:
                return _ensure_directory(cls.normalize_value(key, setting.value))
        except Exception as e:
            logger.error("从数据库读取路径配置出错 (%s): %s", key, e)

        return _ensure_directory(derived_paths[key])

    @classmethod
    def normalize_value(cls, key: str, value: str) -> str:
        if value is None:
            raise ValueError(f"配置 {key} 不能为空")

        normalized = value.strip()
        if key in PATH_ENV_MAP:
            if not normalized:
                raise ValueError(f"路径配置 {key} 不能为空")
            return _normalize_path(normalized)

        if key == SettingKey.CACHE_EXPIRY_HOURS:
            try:
                numeric_value = int(normalized)
            except ValueError as exc:
                raise ValueError("cache_expiry_hours 必须是整数") from exc
            if numeric_value <= 0:
                raise ValueError("cache_expiry_hours 必须大于 0")
            return str(numeric_value)

        if key == SettingKey.TRASH_RETENTION_DAYS:
            try:
                numeric_value = int(normalized)
            except ValueError as exc:
                raise ValueError("trash_retention_days 必须是整数") from exc
            if numeric_value < 0:
                raise ValueError("trash_retention_days 必须大于等于 0（0 表示永久保留）")
            return str(numeric_value)

        if key in BOOL_SETTING_KEYS:
            lowered = normalized.lower()
            if lowered in {"true", "1", "yes", "on"}:
                return "true"
            if lowered in {"false", "0", "no", "off"}:
                return "false"
            raise ValueError(f"{key} 必须是布尔值（true/false）")

        if key == SettingKey.SCHEDULE_CRON:
            from apscheduler.triggers.cron import CronTrigger

            try:
                CronTrigger.from_crontab(normalized)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"schedule_cron 不是合法的 5 段式 cron 表达式: {normalized}") from exc
            return normalized

        if key == SettingKey.SCHEDULE_MAX_WORKS_PER_RUN:
            try:
                numeric_value = int(normalized)
            except ValueError as exc:
                raise ValueError("schedule_max_works_per_run 必须是整数") from exc
            if numeric_value < 0:
                raise ValueError("schedule_max_works_per_run 必须大于等于 0（0 表示不限）")
            return str(numeric_value)

        if key == SettingKey.FEISHU_WEBHOOK_URL:
            if normalized and not normalized.startswith(("http://", "https://")):
                raise ValueError("feishu_webhook_url 必须是 http(s) 地址")
            return normalized

        if key == SettingKey.JELLYFIN_BASE_URL:
            if normalized and not normalized.startswith(("http://", "https://")):
                raise ValueError("jellyfin_base_url 必须是 http(s) 地址")
            return normalized.rstrip("/")

        if key == SettingKey.JELLYFIN_USER_ID:
            if not normalized:
                return ""
            compact = normalized.replace("-", "").lower()
            if len(compact) != 32 or any(char not in "0123456789abcdef" for char in compact):
                raise ValueError("jellyfin_user_id 必须是合法的 Jellyfin 用户 GUID（32 位十六进制）")
            return compact

        return normalized

    @classmethod
    def default_settings(cls) -> list[Setting]:
        return [
            Setting(
                key=definition.key,
                value=definition.default,
                description=definition.description,
            )
            for definition in SETTINGS_DEFINITIONS.values()
        ]


# 预定义的辅助函数
def get_proxy() -> Optional[str]:
    proxy = ConfigManager.get(SettingKey.PROXY)
    return proxy if proxy else None


def get_base_url() -> str:
    return ConfigManager.get(SettingKey.BASE_URL)


def get_storage_path() -> str:
    """获取存储根目录的绝对路径"""
    return _ensure_directory(get_storage_paths().root)


def get_download_path() -> str:
    return ConfigManager.get_path(SettingKey.DOWNLOAD_PATH)


def get_temp_path() -> str:
    return ConfigManager.get_path(SettingKey.TEMP_PATH)


def get_extracted_path() -> str:
    return ConfigManager.get_path(SettingKey.EXTRACTED_PATH)


def get_trash_path() -> str:
    """获取字幕回收站存储路径"""
    return _ensure_directory(get_storage_paths().trash)


def get_database_path() -> str:
    return get_storage_paths().database
