from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.db.models import MediaPath, ScannedFile, SubtitleTask
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.mcp.server import handle_call_tool, handle_list_tools
from app.services.download_workflow import (
    DownloadArtifact,
    SubtitleFileSelector,
    SubtitleMover,
)
from app.services.task_service import TaskService

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_records():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(SubtitleTask))
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(SubtitleTask))
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()


def test_subtitle_mover_video_file_as_target_path(tmp_path: Path):
    tv_dir = tmp_path / "TV" / "Common Side Effects" / "Season 2"
    tv_dir.mkdir(parents=True, exist_ok=True)
    video_file = tv_dir / "Common.Side.Effects.S02E04.mkv"
    video_file.write_bytes(b"dummy video")

    # 针对 TV 剧集，用户直接传了具体的视频文件路径
    task = SubtitleTask(
        title="Common.Side.Effects.S02E04",
        source_url="https://zimuku.org/detail/123.html",
        target_path=str(video_file),
        target_type="tv",
        season=2,
        episode=4,
        language="zh-CN-en",
    )

    resolved_dir = SubtitleMover.resolve_target_directory(task)
    assert resolved_dir == str(tv_dir)

    video_basename = SubtitleMover.find_video_basename(task, resolved_dir)
    assert video_basename == "Common.Side.Effects.S02E04"

    # 模拟移动字幕
    sub_source = tmp_path / "downloaded.ass"
    sub_source.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,治愈癌症\\NCure for cancer
""",
        encoding="utf-8",
    )

    dest = SubtitleMover.move(task, str(sub_source))
    expected_path = tv_dir / "Common.Side.Effects.S02E04.zh-CN-en.ass"
    assert dest == str(expected_path)
    assert expected_path.exists()


def test_subtitle_mover_language_auto_detection_and_no_collision(tmp_path: Path):
    media_dir = tmp_path / "Movies"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_file = media_dir / "Inception.2010.mkv"
    video_file.write_bytes(b"dummy")

    # language 未指定时，自动通过字幕内容检测双语并命名
    task = SubtitleTask(
        title="Inception",
        source_url="https://zimuku.org/detail/456.html",
        target_path=str(video_file),
        target_type="movie",
        language=None,
    )

    sub_source = tmp_path / "temp.ass"
    sub_source.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,我们在梦境之中\\NWe are in a dream
""",
        encoding="utf-8",
    )

    dest = SubtitleMover.move(task, str(sub_source))
    expected = media_dir / "Inception.2010.zh-CN-en.ass"
    assert dest == str(expected)
    assert expected.exists()

    # 再次移动同名文件时，应自动递增序号，避免直接覆盖
    sub_source_2 = tmp_path / "temp2.ass"
    sub_source_2.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,我们在第二层梦境之中\\NWe are in a deeper dream
""",
        encoding="utf-8",
    )
    dest_2 = SubtitleMover.move(task, str(sub_source_2))
    expected_2 = media_dir / "Inception.2010.zh-CN-en.2.ass"
    assert dest_2 == str(expected_2)
    assert expected_2.exists()


def test_subtitle_file_selector_episode_preference(tmp_path: Path):
    extract_dir = tmp_path / "extracted_season_pack"
    extract_dir.mkdir(parents=True, exist_ok=True)

    (extract_dir / "Common.Side.Effects.S02E01.chs.srt").write_text("ep1")
    (extract_dir / "Common.Side.Effects.S02E04.chs&eng.ass").write_text("ep4 ass")
    (extract_dir / "Common.Side.Effects.S02E04.chs.srt").write_text("ep4 srt")
    (extract_dir / "Common.Side.Effects.S02E08.chs&eng.ass").write_text("ep8")

    best_ep4 = SubtitleFileSelector.select_best(str(extract_dir), season=2, episode=4)
    assert "S02E04" in best_ep4
    assert best_ep4.endswith(".ass")  # 优先选择双语 ASS


def _setup_scanned_video(tmp_path: Path) -> int:
    media_dir = tmp_path / "TV" / "Common Side Effects (2025)" / "Season 2"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_path = media_dir / "Common Side Effects - S02E04 - Episode 4.mkv"
    video_path.write_bytes(b"dummy")

    with Session(engine) as session:
        mp = MediaPath(path=str(media_dir.parent.parent), type="tv")
        session.add(mp)
        session.commit()
        session.refresh(mp)

        sf = ScannedFile(
            path_id=mp.id,
            type="tv",
            file_path=str(video_path),
            filename=video_path.name,
            extracted_title="Common Side Effects",
            season=2,
            episode=4,
            has_subtitle=False,
        )
        session.add(sf)
        session.commit()
        session.refresh(sf)
        assert sf.id is not None
        return sf.id


@pytest.mark.anyio
async def test_task_service_run_download_task_with_file_id(tmp_path: Path):
    file_id = _setup_scanned_video(tmp_path)

    # 模拟下载文件
    downloaded_sub = tmp_path / "mock_download.ass"
    downloaded_sub.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,测试对白\\NTest dialogue
""",
        encoding="utf-8",
    )

    artifact = DownloadArtifact(
        filename="mock_download.ass",
        file_path=str(downloaded_sub),
        save_path=str(downloaded_sub),
        extracted_files=[str(downloaded_sub)],
    )

    with patch("app.services.task_service.DownloadWorkflow") as mock_workflow_cls:
        mock_wf = mock_workflow_cls.return_value
        mock_wf.execute = AsyncMock(return_value=artifact)
        mock_wf.close = AsyncMock()

        with Session(engine) as session:
            task = TaskService.create_task(
                session,
                title="",
                source_url="https://zimuku.org/detail/789.html",
                language="zh-CN-en",
                file_id=file_id,
            )
            assert task.id is not None
            assert task.target_path is not None
            assert "Common Side Effects - S02E04" in task.target_path
            assert task.season == 2
            assert task.episode == 4
            task_id = task.id

        await TaskService.run_download_task(task_id)

        with Session(engine) as session:
            completed_task = session.get(SubtitleTask, task_id)
            assert completed_task is not None
            assert completed_task.status == "completed"

            # 验证 ScannedFile 状态被成功更新为 has_subtitle=True
            media_record = session.get(ScannedFile, file_id)
            assert media_record is not None
            assert media_record.has_subtitle is True


def test_api_download_subtitle_for_file(tmp_path: Path):
    file_id = _setup_scanned_video(tmp_path)

    with patch("app.services.task_service.TaskService.run_download_task") as mock_run:
        mock_run.return_value = None
        resp = client.post(
            f"/media/files/{file_id}/download-subtitle",
            json={
                "source_url": "https://zimuku.org/detail/s02e04.html",
                "language": "zh-CN-en",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_url"] == "https://zimuku.org/detail/s02e04.html"
        assert data["file_id"] == file_id
        assert data["season"] == 2
        assert data["episode"] == 4


@pytest.mark.anyio
async def test_mcp_download_subtitle_for_file_tool(tmp_path: Path):
    file_id = _setup_scanned_video(tmp_path)

    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "download_subtitle_for_file" in tool_names

    with patch("app.services.task_service.TaskService.run_download_task") as mock_run:
        mock_run.return_value = None
        res = await handle_call_tool(
            "download_subtitle_for_file",
            {
                "file_id": file_id,
                "source_url": "https://zimuku.org/detail/s02e04.html",
                "language": "zh-CN-en",
            },
        )
        assert len(res) > 0
        assert "字幕下载任务已执行" in res[0].text or "字幕下载并关联归档成功" in res[0].text
