from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.subtitle_detector import SubtitleDetector
from app.db.models import MediaPath, ScannedFile
from app.db.session import create_db_and_tables, engine
from app.main import app
from app.mcp.server import handle_call_tool, handle_list_tools
from app.services.subtitle_inspection_service import (
    SubtitleInspectionService,
    SubtitleInvalidRequestError,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_records():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()
    yield
    with Session(engine) as session:
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.commit()


def test_subtitle_detector_decoding_and_extraction(tmp_path: Path):
    # 测试 ASS 格式与编码解码
    ass_content = (
        "[Script Info]\n"
        "Title: Common Side Effects S01E01\n"
        "ScriptType: v4.00+\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour\n"
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,{\\pos(100,200)}这是第一句对白。\\NFirst line.\n"
        "Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,第二句对白开始测试。\\NSecond line of dialogue.\n"
        "Dialogue: 0,0:00:09.00,0:00:12.00,Default,,0,0,0,,请注意观察患者症状。\\NObserve symptoms carefully.\n"
    )
    dialogues = SubtitleDetector.extract_dialogues(ass_content, ".ass")
    assert len(dialogues) == 3
    assert "{\\pos(100,200)}" not in dialogues[0]
    assert "这是第一句对白" in dialogues[0]
    assert "First line" in dialogues[0]

    # 分析 ASS 对白语言（双语）
    analysis = SubtitleDetector.analyze_dialogues(dialogues)
    assert analysis.is_bilingual is True
    assert analysis.detected_language == "zh-CN-en"
    assert analysis.detected_language_name == "简英双语"
    assert len(analysis.sample_dialogues) > 0


def test_subtitle_detector_pure_chinese_and_english():
    chinese_srt = """1
00:00:01,000 --> 00:00:03,000
你好，今天天气不错。

2
00:00:04,000 --> 00:00:06,000
是的，我们一起去散步吧。
"""
    dialogues_cn = SubtitleDetector.extract_dialogues(chinese_srt, ".srt")
    analysis_cn = SubtitleDetector.analyze_dialogues(dialogues_cn)
    assert analysis_cn.is_bilingual is False
    assert analysis_cn.detected_language == "zh-CN"

    english_srt = """1
00:00:01,000 --> 00:00:03,000
Hello everyone, welcome to the show.

2
00:00:04,000 --> 00:00:06,000
Today we are discussing common side effects of medicine.
"""
    dialogues_en = SubtitleDetector.extract_dialogues(english_srt, ".srt")
    analysis_en = SubtitleDetector.analyze_dialogues(dialogues_en)
    assert analysis_en.is_bilingual is False
    assert analysis_en.detected_language == "en"


def _setup_media_and_subtitles(tmp_path: Path) -> tuple[int, Path]:
    media_dir = tmp_path / "TV" / "Common Side Effects" / "Season 1"
    media_dir.mkdir(parents=True, exist_ok=True)
    video_file = media_dir / "Common.Side.Effects.S01E01.mkv"
    video_file.write_bytes(b"dummy video data")

    # 创建双语字幕
    sub1 = media_dir / "Common.Side.Effects.S01E01.zh-CN-en.ass"
    sub1.write_text(
        """[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,你发现了治愈癌症的方法？\\NYou found a cure for cancer?
Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,但是它有严重的副作用。\\nHowever, it has severe side effects.
Dialogue: 0,0:00:09.00,0:00:12.00,Default,,0,0,0,,我们要保守这个秘密。\\NWe must keep this secret safe.
""",
        encoding="utf-8",
    )

    # 创建纯英文字幕
    sub2 = media_dir / "Common.Side.Effects.S01E01.en.srt"
    sub2.write_text(
        """1
00:00:01,000 --> 00:00:04,000
You found a cure for cancer?

2
00:00:05,000 --> 00:00:08,000
However, it has severe side effects.
""",
        encoding="utf-8",
    )

    with Session(engine) as session:
        mp = MediaPath(path=str(media_dir.parent.parent), type="tv")
        session.add(mp)
        session.commit()
        session.refresh(mp)

        sf = ScannedFile(
            path_id=mp.id,
            type="tv",
            file_path=str(video_file),
            filename=video_file.name,
            extracted_title="Common Side Effects",
            season=1,
            episode=1,
            has_subtitle=True,
        )
        session.add(sf)
        session.commit()
        session.refresh(sf)
        assert sf.id is not None
        return sf.id, video_file


def test_subtitle_inspection_service(tmp_path: Path):
    file_id, _ = _setup_media_and_subtitles(tmp_path)

    with Session(engine) as session:
        subtitles = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        assert len(subtitles) == 2

        # 检验双语字幕
        bilingual_sub = next(s for s in subtitles if s.format == ".ass")
        assert bilingual_sub.is_bilingual is True
        assert bilingual_sub.detected_language == "zh-CN-en"
        assert bilingual_sub.detected_language_name == "简英双语"
        assert len(bilingual_sub.sample_dialogues) > 0
        assert "治愈癌症" in bilingual_sub.sample_dialogues[0]
        assert "cure for cancer" in bilingual_sub.sample_dialogues[0]

        # 检验英文字幕
        en_sub = next(s for s in subtitles if s.format == ".srt")
        assert en_sub.is_bilingual is False
        assert en_sub.detected_language == "en"

        # 存在多个字幕未指定 filename 抛出 SubtitleInvalidRequestError
        with pytest.raises(SubtitleInvalidRequestError) as exc_info:
            SubtitleInspectionService.read_subtitle_content(session, file_id)
        assert "存在多个关联字幕" in str(exc_info.value)

        # 指定 filename 读取双语字幕内容
        content_res = SubtitleInspectionService.read_subtitle_content(
            session,
            file_id=file_id,
            filename=bilingual_sub.filename,
            clean_text=True,
        )
        assert content_res.is_binary is False
        assert content_res.clean_text is True
        assert content_res.total_lines == 3
        assert any("治愈癌症" in line for line in content_res.lines)
        assert content_res.analysis["is_bilingual"] is True
        assert content_res.analysis["detected_language"] == "zh-CN-en"


def test_subtitle_inspection_api(tmp_path: Path):
    file_id, _ = _setup_media_and_subtitles(tmp_path)

    # 1. GET /media/files/{file_id}/subtitles
    resp = client.get(f"/media/files/{file_id}/subtitles")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    ass_item = next(item for item in data if item["format"] == ".ass")
    assert ass_item["is_bilingual"] is True
    assert ass_item["detected_language"] == "zh-CN-en"
    assert ass_item["detected_language_name"] == "简英双语"
    assert len(ass_item["sample_dialogues"]) > 0

    # 2. GET /media/files/{file_id}/subtitles/content
    resp_content = client.get(
        f"/media/files/{file_id}/subtitles/content",
        params={"filename": ass_item["filename"], "clean_text": True},
    )
    assert resp_content.status_code == 200
    content_data = resp_content.json()
    assert content_data["subtitle_filename"] == ass_item["filename"]
    assert content_data["analysis"]["is_bilingual"] is True
    assert len(content_data["lines"]) == 3

    # 3. 错误情况：文件不存在
    resp_404 = client.get("/media/files/999999/subtitles")
    assert resp_404.status_code == 404


@pytest.mark.anyio
async def test_subtitle_inspection_mcp_tools(tmp_path: Path):
    file_id, _ = _setup_media_and_subtitles(tmp_path)

    # 1. 测试 list_media_subtitles 工具
    tools = await handle_list_tools()
    tool_names = [t.name for t in tools]
    assert "list_media_subtitles" in tool_names
    assert "read_subtitle_content" in tool_names

    list_res = await handle_call_tool("list_media_subtitles", {"file_id": file_id})
    assert len(list_res) > 0
    text_out = list_res[0].text
    assert "已有字幕列表及语言检测" in text_out
    assert "zh-CN-en" in text_out
    assert "简英双语" in text_out

    # 2. 测试 read_subtitle_content 工具
    read_res = await handle_call_tool(
        "read_subtitle_content",
        {
            "file_id": file_id,
            "filename": "Common.Side.Effects.S01E01.zh-CN-en.ass",
            "clean_text": True,
        },
    )
    assert len(read_res) > 0
    read_text = read_res[0].text
    assert "字幕内容与语言分析" in read_text
    assert "治愈癌症" in read_text
    assert "cure for cancer" in read_text
    assert "zh-CN-en" in read_text
