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
