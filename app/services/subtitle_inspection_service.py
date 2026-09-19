from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session

from ..core.subtitle_detector import LanguageAnalysisResult, SubtitleDetector
from ..core.utils import SUBTITLE_EXTENSIONS
from ..db.models import ScannedFile


class SubtitleInspectionError(Exception):
    """字幕查询或内容读取异常基类。"""


class SubtitleNotFoundError(SubtitleInspectionError, LookupError):
    """字幕或媒体文件未找到。"""


class SubtitleInvalidRequestError(SubtitleInspectionError, ValueError):
    """请求参数无效或不支持的操作。"""


@dataclass(frozen=True)
class ExistingSubtitleInfo:
    filename: str
    file_path: str
    format: str
    size_bytes: int
    modified_at: str
    filename_language: str | None
    is_binary: bool
    detected_language: str
    detected_language_name: str
    is_bilingual: bool
    encoding: str
    chinese_char_count: int
    english_word_count: int
    bilingual_dialogue_count: int
    sample_dialogues: list[str]
    confidence: float
    details: dict[str, Any]
    has_backup: bool = False
    backup_filename: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubtitleContentResult:
    file_id: int
    media_filename: str
    subtitle_filename: str
    subtitle_path: str
    format: str
    encoding: str
    is_binary: bool
    clean_text: bool
    total_lines: int
    returned_lines: int
    lines: list[str]
    analysis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubtitleInspectionService:
    """查询媒体文件已有字幕并读取/分析实际内容的业务服务。"""

    @classmethod
    def get_existing_subtitles(cls, session: Session, file_id: int) -> list[ExistingSubtitleInfo]:
        """获取指定媒体文件关联的所有已有字幕及其实际语言分析。"""
        media = session.get(ScannedFile, file_id)
        if media is None:
            raise SubtitleNotFoundError(f"未找到媒体文件 ID: {file_id}")

        video_path = Path(media.file_path)
        subtitle_paths = cls._find_related_subtitle_files(video_path)

        results: list[ExistingSubtitleInfo] = []
        for sub_path in subtitle_paths:
            info = cls._inspect_single_subtitle(sub_path)
            results.append(info)

        return results

    @classmethod
    def read_subtitle_content(
        cls,
        session: Session,
        file_id: int,
        filename: str | None = None,
        max_lines: int = 100,
        clean_text: bool = True,
    ) -> SubtitleContentResult:
        """读取指定字幕的内容并提供纯文本对白与语言分析。"""
        media = session.get(ScannedFile, file_id)
        if media is None:
            raise SubtitleNotFoundError(f"未找到媒体文件 ID: {file_id}")

        video_path = Path(media.file_path)
        subtitle_paths = cls._find_related_subtitle_files(video_path)
        if not subtitle_paths:
            raise SubtitleNotFoundError(f"媒体文件 '{media.filename}' 暂无任何关联字幕")

        target_file: Path | None = None
        if filename:
            # 安全校验 filename
            safe_name = Path(filename).name
            if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
                raise SubtitleInvalidRequestError("filename 格式无效")

            for sub_path in subtitle_paths:
                if sub_path.name == safe_name:
                    target_file = sub_path
                    break

            if target_file is None:
                available = [p.name for p in subtitle_paths]
                raise SubtitleNotFoundError(f"未找到指定字幕文件 '{filename}'。可用字幕: {', '.join(available)}")
        else:
            if len(subtitle_paths) == 1:
                target_file = subtitle_paths[0]
            else:
                available = [p.name for p in subtitle_paths]
                raise SubtitleInvalidRequestError(
                    f"存在多个关联字幕，请通过 filename 参数指定其中一个。可用字幕: {', '.join(available)}"
                )

        suffix = target_file.suffix.lower()
        if suffix == ".sup":
            raise SubtitleInvalidRequestError("该字幕为 .sup 二进制图形格式，不支持直接读取纯文本内容")

        raw_bytes = target_file.read_bytes()
        text, encoding = SubtitleDetector.decode_subtitle_bytes(raw_bytes)

        if clean_text:
            all_lines = SubtitleDetector.extract_dialogues(text, suffix)
        else:
            all_lines = text.splitlines()

        total_lines = len(all_lines)
        if max_lines and max_lines > 0:
            effective_limit = min(max_lines, 2000)
            returned = all_lines[:effective_limit]
        else:
            returned = all_lines[:2000]  # 安全上限 2000 行

        # 对提取出的对白进行语言分析
        dialogues_for_analysis = all_lines if clean_text else SubtitleDetector.extract_dialogues(text, suffix)
        analysis = SubtitleDetector.analyze_dialogues(
            dialogues_for_analysis,
            encoding=encoding,
            filename_hint=target_file.name,
        )

        return SubtitleContentResult(
            file_id=file_id,
            media_filename=media.filename,
            subtitle_filename=target_file.name,
            subtitle_path=str(target_file),
            format=suffix,
            encoding=encoding,
            is_binary=False,
            clean_text=clean_text,
            total_lines=total_lines,
            returned_lines=len(returned),
            lines=returned,
            analysis=analysis.to_dict(),
        )

    @classmethod
    def _find_related_subtitle_files(cls, video_path: Path) -> list[Path]:
        """查找与视频同名的所有已有字幕文件。"""
        video_stem = video_path.stem.lower()
        dir_path = video_path.parent
        if not dir_path.exists():
            return []

        search_dirs = [dir_path]
        subs_dir = dir_path / "Subs"
        if subs_dir.is_dir():
            search_dirs.append(subs_dir)

        subtitles: list[Path] = []
        for search_dir in search_dirs:
            try:
                for item in search_dir.iterdir():
                    if item.is_file() and item.suffix.lower() in SUBTITLE_EXTENSIONS:
                        if item.stem.lower().endswith(".orig"):
                            continue
                        if item.stem.lower().startswith(video_stem):
                            subtitles.append(item)
            except OSError:
                continue

        return sorted(subtitles, key=lambda p: p.name)

    @classmethod
    def _inspect_single_subtitle(cls, sub_path: Path) -> ExistingSubtitleInfo:
        """检查单个字幕文件的元数据和语言。"""
        stat = sub_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        filename_lang = SubtitleDetector.infer_language_from_filename(sub_path.name)
        suffix = sub_path.suffix.lower()
        is_binary = suffix == ".sup"

        analysis: LanguageAnalysisResult = SubtitleDetector.analyze_file(sub_path)
        backup_path = sub_path.with_name(f"{sub_path.stem}.orig{sub_path.suffix}")
        has_backup = backup_path.is_file()
        backup_filename = backup_path.name if has_backup else None

        return ExistingSubtitleInfo(
            filename=sub_path.name,
            file_path=str(sub_path),
            format=suffix,
            size_bytes=stat.st_size,
            modified_at=modified_at,
            filename_language=filename_lang,
            is_binary=is_binary,
            detected_language=analysis.detected_language,
            detected_language_name=analysis.detected_language_name,
            is_bilingual=analysis.is_bilingual,
            encoding=analysis.encoding,
            chinese_char_count=analysis.chinese_char_count,
            english_word_count=analysis.english_word_count,
            bilingual_dialogue_count=analysis.bilingual_dialogue_count,
            sample_dialogues=analysis.sample_dialogues,
            confidence=analysis.confidence,
            details=analysis.details,
            has_backup=has_backup,
            backup_filename=backup_filename,
        )
