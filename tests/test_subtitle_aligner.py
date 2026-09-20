from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete, select

from app.core.aligner import AlignerStatus, SubtitleAligner, SubtitleAlignError
from app.core.config import ConfigManager, SettingKey
from app.db.models import MediaPath, ScannedFile, Setting, SubtitleAlignmentState, SubtitleTask
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.services.media_service import MediaService, global_task_status
from app.services.subtitle_align_service import SubtitleAlignService
from app.services.subtitle_inspection_service import (
    SubtitleInspectionService,
    record_alignment_result,
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
        session.exec(delete(SubtitleAlignmentState))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(SubtitleTask))
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.exec(delete(SubtitleAlignmentState))
        auto_align_setting = session.exec(
            select(Setting).where(Setting.key == SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD)
        ).first()
        if auto_align_setting:
            auto_align_setting.value = "true"
            session.add(auto_align_setting)
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


def test_extract_start_times(tmp_path: Path):
    srt = tmp_path / "a.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\nHello\n\n2\n00:01:05,250 --> 00:01:07,000\nWorld\n",
        encoding="utf-8",
    )
    starts = SubtitleAligner.extract_start_times(srt)
    assert starts == [1000, 65250]

    ass = tmp_path / "a.ass"
    ass.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hello\n"
        "Dialogue: 0,0:01:05.25,0:01:07.00,Default,,0,0,0,,World\n",
        encoding="utf-8",
    )
    starts = SubtitleAligner.extract_start_times(ass)
    assert starts == [1000, 65250]


@pytest.mark.anyio
async def test_check_alignment_judgement(tmp_path: Path):
    video_path = tmp_path / "movie.mp4"
    video_path.write_bytes(b"video")
    sub_path = tmp_path / "movie.srt"
    sub_path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nA\n\n2\n00:00:05,000 --> 00:00:06,000\nB\n",
        encoding="utf-8",
    )

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

    # 场景 1：对齐后偏移极小 -> 判定已对齐
    async def fake_align_small_shift(reference_path, subtitle_path, output_path, split_penalty=7.0, **kwargs):
        output_path.write_text(
            "1\n00:00:01,050 --> 00:00:02,050\nA\n\n2\n00:00:05,080 --> 00:00:06,080\nB\n",
            encoding="utf-8",
        )

    with patch.object(SubtitleAligner, "align", side_effect=fake_align_small_shift):
        with Session(engine) as session:
            res = await SubtitleAlignService.check_media_subtitle_alignment(session, file_id)
            assert res.aligned is True
            assert res.checked_cues == 2
            assert res.max_shift_ms == 80
            assert res.mean_shift_ms == 65

    # 场景 2：对齐后偏移较大 -> 判定未对齐，且原字幕未被修改
    async def fake_align_big_shift(reference_path, subtitle_path, output_path, split_penalty=7.0, **kwargs):
        output_path.write_text(
            "1\n00:00:03,500 --> 00:00:04,500\nA\n\n2\n00:00:07,500 --> 00:00:08,500\nB\n",
            encoding="utf-8",
        )

    original_content = sub_path.read_text(encoding="utf-8")
    with patch.object(SubtitleAligner, "align", side_effect=fake_align_big_shift):
        with Session(engine) as session:
            res = await SubtitleAlignService.check_media_subtitle_alignment(session, file_id)
            assert res.aligned is False
            assert res.max_shift_ms == 2500
    assert sub_path.read_text(encoding="utf-8") == original_content

    # 场景 3：检查 API 端点
    with patch.object(SubtitleAligner, "align", side_effect=fake_align_small_shift):
        res = client.post(f"/media/files/{file_id}/check-subtitle-alignment", json={"threshold_ms": 200})
        assert res.status_code == 200
        data = res.json()
        assert data["aligned"] is True
        assert data["subtitle_filename"] == "movie.srt"


@pytest.mark.anyio
async def test_auto_align_for_task_respects_format_and_failures(tmp_path: Path):
    video_path = tmp_path / "m.mp4"
    video_path.write_bytes(b"video")

    # .sup 图形字幕不支持，跳过且返回 False
    sup_path = tmp_path / "m.sup"
    sup_path.write_bytes(b"binary")
    task = SubtitleTask(
        title="m",
        source_url="http://x.test/1",
        status="completed",
        target_path=str(video_path),
        save_path=str(sup_path),
    )
    assert await SubtitleAlignService.auto_align_for_task(task, str(sup_path)) is False

    # 对齐引擎抛异常时不影响任务（返回 False）
    srt_path = tmp_path / "m.zh-CN.srt"
    srt_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nX\n", encoding="utf-8")
    task.save_path = str(srt_path)
    with patch.object(SubtitleAligner, "align", side_effect=SubtitleAlignError("engine down")):
        assert await SubtitleAlignService.auto_align_for_task(task, str(srt_path)) is False
    # 原字幕未被破坏，但备份已建立
    assert "X" in srt_path.read_text(encoding="utf-8")
    assert (tmp_path / "m.zh-CN.orig.srt").exists()

    # 正常路径：成功对齐返回 True
    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:02,000 --> 00:00:03,000\nX\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        assert await SubtitleAlignService.auto_align_for_task(task, str(srt_path)) is True


@pytest.mark.anyio
async def test_run_download_task_auto_align_toggle(tmp_path: Path):
    video_path = tmp_path / "auto.mp4"
    video_path.write_bytes(b"video")

    async def fake_execute(self, task):
        from app.services.download_workflow import DownloadArtifact

        save_path = tmp_path / "auto.zh-CN.srt"
        save_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nAuto\n", encoding="utf-8")
        return DownloadArtifact(
            filename="auto.zip",
            file_path=str(save_path),
            save_path=str(save_path),
            extracted_files=[str(save_path)],
        )

    # 开关开启时：下载成功后触发自动对齐
    with Session(engine) as session:
        task = SubtitleTask(
            title="auto",
            source_url="http://x.test/auto-on",
            status="pending",
            target_path=str(video_path),
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id

    with (
        patch("app.services.task_service.DownloadWorkflow.execute", new=fake_execute),
        patch("app.services.task_service.DownloadWorkflow.close", new=AsyncMock(return_value=None)),
        patch.object(SubtitleAlignService, "auto_align_for_task", new=AsyncMock(return_value=True)) as mock_auto_align,
    ):
        await TaskService.run_download_task(task_id)
        assert mock_auto_align.await_count == 1

    with Session(engine) as session:
        task = session.get(SubtitleTask, task_id)
        assert task.status == "completed"

    # 开关关闭时：不触发自动对齐
    ConfigManager.set(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, "false")
    with Session(engine) as session:
        task2 = SubtitleTask(
            title="auto2",
            source_url="http://x.test/auto-off",
            status="pending",
            target_path=str(video_path),
        )
        session.add(task2)
        session.commit()
        session.refresh(task2)
        task2_id = task2.id

    with (
        patch("app.services.task_service.DownloadWorkflow.execute", new=fake_execute),
        patch("app.services.task_service.DownloadWorkflow.close", new=AsyncMock(return_value=None)),
        patch.object(SubtitleAlignService, "auto_align_for_task", new=AsyncMock(return_value=True)) as mock_auto_align2,
    ):
        await TaskService.run_download_task(task2_id)
        assert mock_auto_align2.await_count == 0

    ConfigManager.set(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, "true")


def test_auto_align_setting_normalization():
    assert ConfigManager.normalize_value(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, "ON") == "true"
    assert ConfigManager.normalize_value(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, "0") == "false"
    with pytest.raises(ValueError):
        ConfigManager.normalize_value(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, "maybe")

    assert ConfigManager.get_bool(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, True) is True


@pytest.mark.anyio
async def test_mcp_align_and_check_tools(tmp_path: Path):
    from app.mcp.server import handle_call_tool, handle_list_tools

    video_path = tmp_path / "mcp.mp4"
    video_path.write_bytes(b"video")
    sub_path = tmp_path / "mcp.zh-CN.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nMCP\n", encoding="utf-8")

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

    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "align_subtitle" in tool_names
    assert "check_subtitle_alignment" in tool_names

    # 手动触发对齐
    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:02,000 --> 00:00:03,000\nMCP Aligned\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        res = await handle_call_tool("align_subtitle", {"file_id": file_id})
        assert "音轨对齐完成" in res[0].text
        assert (tmp_path / "mcp.zh-CN.orig.srt").exists()

    # 对齐检查（对齐后无偏移 -> aligned=True）
    async def fake_align_no_shift(reference_path, subtitle_path, output_path, split_penalty=7.0, **kwargs):
        output_path.write_text(subtitle_path.read_text(encoding="utf-8"), encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align_no_shift):
        res = await handle_call_tool("check_subtitle_alignment", {"file_id": file_id})
        assert "音轨对齐检查结果" in res[0].text
        assert '"aligned": true' in res[0].text


@pytest.mark.anyio
async def test_alignment_state_attribute_lifecycle(tmp_path: Path):
    """对齐状态作为字幕属性：记录 -> 查询 -> 文件修改后回落 unknown -> 还原后 unknown。"""
    video_path = tmp_path / "state.mp4"
    video_path.write_bytes(b"video")
    sub_path = tmp_path / "state.zh-CN.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nState\n", encoding="utf-8")

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

    # 1. 初始状态 unknown
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "unknown"
        assert subs[0].alignment_max_shift_ms is None

    # 2. 手动记录 misaligned 状态 -> 查询可见
    record_alignment_result(
        subtitle_path=sub_path,
        file_id=file_id,
        status="misaligned",
        max_shift_ms=2500.0,
        mean_shift_ms=1200.0,
    )
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "misaligned"
        assert subs[0].alignment_max_shift_ms == 2500.0
        assert subs[0].alignment_mean_shift_ms == 1200.0
        assert subs[0].alignment_checked_at is not None

    # 3. 执行对齐后状态变为 aligned
    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:03,500 --> 00:00:04,500\nState\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        with Session(engine) as session:
            await SubtitleAlignService.align_media_subtitle(session, file_id)

    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "aligned"
        assert subs[0].alignment_max_shift_ms is None

    # 4. 字幕文件被外部修改后 -> 状态回落 unknown
    sub_path.write_text("1\n00:00:09,000 --> 00:00:10,000\nExternally Modified\n", encoding="utf-8")
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "unknown"
        assert subs[0].alignment_max_shift_ms is None

    # 5. 还原原字幕后 -> 状态重置 unknown（即使此前记录过 aligned）
    record_alignment_result(subtitle_path=sub_path, file_id=file_id, status="aligned")
    with Session(engine) as session:
        SubtitleAlignService.restore_media_subtitle(session, file_id, filename="state.zh-CN.srt")
    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "unknown"
        record = session.exec(
            select(SubtitleAlignmentState).where(SubtitleAlignmentState.subtitle_path == str(sub_path))
        ).first()
        assert record is None


def test_alignment_state_in_api_response(tmp_path: Path):
    video_path = tmp_path / "api_state.mp4"
    video_path.write_bytes(b"video")
    sub_path = tmp_path / "api_state.srt"
    sub_path.write_text("1\n00:00:01,000 --> 00:00:02,000\nApi\n", encoding="utf-8")

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

    record_alignment_result(
        subtitle_path=sub_path,
        file_id=file_id,
        status="misaligned",
        max_shift_ms=800.0,
    )

    res = client.get(f"/media/files/{file_id}/subtitles")
    assert res.status_code == 200
    data = res.json()
    assert data[0]["alignment_status"] == "misaligned"
    assert data[0]["alignment_max_shift_ms"] == 800.0


def _create_series_file(tmp_path: Path, title: str, season: int, episode: int, subtitle_names: list[str]) -> int:
    """创建剧集视频文件 + 关联字幕，并登记 ScannedFile，返回 file_id。"""
    video_path = tmp_path / f"{title}.S{season:02d}E{episode:02d}.mkv"
    video_path.write_bytes(b"fake video")
    for sub_name in subtitle_names:
        (tmp_path / sub_name).write_text("1\n00:00:01,000 --> 00:00:02,000\nLine\n", encoding="utf-8")

    with Session(engine) as session:
        path_record = session.exec(select(MediaPath).where(MediaPath.path == str(tmp_path))).first()
        if path_record is None:
            path_record = MediaPath(path=str(tmp_path), type="tv")
            session.add(path_record)
            session.commit()
            session.refresh(path_record)
        media = ScannedFile(
            path_id=path_record.id,
            type="tv",
            file_path=str(video_path),
            filename=video_path.name,
            has_subtitle=bool(subtitle_names),
            extracted_title=title,
            season=season,
            episode=episode,
        )
        session.add(media)
        session.commit()
        session.refresh(media)
        return media.id


@pytest.mark.anyio
async def test_run_series_align_process_aligns_all_subtitles(tmp_path: Path):
    series_dir = tmp_path / "series"
    series_dir.mkdir()
    first_id = _create_series_file(series_dir, "Show A", 1, 1, ["Show A.S01E01.zh.srt", "Show A.S01E01.zh.ass"])
    second_id = _create_series_file(series_dir, "Show A", 1, 2, ["Show A.S01E02.zh.srt"])
    no_sub_id = _create_series_file(series_dir, "Show A", 1, 3, [])

    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:02,000 --> 00:00:03,000\nAligned\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        await MediaService.run_series_align_process("Show A")

    # 任务状态已清理
    assert "Show A" not in global_task_status.aligning_series
    assert first_id not in global_task_status.aligning_files
    assert second_id not in global_task_status.aligning_files

    # 每集字幕均已对齐：内容被改写、.orig 备份生成、状态记录为 aligned
    with Session(engine) as session:
        for file_id, sub_names in (
            (first_id, ["Show A.S01E01.zh.srt", "Show A.S01E01.zh.ass"]),
            (second_id, ["Show A.S01E02.zh.srt"]),
        ):
            subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
            assert sorted(sub.filename for sub in subs) == sorted(sub_names)
            for sub in subs:
                assert sub.alignment_status == "aligned"
                sub_path = series_dir / sub.filename
                assert "Aligned" in sub_path.read_text(encoding="utf-8")
                orig_backup = sub_path.with_name(f"{sub_path.stem}.orig{sub_path.suffix}")
                assert orig_backup.is_file()

    # 无字幕文件被跳过且不报错
    with Session(engine) as session:
        assert SubtitleInspectionService.get_existing_subtitles(session, no_sub_id) == []


@pytest.mark.anyio
async def test_run_series_align_process_matches_normalized_title(tmp_path: Path):
    series_dir = tmp_path / "series_norm"
    series_dir.mkdir()
    file_id = _create_series_file(series_dir, "Show B", 1, 1, ["Show B.S01E01.zh.srt"])

    async def fake_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        output_path.write_text("1\n00:00:02,000 --> 00:00:03,000\nAligned\n", encoding="utf-8")

    # 带年份的标题应通过规范化匹配到同一剧集
    with patch.object(SubtitleAligner, "align", side_effect=fake_align):
        await MediaService.run_series_align_process("Show B (2021)")

    with Session(engine) as session:
        subs = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert subs[0].alignment_status == "aligned"


@pytest.mark.anyio
async def test_run_series_align_process_continues_after_failure(tmp_path: Path):
    series_dir = tmp_path / "series_fail"
    series_dir.mkdir()
    ok_id = _create_series_file(series_dir, "Show C", 1, 1, ["Show C.S01E01.zh.srt"])
    fail_id = _create_series_file(series_dir, "Show C", 1, 2, ["Show C.S01E02.zh.srt"])

    real_call_count = {"n": 0}

    async def flaky_align(reference_path, subtitle_path, output_path, split_penalty=7.0):
        real_call_count["n"] += 1
        if subtitle_path.name == "Show C.S01E02.zh.srt":
            raise SubtitleAlignError("boom")
        output_path.write_text("1\n00:00:02,000 --> 00:00:03,000\nAligned\n", encoding="utf-8")

    with patch.object(SubtitleAligner, "align", side_effect=flaky_align):
        await MediaService.run_series_align_process("Show C")

    # 两条字幕都被尝试过，失败不中断
    assert real_call_count["n"] == 2
    assert "Show C" not in global_task_status.aligning_series
    assert fail_id not in global_task_status.aligning_files

    with Session(engine) as session:
        ok_subs = SubtitleInspectionService.get_existing_subtitles(session, ok_id)
        fail_subs = SubtitleInspectionService.get_existing_subtitles(session, fail_id)
        assert ok_subs[0].alignment_status == "aligned"
        assert fail_subs[0].alignment_status == "unknown"


def test_series_align_api_trigger():
    with patch("app.api.media.MediaService.run_series_align_process", new=AsyncMock(return_value=None)) as mock_run:
        res = client.post("/media/series/align-subtitles", json={"title": "Show D"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["task_kind"] == "series_align"
        assert data["target"] == "Show D"
        mock_run.assert_called_once_with("Show D")

        # 兼容 query 参数形式
        res = client.post("/media/series/align-subtitles?title=Show%20E")
        assert res.status_code == 200
        assert res.json()["target"] == "Show E"


def test_series_align_api_requires_title():
    res = client.post("/media/series/align-subtitles", json={})
    assert res.status_code == 422
