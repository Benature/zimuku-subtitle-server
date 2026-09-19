from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.aligner import AlignerStatus, SubtitleAligner, SubtitleAlignError
from app.db.models import MediaPath, ScannedFile, SubtitleTask
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.services.subtitle_align_service import SubtitleAlignService
from app.services.subtitle_inspection_service import SubtitleInspectionService

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


def test_aligner_status_detection():
    with patch.object(SubtitleAligner, "find_executable") as mock_find:
        # 1. 均未安装
        mock_find.side_effect = lambda name, env=None: None
        status = SubtitleAligner.get_status()
        assert status.available is False
        assert status.engine is None
        assert "未检测到 ffmpeg" in status.message

        # 2. 仅 ffmpeg
        mock_find.side_effect = lambda name, env=None: "/usr/bin/ffmpeg" if name == "ffmpeg" else None
        status = SubtitleAligner.get_status()
        assert status.available is False
        assert status.ffmpeg_available is True
        assert "未检测到字幕对齐工具" in status.message

        # 3. ffmpeg + alass
        mock_find.side_effect = lambda name, env=None: (
            "/usr/bin/ffmpeg" if name == "ffmpeg" else ("/usr/local/bin/alass" if name == "alass" else None)
        )
        status = SubtitleAligner.get_status()
        assert status.available is True
        assert status.engine == "alass"
        assert status.alass_path == "/usr/local/bin/alass"

        # 4. ffmpeg + ffsubsync (无 alass)
        mock_find.side_effect = lambda name, env=None: (
            "/usr/bin/ffmpeg" if name == "ffmpeg" else ("/usr/local/bin/ffsubsync" if name == "ffsubsync" else None)
        )
        status = SubtitleAligner.get_status()
        assert status.available is True
        assert status.engine == "ffsubsync"


@pytest.mark.anyio
async def test_aligner_file_validations(tmp_path: Path):
    video_file = tmp_path / "movie.mp4"
    video_file.write_bytes(b"fake video")

    sub_file = tmp_path / "movie.zh-CN.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")

    out_file = tmp_path / "movie.zh-CN.aligned.srt"

    # 工具不可用时
    with patch.object(
        SubtitleAligner,
        "get_status",
        return_value=AlignerStatus(
            available=False,
            engine=None,
            ffmpeg_available=False,
            alass_path=None,
            ffsubsync_path=None,
            message="不可用",
        ),
    ):
        with pytest.raises(SubtitleAlignError, match="音轨对齐不可用"):
            await SubtitleAligner.align(video_file, sub_file, out_file)

    # 视频不存在时
    ready_status = AlignerStatus(
        available=True,
        engine="alass",
        ffmpeg_available=True,
        alass_path="/usr/bin/alass",
        ffsubsync_path=None,
        message="就绪",
    )
    with patch.object(SubtitleAligner, "get_status", return_value=ready_status):
        non_existent_video = tmp_path / "not_found.mp4"
        with pytest.raises(SubtitleAlignError, match="参考视频文件不存在"):
            await SubtitleAligner.align(non_existent_video, sub_file, out_file)

        # 不支持图形字幕
        sup_file = tmp_path / "movie.sup"
        sup_file.write_bytes(b"dummy sup")
        with pytest.raises(SubtitleAlignError, match="不支持对齐格式"):
            await SubtitleAligner.align(video_file, sup_file, out_file)


@pytest.mark.anyio
async def test_aligner_run_alass_success(tmp_path: Path):
    video_file = tmp_path / "movie.mp4"
    video_file.write_bytes(b"fake video")

    sub_file = tmp_path / "movie.zh-CN.srt"
    # 用 GBK 编码测试转码兼容性
    sub_file.write_bytes("1\n00:00:01,000 --> 00:00:03,000\n你好世界\n".encode("gbk"))

    out_file = tmp_path / "movie.zh-CN.aligned.srt"

    ready_status = AlignerStatus(
        available=True,
        engine="alass",
        ffmpeg_available=True,
        alass_path="/usr/bin/alass",
        ffsubsync_path=None,
        message="就绪",
    )

    async def fake_run_alass(
        alass_bin, reference_path, input_sub_path, output_sub_path, split_penalty, timeout_seconds
    ):
        assert reference_path == video_file
        assert split_penalty == 7.0
        # 写入模拟输出文件
        output_sub_path.write_text("1\n00:00:02,500 --> 00:00:04,500\n你好世界\n", encoding="utf-8")

    with (
        patch.object(SubtitleAligner, "get_status", return_value=ready_status),
        patch.object(SubtitleAligner, "_run_alass", side_effect=fake_run_alass),
    ):
        await SubtitleAligner.align(video_file, sub_file, out_file)
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "00:00:02,500" in content


@pytest.mark.anyio
async def test_aligner_run_alass_command_failure(tmp_path: Path):
    video_file = tmp_path / "movie.mp4"
    video_file.write_bytes(b"fake video")

    sub_file = tmp_path / "movie.zh-CN.srt"
    sub_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello\n", encoding="utf-8")

    out_file = tmp_path / "out.srt"

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"alass: error processing audio")
    mock_proc.returncode = 1

    with (
        patch.object(
            SubtitleAligner,
            "get_status",
            return_value=AlignerStatus(
                available=True,
                engine="alass",
                ffmpeg_available=True,
                alass_path="/usr/bin/alass",
                ffsubsync_path=None,
                message="就绪",
            ),
        ),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        with pytest.raises(SubtitleAlignError, match="对齐算法执行失败: alass: error processing audio"):
            await SubtitleAligner.align(video_file, sub_file, out_file)


@pytest.mark.anyio
async def test_subtitle_align_service_lifecycle_and_restore(tmp_path: Path):
    video_path = tmp_path / "Inception.1999.mp4"
    video_path.write_bytes(b"video data")

    sub_path = tmp_path / "Inception.1999.zh-CN.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nOriginal\n", encoding="utf-8")

    with Session(engine) as session:
        path_record = MediaPath(path=str(tmp_path), type="movie")
        session.add(path_record)
        session.commit()
        session.refresh(path_record)

        media = ScannedFile(
            path_id=path_record.id,
            type="movie",
            file_path=str(video_path),
            filename=video_path.name,
            has_subtitle=True,
        )
        session.add(media)
        session.commit()
        session.refresh(media)
        file_id = media.id

    # 1. 初始状态：未对齐，无备份
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert len(subs) == 1
        assert subs[0].filename == "Inception.1999.zh-CN.srt"
        assert subs[0].has_backup is False

    # 2. 执行对齐
    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        # 覆盖写入对齐后内容
        output_path.write_text("1\n00:00:05,000 --> 00:00:06,000\nAligned\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        with Session(engine) as session:
            res = await SubtitleAlignService.align_media_subtitle(session, file_id)
            assert res.status == "ok"
            assert res.has_backup is True
            assert res.backup_filename == "Inception.1999.zh-CN.orig.srt"

    # 检查原文件被更新，备份文件保留原样
    backup_file = tmp_path / "Inception.1999.zh-CN.orig.srt"
    assert backup_file.exists()
    assert "Original" in backup_file.read_text(encoding="utf-8")
    assert "Aligned" in sub_path.read_text(encoding="utf-8")

    # 3. 再次查询字幕列表：不应出现两个字幕，应只有一个主字幕且 has_backup=True
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert len(subs) == 1
        assert subs[0].filename == "Inception.1999.zh-CN.srt"
        assert subs[0].has_backup is True
        assert subs[0].backup_filename == "Inception.1999.zh-CN.orig.srt"

    # 4. 执行还原 (Restore)
    with Session(engine) as session:
        restore_res = SubtitleAlignService.restore_media_subtitle(session, file_id, filename="Inception.1999.zh-CN.srt")
        assert restore_res.status == "ok"
        assert restore_res.has_backup is False

    # 还原后，原文件变回 Original，备份文件被删除
    assert not backup_file.exists()
    assert "Original" in sub_path.read_text(encoding="utf-8")

    # 5. 再次查询字幕列表：has_backup 为 False
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert len(subs) == 1
        assert subs[0].has_backup is False


@pytest.mark.anyio
async def test_task_subtitle_align(tmp_path: Path):
    video_path = tmp_path / "Show.S01E01.mp4"
    video_path.write_bytes(b"video data")
    sub_path = tmp_path / "Show.S01E01.zh-CN.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nTask Sub\n", encoding="utf-8")

    with Session(engine) as session:
        task = SubtitleTask(
            title="Show.S01E01",
            source_url="http://zimuku.test/sub/1",
            status="completed",
            target_path=str(video_path),
            save_path=str(sub_path),
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id

    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:10,000 --> 00:00:12,000\nTask Aligned\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        with Session(engine) as session:
            res = await SubtitleAlignService.align_task_subtitle(session, task_id)
            assert res.status == "ok"
            assert res.has_backup is True

    assert "Task Aligned" in sub_path.read_text(encoding="utf-8")
    backup_file = tmp_path / "Show.S01E01.zh-CN.orig.srt"
    assert backup_file.exists()


def test_api_align_and_restore_endpoints(tmp_path: Path):
    video_path = tmp_path / "Matrix.mp4"
    video_path.write_bytes(b"video")
    sub_path = tmp_path / "Matrix.zh-CN.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nMatrix Sub\n", encoding="utf-8")

    with Session(engine) as session:
        path_record = MediaPath(path=str(tmp_path), type="movie")
        session.add(path_record)
        session.commit()
        session.refresh(path_record)

        media = ScannedFile(
            path_id=path_record.id,
            type="movie",
            file_path=str(video_path),
            filename=video_path.name,
            has_subtitle=True,
        )
        session.add(media)
        session.commit()
        session.refresh(media)
        file_id = media.id

    # 1. GET /media/aligner/status
    with patch.object(
        SubtitleAligner,
        "get_status",
        return_value=AlignerStatus(
            available=True,
            engine="alass",
            ffmpeg_available=True,
            alass_path="/usr/bin/alass",
            ffsubsync_path=None,
            message="就绪",
        ),
    ):
        res = client.get("/media/aligner/status")
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is True
        assert data["engine"] == "alass"

    # 2. POST /media/files/{file_id}/align-subtitle
    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("Aligned via API\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        res = client.post(
            f"/media/files/{file_id}/align-subtitle",
            json={"filename": "Matrix.zh-CN.srt", "split_penalty": 5.0},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["has_backup"] is True

    # 3. POST /media/files/{file_id}/restore-subtitle
    res = client.post(
        f"/media/files/{file_id}/restore-subtitle",
        json={"filename": "Matrix.zh-CN.srt"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["has_backup"] is False
