from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.db.session as db_session
from app.db.models import SearchCache, Setting, SubtitleTask

# 使用内存数据库进行测试
sqlite_url = "sqlite://"
test_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})


@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session
    SQLModel.metadata.drop_all(test_engine)


def test_create_setting(session: Session):
    setting = Setting(key="test_key", value="test_value", description="test_desc")
    session.add(setting)
    session.commit()
    session.refresh(setting)

    assert setting.id is not None
    assert setting.key == "test_key"

    # Read
    db_setting = session.exec(select(Setting).where(Setting.key == "test_key")).first()
    assert db_setting.value == "test_value"


def test_update_setting(session: Session):
    # Ensure exists
    setting = session.exec(select(Setting).where(Setting.key == "test_key")).first()
    if not setting:
        setting = Setting(key="test_key", value="old_value")
        session.add(setting)
        session.commit()

    setting.value = "new_value"
    session.add(setting)
    session.commit()

    db_setting = session.exec(select(Setting).where(Setting.key == "test_key")).first()
    assert db_setting.value == "new_value"


def test_search_cache(session: Session):
    cache = SearchCache(
        query="avatar",
        results_json='[{"title": "Avatar 2"}]',
        expires_at=datetime.now() + timedelta(days=1),
    )
    session.add(cache)
    session.commit()

    db_cache = session.exec(select(SearchCache).where(SearchCache.query == "avatar")).first()
    assert db_cache is not None
    assert "Avatar 2" in db_cache.results_json


def test_subtitle_task(session: Session):
    task = SubtitleTask(title="Avengers", source_url="http://example.com")
    session.add(task)
    session.commit()

    db_task = session.exec(select(SubtitleTask).where(SubtitleTask.title == "Avengers")).first()
    assert db_task.status == "pending"


def test_database_initialization_migrates_nfo_search_columns(monkeypatch):
    legacy_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE scannedfile (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(db_session, "engine", legacy_engine)
    db_session.create_db_and_tables()

    with legacy_engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(scannedfile)")}
        indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(scannedfile)")}

    assert {"nfo_title", "nfo_original_title", "nfo_aliases"}.issubset(columns)
    assert {"ix_scannedfile_nfo_title", "ix_scannedfile_nfo_original_title"}.issubset(indexes)


def test_database_initialization_migrates_subtitle_task_columns(monkeypatch):
    legacy_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE subtitletask (id INTEGER PRIMARY KEY, title VARCHAR, source_url VARCHAR, status VARCHAR)"
        )

    monkeypatch.setattr(db_session, "engine", legacy_engine)
    db_session.create_db_and_tables()

    with legacy_engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(subtitletask)")}
        indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(subtitletask)")}

    assert "file_id" in columns
    assert "ix_subtitletask_file_id" in indexes


def test_database_initialization_migrates_legacy_jellyfin_settings(monkeypatch):
    legacy_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(legacy_engine)
    with Session(legacy_engine) as session:
        session.add(Setting(key="jellyfin_enabled", value="true"))
        session.add(Setting(key="jellyfin_base_url", value="http://jf.local:8096/"))
        session.add(Setting(key="jellyfin_api_key", value="legacy-key"))
        session.add(Setting(key="jellyfin_user_id", value="0123456789abcdef0123456789abcdef"))
        session.commit()

    monkeypatch.setattr(db_session, "engine", legacy_engine)
    db_session.create_db_and_tables()

    with Session(legacy_engine) as session:
        settings = {s.key: s.value for s in session.exec(select(Setting)).all()}

    assert not any(key.startswith("jellyfin_") for key in settings)
    assert settings["media_server_enabled"] == "true"
    assert settings["media_server_base_url"] == "http://jf.local:8096"
    assert settings["media_server_api_key"] == "legacy-key"
    assert settings["media_server_user_id"] == "0123456789abcdef0123456789abcdef"


def test_legacy_jellyfin_settings_migration_keeps_existing_media_server_values(monkeypatch):
    legacy_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(legacy_engine)
    with Session(legacy_engine) as session:
        session.add(Setting(key="jellyfin_base_url", value="http://old.local:8096"))
        session.add(Setting(key="jellyfin_enabled", value="false"))
        session.add(Setting(key="media_server_base_url", value="http://new.local:8096"))
        session.commit()

    monkeypatch.setattr(db_session, "engine", legacy_engine)
    db_session.create_db_and_tables()

    with Session(legacy_engine) as session:
        settings = {s.key: s.value for s in session.exec(select(Setting)).all()}

    assert "jellyfin_base_url" not in settings
    assert "jellyfin_enabled" not in settings
    assert settings["media_server_base_url"] == "http://new.local:8096"
    assert settings["media_server_enabled"] == "false"
