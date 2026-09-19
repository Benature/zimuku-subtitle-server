import base64
import io
import shutil
import zipfile
from pathlib import Path

import py7zr
import pytest
from sqlmodel import Session, delete

from app.core.utils import check_has_subtitle
from app.db.models import MediaPath, ScannedFile
from app.db.session import create_db_and_tables, engine
from app.services.subtitle_upload_service import SubtitleUploadError, SubtitleUploadService


@pytest.fixture(autouse=True)
def clean_media_records():
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


def _create_scanned_file(video_path: Path) -> int:
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"video")
    with Session(engine) as session:
        media_path = MediaPath(path=str(video_path.parent), type="movie")
        session.add(media_path)
        session.commit()
        session.refresh(media_path)
        scanned_file = ScannedFile(
            path_id=media_path.id,
            type="movie",
            file_path=str(video_path),
            filename=video_path.name,
        )
        session.add(scanned_file)
        session.commit()
        session.refresh(scanned_file)
        assert scanned_file.id is not None
        return scanned_file.id


def _upload(file_id: int, filename: str, content: bytes, language: str | None = None):
    with Session(engine) as session:
        return SubtitleUploadService.upload(
            session,
            file_id=file_id,
            filename=filename,
            content_base64=base64.b64encode(content).decode("ascii"),
            language=language,
        )


def test_upload_direct_subtitle_uses_language_and_preserves_existing_file(tmp_path):
    video_path = tmp_path / "Movie.2026.mkv"
    file_id = _create_scanned_file(video_path)
    existing_path = tmp_path / "Movie.2026.zh-CN.srt"
    existing_path.write_text("existing", encoding="utf-8")

    result = _upload(file_id, "source.SRT", b"new subtitle", language="zh-CN")

    uploaded_path = tmp_path / "Movie.2026.zh-CN.2.srt"
    assert result.to_dict() == {
        "file_id": file_id,
        "language": "zh-CN",
        "saved_count": 1,
        "saved_paths": [str(uploaded_path)],
    }
    assert existing_path.read_text(encoding="utf-8") == "existing"
    assert uploaded_path.read_bytes() == b"new subtitle"
    with Session(engine) as session:
        assert session.get(ScannedFile, file_id).has_subtitle is True


def test_uploaded_sup_is_detected_by_media_scan(tmp_path):
    video_path = tmp_path / "Movie.mkv"
    file_id = _create_scanned_file(video_path)

    result = _upload(file_id, "source.sup", b"binary subtitle")

    assert result.saved_paths == [str(tmp_path / "Movie.sup")]
    assert check_has_subtitle(video_path) is True


def test_upload_archive_saves_all_supported_subtitles_in_stable_order(tmp_path, subtitle_zip_bytes):
    video_path = tmp_path / "Show.S01E01.mkv"
    file_id = _create_scanned_file(video_path)
    archive = subtitle_zip_bytes(
        {
            "nested/b.srt": "second",
            "a.srt": "first",
            "c.ass": "styled",
            "readme.txt": "ignored",
        }
    )

    result = _upload(file_id, "bundle.zip", archive)

    assert result.saved_paths == [
        str(tmp_path / "Show.S01E01.srt"),
        str(tmp_path / "Show.S01E01.ass"),
        str(tmp_path / "Show.S01E01.2.srt"),
    ]
    assert (tmp_path / "Show.S01E01.srt").read_text(encoding="utf-8") == "first"
    assert (tmp_path / "Show.S01E01.ass").read_text(encoding="utf-8") == "styled"
    assert (tmp_path / "Show.S01E01.2.srt").read_text(encoding="utf-8") == "second"


def test_upload_7z_archive(tmp_path):
    video_path = tmp_path / "Movie.mkv"
    file_id = _create_scanned_file(video_path)
    source_path = tmp_path / "source.ass"
    source_path.write_text("styled subtitle", encoding="utf-8")
    archive_path = tmp_path / "bundle.7z"
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        archive.write(source_path, "nested/source.ass")

    result = _upload(file_id, "bundle.7z", archive_path.read_bytes(), language="en")

    assert result.saved_paths == [str(tmp_path / "Movie.en.ass")]
    assert (tmp_path / "Movie.en.ass").read_text(encoding="utf-8") == "styled subtitle"


@pytest.mark.parametrize(
    ("filename", "content_base64", "language", "expected"),
    [
        ("../subtitle.srt", "YQ==", None, "filename"),
        ("subtitle.txt", "YQ==", None, "不支持"),
        ("subtitle.srt", "not-base64", None, "Base64"),
        ("subtitle.srt", "YQ==", "custom", "语言代码"),
    ],
)
def test_upload_rejects_invalid_inputs(tmp_path, filename, content_base64, language, expected):
    file_id = _create_scanned_file(tmp_path / "Movie.mkv")

    with Session(engine) as session, pytest.raises(SubtitleUploadError, match=expected):
        SubtitleUploadService.upload(
            session,
            file_id=file_id,
            filename=filename,
            content_base64=content_base64,
            language=language,
        )


def test_upload_rejects_oversized_content_without_large_fixture(tmp_path, monkeypatch):
    file_id = _create_scanned_file(tmp_path / "Movie.mkv")
    monkeypatch.setattr("app.services.subtitle_upload_service.MAX_UPLOAD_SIZE", 3)

    with Session(engine) as session, pytest.raises(SubtitleUploadError, match="10 MiB"):
        SubtitleUploadService.upload(
            session,
            file_id=file_id,
            filename="subtitle.srt",
            content_base64=base64.b64encode(b"four").decode("ascii"),
        )


def test_upload_rejects_archive_without_subtitles(tmp_path):
    file_id = _create_scanned_file(tmp_path / "Movie.mkv")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "nothing here")

    with pytest.raises(SubtitleUploadError, match="未找到"):
        _upload(file_id, "empty.zip", buffer.getvalue())


def test_upload_rejects_archive_path_traversal(tmp_path):
    file_id = _create_scanned_file(tmp_path / "Movie.mkv")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.srt", "unsafe")

    with pytest.raises(SubtitleUploadError, match="未找到"):
        _upload(file_id, "unsafe.zip", buffer.getvalue())

    assert not (tmp_path.parent / "escape.srt").exists()


def test_upload_rejects_missing_media_and_stale_video(tmp_path):
    with Session(engine) as session, pytest.raises(SubtitleUploadError, match="未找到"):
        SubtitleUploadService.upload(
            session,
            file_id=999999,
            filename="subtitle.srt",
            content_base64="YQ==",
        )

    video_path = tmp_path / "gone.mkv"
    file_id = _create_scanned_file(video_path)
    video_path.unlink()
    with pytest.raises(SubtitleUploadError, match="不存在"):
        _upload(file_id, "subtitle.srt", b"subtitle")


def test_upload_rolls_back_created_files_when_copy_fails(tmp_path, subtitle_zip_bytes, monkeypatch):
    video_path = tmp_path / "Movie.mkv"
    file_id = _create_scanned_file(video_path)
    archive = subtitle_zip_bytes({"a.srt": "first", "b.srt": "second"})
    original_copy = shutil.copyfileobj
    call_count = 0

    def fail_second_copy(source, destination):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("disk full")
        return original_copy(source, destination)

    monkeypatch.setattr("app.services.subtitle_upload_service.shutil.copyfileobj", fail_second_copy)

    with pytest.raises(SubtitleUploadError, match="disk full"):
        _upload(file_id, "bundle.zip", archive)

    assert list(tmp_path.glob("Movie*.srt")) == []
    with Session(engine) as session:
        assert session.get(ScannedFile, file_id).has_subtitle is False
