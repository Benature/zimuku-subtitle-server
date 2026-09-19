import base64
import binascii
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlmodel import Session

from ..core.archive import ArchiveManager
from ..core.config import get_temp_path
from ..core.subtitle_languages import SUBTITLE_LANGUAGE_BY_CODE
from ..core.utils import SUBTITLE_EXTENSIONS
from ..db.models import ScannedFile

MAX_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_ARCHIVE_FILES = 100
MAX_ARCHIVE_EXTRACTED_SIZE = 50 * 1024 * 1024
ARCHIVE_EXTENSIONS = set(ArchiveManager.SUPPORTED_ARCHIVE_EXTENSIONS)


class SubtitleUploadError(Exception):
    """字幕上传参数或文件内容无效。"""


@dataclass(frozen=True)
class SubtitleUploadResult:
    file_id: int
    language: str | None
    saved_count: int
    saved_paths: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SubtitleUploadService:
    @classmethod
    def upload(
        cls,
        session: Session,
        *,
        file_id: int,
        filename: str,
        content_base64: str,
        language: str | None = None,
    ) -> SubtitleUploadResult:
        safe_filename = cls._validate_filename(filename)
        language_tag = cls._resolve_language_tag(language)
        content = cls._decode_content(content_base64)
        media = session.get(ScannedFile, file_id)
        if media is None:
            raise SubtitleUploadError(f"未找到已扫描媒体文件: {file_id}")

        video_path = Path(media.file_path)
        if not video_path.is_file():
            raise SubtitleUploadError(f"目标视频文件不存在: {video_path}")

        temp_root = Path(get_temp_path())
        temp_root.mkdir(parents=True, exist_ok=True)
        created_paths: list[Path] = []
        try:
            with tempfile.TemporaryDirectory(prefix=f"upload_{file_id}_", dir=temp_root) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                uploaded_path = temp_dir / safe_filename
                uploaded_path.write_bytes(content)
                candidates = cls._collect_candidates(uploaded_path, temp_dir)
                destinations = cls._plan_destinations(video_path, candidates, language_tag)
                for source, destination in zip(candidates, destinations, strict=True):
                    with source.open("rb") as source_file:
                        with destination.open("xb") as destination_file:
                            created_paths.append(destination)
                            shutil.copyfileobj(source_file, destination_file)

                media.has_subtitle = True
                session.add(media)
                session.commit()
        except SubtitleUploadError:
            cls._remove_created_files(created_paths)
            raise
        except (OSError, ValueError, binascii.Error) as exc:
            cls._remove_created_files(created_paths)
            session.rollback()
            raise SubtitleUploadError(f"字幕文件处理失败: {exc}") from exc
        except Exception:
            cls._remove_created_files(created_paths)
            session.rollback()
            raise

        return SubtitleUploadResult(
            file_id=file_id,
            language=language,
            saved_count=len(created_paths),
            saved_paths=[str(path) for path in created_paths],
        )

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
            raise SubtitleUploadError("filename 必须是不包含路径的文件名")
        if any(ord(char) < 32 for char in filename):
            raise SubtitleUploadError("filename 包含非法控制字符")
        extension = Path(filename).suffix.lower()
        if extension not in SUBTITLE_EXTENSIONS | ARCHIVE_EXTENSIONS:
            raise SubtitleUploadError(f"不支持的字幕文件格式: {extension or '无扩展名'}")
        return filename

    @staticmethod
    def _resolve_language_tag(language: str | None) -> str | None:
        if language is None:
            return None
        definition = SUBTITLE_LANGUAGE_BY_CODE.get(language)
        if definition is None:
            raise SubtitleUploadError(f"不支持的字幕语言代码: {language}")
        return definition.filename_tag

    @staticmethod
    def _decode_content(content_base64: str) -> bytes:
        if not content_base64:
            raise SubtitleUploadError("content_base64 不能为空")
        max_encoded_size = ((MAX_UPLOAD_SIZE + 2) // 3) * 4
        if len(content_base64) > max_encoded_size:
            raise SubtitleUploadError("字幕文件超过 10 MiB 限制")
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SubtitleUploadError("content_base64 不是有效的 Base64") from exc
        if not content:
            raise SubtitleUploadError("上传内容不能为空")
        if len(content) > MAX_UPLOAD_SIZE:
            raise SubtitleUploadError("字幕文件超过 10 MiB 限制")
        return content

    @classmethod
    def _collect_candidates(cls, uploaded_path: Path, temp_dir: Path) -> list[Path]:
        if uploaded_path.suffix.lower() in ARCHIVE_EXTENSIONS:
            extract_dir = temp_dir / "extracted"
            try:
                extracted = ArchiveManager.extract(
                    str(uploaded_path),
                    str(extract_dir),
                    max_files=MAX_ARCHIVE_FILES,
                    max_total_size=MAX_ARCHIVE_EXTRACTED_SIZE,
                )
            except Exception as exc:
                raise SubtitleUploadError(f"压缩包处理失败: {exc}") from exc
            candidates = sorted(
                (Path(path) for path in extracted if Path(path).suffix.lower() in SUBTITLE_EXTENSIONS),
                key=lambda path: path.relative_to(extract_dir).as_posix().casefold(),
            )
        else:
            candidates = [uploaded_path]

        if not candidates:
            raise SubtitleUploadError("上传内容中未找到支持的字幕文件")
        return candidates

    @staticmethod
    def _plan_destinations(video_path: Path, candidates: list[Path], language_tag: str | None) -> list[Path]:
        base_name = video_path.stem
        if language_tag:
            base_name = f"{base_name}.{language_tag}"

        reserved: set[Path] = set()
        destinations: list[Path] = []
        for candidate in candidates:
            extension = candidate.suffix.lower()
            destination = video_path.parent / f"{base_name}{extension}"
            index = 2
            while destination.exists() or destination in reserved:
                destination = video_path.parent / f"{base_name}.{index}{extension}"
                index += 1
            reserved.add(destination)
            destinations.append(destination)
        return destinations

    @staticmethod
    def _remove_created_files(paths: list[Path]) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
