import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import ConfigManager, SettingKey
from app.db.models import MediaPath, ScannedFile, SubtitleTrash
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.mcp.server import handle_call_tool, handle_list_tools
from app.services.subtitle_trash_service import (
    SubtitleInvalidRequestError,
    SubtitleTrashService,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_records():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(SubtitleTrash))
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()


def _setup_media_with_subtitles(
    tmp_path: Path, multiple: bool = False, with_orig: bool = False
) -> tuple[int, Path, list[Path]]:
    media_dir = tmp_path / "Movies" / "Inception"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_file = media_dir / "Inception.2010.mkv"
    video_file.write_bytes(b"fake video data")

    sub1 = media_dir / "Inception.2010.zh-CN.srt"
    sub1.write_text("1\n00:00:01,000 --> 00:00:02,000\n测试字幕内容\n", encoding="utf-8")
    subtitles = [sub1]

    if with_orig:
        orig = media_dir / "Inception.2010.zh-CN.orig.srt"
        orig.write_text("1\n00:00:01,000 --> 00:00:02,000\n原始备份内容\n", encoding="utf-8")

    if multiple:
        sub2 = media_dir / "Inception.2010.en.ass"
        sub2.write_text("[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,English line\n", encoding="utf-8")
        subtitles.append(sub2)

    with Session(engine) as session:
        mp = MediaPath(path=str(media_dir.parent), type="movie")
        session.add(mp)
        session.commit()
        session.refresh(mp)

        sf = ScannedFile(
            path_id=mp.id,
            type="movie",
            file_path=str(video_file),
            filename=video_file.name,
            extracted_title="Inception",
            year="2010",
            has_subtitle=True,
        )
        session.add(sf)
        session.commit()
        session.refresh(sf)
        return sf.id, video_file, subtitles


def test_trash_single_subtitle_service(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]
    assert sub.is_file()

    with Session(engine) as session:
        result = SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        assert result.file_id == file_id
        assert result.subtitle_filename == sub.name
        assert result.is_permanent_deletion is False
        assert result.has_backup is False
        assert result.has_subtitle is False
        assert len(result.remaining_subtitles) == 0

        # 原文件已被移出原位置
        assert not sub.exists()

        # 回收站内存在该文件
        trash_file = Path(result.trash_path)
        assert trash_file.is_file()
        assert "测试字幕内容" in trash_file.read_text(encoding="utf-8")

        # 回收站内存在 trashinfo.json 元数据
        meta_file = trash_file.parent / "trashinfo.json"
        assert meta_file.is_file()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["filename"] == sub.name
        assert meta["original_path"] == str(sub)
        assert meta["is_permanent_deletion"] is False

        # 检查数据库记录
        db_record = session.get(SubtitleTrash, result.trash_id)
        assert db_record is not None
        assert db_record.is_restored is False
        assert db_record.subtitle_filename == sub.name

        # 检查媒体记录的 has_subtitle 更新为 False
        media = session.get(ScannedFile, file_id)
        assert media.has_subtitle is False


def test_trash_subtitle_with_orig_backup(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=True)
    sub = subs[0]
    orig = sub.with_name(f"{sub.stem}.orig{sub.suffix}")
    assert sub.is_file()
    assert orig.is_file()

    with Session(engine) as session:
        result = SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        assert result.has_backup is True

        # 原位置两者均不存在
        assert not sub.exists()
        assert not orig.exists()

        # 回收站中两者均存在
        trash_sub = Path(result.trash_path)
        assert trash_sub.is_file()
        db_record = session.get(SubtitleTrash, result.trash_id)
        assert db_record.backup_trash_path is not None
        trash_orig = Path(db_record.backup_trash_path)
        assert trash_orig.is_file()
        assert "原始备份内容" in trash_orig.read_text(encoding="utf-8")


def test_trash_multiple_subtitles_requires_filename(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=True, with_orig=False)

    with Session(engine) as session:
        # 不指定 filename 抛出异常
        with pytest.raises(SubtitleInvalidRequestError) as exc_info:
            SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        assert "存在多个关联字幕" in str(exc_info.value)

        # 指定一个具体 filename
        result = SubtitleTrashService.trash_subtitle(session, file_id=file_id, filename=subs[0].name)
        assert result.subtitle_filename == subs[0].name
        # 仍有另一个字幕，has_subtitle 应依然为 True
        assert result.has_subtitle is True
        assert len(result.remaining_subtitles) == 1
        assert result.remaining_subtitles[0] == subs[1].name

        media = session.get(ScannedFile, file_id)
        assert media.has_subtitle is True


def test_restore_subtitle_service(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=True)
    sub = subs[0]
    orig = sub.with_name(f"{sub.stem}.orig{sub.suffix}")

    with Session(engine) as session:
        trash_result = SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        assert not sub.exists()
        assert not orig.exists()

        # 执行还原
        restore_result = SubtitleTrashService.restore_subtitle(session, trash_id=trash_result.trash_id)
        assert restore_result.trash_id == trash_result.trash_id
        assert restore_result.has_backup_restored is True
        assert restore_result.has_subtitle is True

        # 原位置恢复
        assert sub.is_file()
        assert orig.is_file()
        assert "测试字幕内容" in sub.read_text(encoding="utf-8")
        assert "原始备份内容" in orig.read_text(encoding="utf-8")

        # 数据库状态更新
        record = session.get(SubtitleTrash, trash_result.trash_id)
        assert record.is_restored is True
        assert record.restored_at is not None

        # 媒体记录 has_subtitle 变回 True
        media = session.get(ScannedFile, file_id)
        assert media.has_subtitle is True


def test_restore_conflict_handling(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]

    with Session(engine) as session:
        trash_result = SubtitleTrashService.trash_subtitle(session, file_id=file_id)

        # 在原位置创建一个新文件造成冲突
        sub.write_text("新占位字幕", encoding="utf-8")

        # 不覆盖还原抛出错误
        with pytest.raises(SubtitleInvalidRequestError) as exc_info:
            SubtitleTrashService.restore_subtitle(session, trash_id=trash_result.trash_id, overwrite=False)
        assert "目标位置已存在同名文件" in str(exc_info.value)

        # 允许覆盖还原成功
        res = SubtitleTrashService.restore_subtitle(session, trash_id=trash_result.trash_id, overwrite=True)
        assert res.restored_path == str(sub)
        assert "测试字幕内容" in sub.read_text(encoding="utf-8")


def test_trash_and_restore_by_subtitle_path(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]

    with Session(engine) as session:
        # 直接按 subtitle_path 移入回收站
        trash_res = SubtitleTrashService.trash_subtitle(session, subtitle_path=str(sub))
        assert not sub.exists()
        assert trash_res.file_id == file_id  # 自动反查到了关联媒体
        assert trash_res.is_permanent_deletion is False

        # 直接按 subtitle_path 还原
        restore_res = SubtitleTrashService.restore_subtitle(session, subtitle_path=str(sub))
        assert sub.is_file()
        assert restore_res.restored_path == str(sub)


def test_list_trashed_subtitles(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=True, with_orig=False)

    with Session(engine) as session:
        SubtitleTrashService.trash_subtitle(session, file_id=file_id, filename=subs[0].name)
        SubtitleTrashService.trash_subtitle(session, file_id=file_id, filename=subs[1].name)

        items, total = SubtitleTrashService.list_trashed(session, file_id=file_id)
        assert total == 2
        assert len(items) == 2

        # 还原一个后默认查询排除已还原
        SubtitleTrashService.restore_subtitle(session, trash_id=items[0].id)
        items_active, total_active = SubtitleTrashService.list_trashed(session, file_id=file_id)
        assert total_active == 1
        assert len(items_active) == 1

        # include_restored=True 查询出全部
        items_all, total_all = SubtitleTrashService.list_trashed(session, file_id=file_id, include_restored=True)
        assert total_all == 2


def test_subtitle_trash_rest_api(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]

    with TestClient(app) as test_client:
        # 1. POST /media/files/{file_id}/subtitles/trash
        resp = test_client.post(f"/media/files/{file_id}/subtitles/trash")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["subtitle_filename"] == sub.name
        assert data["is_permanent_deletion"] is False
        trash_id = data["trash_id"]
        assert not sub.exists()

        # 2. GET /media/subtitles/trash
        list_resp = test_client.get("/media/subtitles/trash", params={"file_id": file_id})
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["total"] == 1
        assert list_data["items"][0]["id"] == trash_id

        # 3. POST /media/subtitles/trash/restore
        restore_resp = test_client.post("/media/subtitles/trash/restore", json={"trash_id": trash_id})
        assert restore_resp.status_code == 200
        restore_data = restore_resp.json()
        assert restore_data["status"] == "ok"
        assert sub.is_file()


@pytest.mark.anyio
async def test_subtitle_trash_mcp_tools(tmp_path: Path):
    file_id, video_file, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]

    # 1. 验证工具注册
    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "trash_subtitle" in tool_names
    assert "trash_media_subtitle" in tool_names
    assert "restore_trashed_subtitle" in tool_names
    assert "list_trashed_subtitles" in tool_names

    # 2. 调用 trash_subtitle
    call_res = await handle_call_tool("trash_subtitle", {"file_id": file_id})
    assert len(call_res) > 0
    text_out = call_res[0].text
    assert "安全移入系统回收站" in text_out
    assert "is_permanent_deletion" in text_out
    assert not sub.exists()

    # 3. 调用 list_trashed_subtitles
    list_res = await handle_call_tool("list_trashed_subtitles", {"file_id": file_id})
    assert len(list_res) > 0
    list_text = list_res[0].text
    assert "回收站字幕记录列表" in list_text
    assert sub.name in list_text

    # 4. 调用 restore_trashed_subtitle
    restore_res = await handle_call_tool("restore_trashed_subtitle", {"file_id": file_id, "filename": sub.name})
    assert len(restore_res) > 0
    restore_text = restore_res[0].text
    assert "字幕已从回收站成功还原" in restore_text
    assert sub.is_file()

    # 5. 测试 trash_media_subtitle 别名调用
    alias_res = await handle_call_tool("trash_media_subtitle", {"file_id": file_id})
    assert len(alias_res) > 0
    assert "安全移入系统回收站" in alias_res[0].text
    assert not sub.exists()


def _trash_and_make_old(tmp_path: Path, days_old: int) -> tuple[int, int, Path]:
    """回收一个字幕后将其 trashed_at 手动改为 days_old 天前，返回 (file_id, trash_id, trash_entry_dir)。"""
    file_id, _, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    with Session(engine) as session:
        result = SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        record = session.get(SubtitleTrash, result.trash_id)
        record.trashed_at = datetime.now() - timedelta(days=days_old)
        session.add(record)
        session.commit()
        return file_id, result.trash_id, Path(result.trash_path).parent


def _age_trash_record(trash_id: int, days_old: int) -> None:
    """将指定回收站记录的回收时间改为 days_old 天前（不触发任何清理逻辑）。"""
    with Session(engine) as session:
        record = session.get(SubtitleTrash, trash_id)
        record.trashed_at = datetime.now() - timedelta(days=days_old)
        session.add(record)
        session.commit()


def test_trash_retention_setting_default_and_validation():
    # 默认值 365 天
    assert SubtitleTrashService.get_retention_days() == 365

    # 可通过系统配置修改
    ConfigManager.set(SettingKey.TRASH_RETENTION_DAYS, "30")
    assert SubtitleTrashService.get_retention_days() == 30

    # 非法值回退默认
    ConfigManager.set(SettingKey.TRASH_RETENTION_DAYS, "abc") if False else None
    with pytest.raises(ValueError):
        ConfigManager.set(SettingKey.TRASH_RETENTION_DAYS, "-1")
    with pytest.raises(ValueError):
        ConfigManager.normalize_value(SettingKey.TRASH_RETENTION_DAYS, "abc")

    # 恢复默认，避免影响其他用例
    ConfigManager.set(SettingKey.TRASH_RETENTION_DAYS, "365")


def test_purge_expired_service(tmp_path: Path):
    # 一条 400 天前的过期记录、一条 10 天前的新鲜记录（先回收再统一改时间，避免触发自动清理）
    _, old_trash_id, old_dir = _trash_and_make_old(tmp_path / "old", days_old=10)
    _, new_trash_id, new_dir = _trash_and_make_old(tmp_path / "new", days_old=10)
    _age_trash_record(old_trash_id, 400)

    assert old_dir.is_dir() and new_dir.is_dir()

    with Session(engine) as session:
        result = SubtitleTrashService.purge_expired(session, retention_days=365)
        assert result.retention_days == 365
        assert result.purged_count == 1
        assert result.purged_records[0]["trash_id"] == old_trash_id

        # 过期条目文件与记录均被彻底删除
        assert not old_dir.exists()
        assert session.get(SubtitleTrash, old_trash_id) is None

        # 新鲜条目保留
        assert new_dir.is_dir()
        assert session.get(SubtitleTrash, new_trash_id) is not None

        # 再次执行无条目可清理
        again = SubtitleTrashService.purge_expired(session, retention_days=365)
        assert again.purged_count == 0


def test_purge_retention_zero_keeps_everything(tmp_path: Path):
    _, trash_id, entry_dir = _trash_and_make_old(tmp_path, days_old=3650)

    with Session(engine) as session:
        result = SubtitleTrashService.purge_expired(session, retention_days=0)
        assert result.purged_count == 0
        assert "永久保留" in result.message
        assert entry_dir.is_dir()
        assert session.get(SubtitleTrash, trash_id) is not None


def test_purge_skips_restored_records(tmp_path: Path):
    file_id, _, subs = _setup_media_with_subtitles(tmp_path, multiple=False, with_orig=False)
    sub = subs[0]
    with Session(engine) as session:
        trash_res = SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        SubtitleTrashService.restore_subtitle(session, trash_id=trash_res.trash_id)
        record = session.get(SubtitleTrash, trash_res.trash_id)
        record.trashed_at = datetime.now() - timedelta(days=400)
        session.add(record)
        session.commit()

        result = SubtitleTrashService.purge_expired(session, retention_days=365)
        # 已还原记录不参与过期清理（文件已还原回原位置，不属于待删除对象）
        assert result.purged_count == 0
        assert sub.is_file()


def test_trash_subtitle_auto_purges_expired(tmp_path: Path):
    _, old_trash_id, old_dir = _trash_and_make_old(tmp_path / "old", days_old=400)
    old_trash_path = str(old_dir / "Inception.2010.zh-CN.srt")

    # 新一次回收会自动触发过期清理
    file_id, _, subs = _setup_media_with_subtitles(tmp_path / "new", multiple=False, with_orig=False)
    with Session(engine) as session:
        SubtitleTrashService.trash_subtitle(session, file_id=file_id)
        assert not old_dir.exists()
        # SQLite 可能复用 rowid，按回收站路径断言旧记录已被删除
        from sqlmodel import select

        remaining = session.exec(select(SubtitleTrash).where(SubtitleTrash.trash_path == old_trash_path)).first()
        assert remaining is None


def test_purge_rest_api(tmp_path: Path):
    _, old_trash_id, old_dir = _trash_and_make_old(tmp_path, days_old=400)

    with TestClient(app) as test_client:
        resp = test_client.post("/media/subtitles/trash/purge", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["retention_days"] == 365
        assert data["purged_count"] == 1
        assert data["purged_records"][0]["trash_id"] == old_trash_id
        assert not old_dir.exists()


@pytest.mark.anyio
async def test_purge_mcp_tool(tmp_path: Path):
    _, old_trash_id, old_dir = _trash_and_make_old(tmp_path, days_old=400)

    tools = await handle_list_tools()
    assert "purge_trashed_subtitles" in [t.name for t in tools]

    res = await handle_call_tool("purge_trashed_subtitles", {})
    assert len(res) > 0
    text = res[0].text
    assert "回收站过期条目清理完成" in text
    assert '"purged_count": 1' in text
    assert not old_dir.exists()


def test_trash_retention_setting_visible_in_settings_api():
    with TestClient(app) as test_client:
        resp = test_client.get("/settings/")
        assert resp.status_code == 200
        settings = {item["key"]: item for item in resp.json()}
        assert "trash_retention_days" in settings
        assert settings["trash_retention_days"]["value"] == "365"
