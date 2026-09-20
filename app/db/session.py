import os
from contextlib import contextmanager

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from ..core.config import ConfigManager, get_database_path


def _get_sqlite_url() -> str:
    database_url = os.getenv("ZIMUKU_DATABASE_URL")
    if database_url:
        return database_url

    db_path = get_database_path()
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    return f"sqlite:///{db_path}"


sqlite_url = _get_sqlite_url()

# 连接池设置 (对于 SQLite 主要是为了在多线程/多协程下稳定运行)
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


NFO_SEARCH_COLUMNS = {
    "nfo_title": "VARCHAR",
    "nfo_original_title": "VARCHAR",
    "nfo_aliases": "VARCHAR",
}

SCANNED_FILE_FLAG_COLUMNS = {
    "allow_no_subtitle": "BOOLEAN NOT NULL DEFAULT 0",
}

SUBTITLE_TASK_MIGRATION_COLUMNS = {
    "file_id": "INTEGER",
}


# 旧版 jellyfin_* 设置键 → 新版 media_server_* 设置键
LEGACY_JELLYFIN_SETTING_KEYS = {
    "jellyfin_enabled": "media_server_enabled",
    "jellyfin_base_url": "media_server_base_url",
    "jellyfin_api_key": "media_server_api_key",
    "jellyfin_user_id": "media_server_user_id",
}


def create_db_and_tables():
    """初始化数据库表"""
    SQLModel.metadata.create_all(engine)
    _migrate_scanned_file_metadata_columns()
    _migrate_subtitle_task_columns()

    # 迁移旧版 jellyfin_* 设置（需在默认配置初始化前执行，保证迁移值不被默认值覆盖）
    _migrate_legacy_jellyfin_settings()

    # 初始化默认配置项
    _init_default_settings()


def _migrate_scanned_file_metadata_columns():
    """为已有 SQLite 数据库补充扫描媒体的 NFO 搜索字段。"""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        existing_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scannedfile)")}
        for name, column_type in {**NFO_SEARCH_COLUMNS, **SCANNED_FILE_FLAG_COLUMNS}.items():
            if name not in existing_columns:
                connection.exec_driver_sql(f"ALTER TABLE scannedfile ADD COLUMN {name} {column_type}")

        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_scannedfile_nfo_title ON scannedfile (nfo_title)")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_scannedfile_nfo_original_title ON scannedfile (nfo_original_title)"
        )


def _migrate_subtitle_task_columns():
    """为已有 SQLite 数据库补充字幕任务的关联字段。"""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        existing_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(subtitletask)")}
        if not existing_columns:
            return
        for name, column_type in SUBTITLE_TASK_MIGRATION_COLUMNS.items():
            if name not in existing_columns:
                connection.exec_driver_sql(f"ALTER TABLE subtitletask ADD COLUMN {name} {column_type}")

        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_subtitletask_file_id ON subtitletask (file_id)")


def _migrate_legacy_jellyfin_settings():
    """将旧版 jellyfin_* 设置合并到 media_server_* 并删除旧键，避免旧键残留出现在通用设置列表中。

    合并规则：新键不存在时以旧值创建；新键为空且旧值非空时回填；
    media_server_enabled 仅在旧值为 true 且新值仍为默认 false 时置位。
    旧值无法通过新键校验（如非法 GUID）时跳过合并，仅删除旧键。
    """
    from sqlmodel import select

    from .models import Setting

    with Session(engine) as session:
        legacy_rows = session.exec(select(Setting).where(Setting.key.in_(LEGACY_JELLYFIN_SETTING_KEYS))).all()
        if not legacy_rows:
            return

        for legacy in legacy_rows:
            new_key = LEGACY_JELLYFIN_SETTING_KEYS[legacy.key]
            try:
                value = ConfigManager.normalize_value(new_key, legacy.value)
            except ValueError:
                value = None

            if value is not None:
                new_row = session.exec(select(Setting).where(Setting.key == new_key)).first()
                if new_row is None:
                    session.add(
                        Setting(
                            key=new_key,
                            value=value,
                            description=ConfigManager._DESCRIPTIONS.get(new_key),
                        )
                    )
                elif not new_row.value and value:
                    new_row.value = value
                elif new_key == "media_server_enabled" and value == "true" and new_row.value == "false":
                    new_row.value = value

            session.delete(legacy)
        session.commit()


def _init_default_settings():
    """初始化默认配置项到数据库（仅补充缺失的键，不覆盖已有配置）"""
    from sqlmodel import select

    from .models import Setting

    with Session(engine) as session:
        existing_keys = set(session.exec(select(Setting.key)).all())
        default_settings = [s for s in ConfigManager.default_settings() if s.key not in existing_keys]
        if not default_settings:
            return

        for setting in default_settings:
            session.add(setting)
        session.commit()


def get_session():
    """FastAPI 依赖项：获取数据库会话"""
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    """为后台任务提供独立、短生命周期的数据库会话。"""
    with Session(engine) as session:
        yield session
