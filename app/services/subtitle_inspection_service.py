from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, select

from ..core.subtitle_detector import LanguageAnalysisResult, SubtitleDetector
from ..core.subtitle_languages import SUBTITLE_LANGUAGE_BY_CODE
from ..core.utils import SUBTITLE_EXTENSIONS
from ..db.models import ScannedFile, SubtitleAlignmentState
from ..db.session import session_scope

ALIGNMENT_STATUS_UNKNOWN = "unknown"
ALIGNMENT_STATUS_ALIGNED = "aligned"
ALIGNMENT_STATUS_MISALIGNED = "misaligned"


class SubtitleInspectionError(Exception):
    """字幕查询或内容读取异常基类。"""


class SubtitleNotFoundError(SubtitleInspectionError, LookupError):
    """字幕或媒体文件未找到。"""


class SubtitleInvalidRequestError(SubtitleInspectionError, ValueError):
    """请求参数无效或不支持的操作。"""


@dataclass(frozen=True)
class AlignmentStateInfo:
    """单个字幕文件的对齐状态视图。"""

    status: str = ALIGNMENT_STATUS_UNKNOWN
    max_shift_ms: Optional[float] = None
    mean_shift_ms: Optional[float] = None
    checked_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_file_signature(sub_path: Path) -> tuple[int, int]:
    """计算字幕文件签名（大小 + 修改时间），用于检测文件是否被修改。"""
    stat = sub_path.stat()
    return stat.st_size, stat.st_mtime_ns


def _resolve_alignment_from_record(record: SubtitleAlignmentState, sub_path: Path) -> AlignmentStateInfo:
    """基于已有记录解析对齐状态；文件签名与记录不匹配时回落为 unknown。"""
    try:
        size_bytes, mtime_ns = compute_file_signature(sub_path)
    except OSError:
        return AlignmentStateInfo()

    if record.size_bytes != size_bytes or record.mtime_ns != mtime_ns:
        return AlignmentStateInfo()

    return AlignmentStateInfo(
        status=record.status,
        max_shift_ms=record.max_shift_ms,
        mean_shift_ms=record.mean_shift_ms,
        checked_at=record.checked_at.isoformat(),
    )


def resolve_alignment_state(session: Session, sub_path: Path) -> AlignmentStateInfo:
    """读取字幕的对齐状态；文件签名与记录不匹配时回落为 unknown。"""
    record = session.exec(
        select(SubtitleAlignmentState).where(SubtitleAlignmentState.subtitle_path == str(sub_path))
    ).first()
    if record is None:
        return AlignmentStateInfo()

    return _resolve_alignment_from_record(record, sub_path)


# 单文件多字幕、单作品多文件聚合时的状态优先级（数值越大越差）
_ALIGNMENT_SEVERITY = {
    ALIGNMENT_STATUS_ALIGNED: 0,
    ALIGNMENT_STATUS_UNKNOWN: 1,
    ALIGNMENT_STATUS_MISALIGNED: 2,
}


@dataclass(frozen=True)
class SubtitleSummaryInfo:
    """单个媒体文件的字幕汇总视图（对齐状态 + 字幕语言列表），供卡片墙展示。"""

    alignment_status: str = ALIGNMENT_STATUS_UNKNOWN
    languages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_subtitle_display_language(sub_path: Path) -> Optional[str]:
    """检测字幕语言的展示名称：优先文件名语言标签，失败时回退到内容分析。"""
    hint = SubtitleDetector.infer_language_from_filename(sub_path.name)
    if hint:
        lang_def = SUBTITLE_LANGUAGE_BY_CODE.get(hint)
        return lang_def.display_name if lang_def else hint

    try:
        analysis = SubtitleDetector.analyze_file(sub_path)
    except Exception:
        return None

    name = analysis.detected_language_name
    return name if name and name != "未知" else None


def get_subtitle_summary(session: Session, media_type: str) -> dict[int, SubtitleSummaryInfo]:
    """按媒体文件汇总字幕信息（对齐状态 + 语言列表），供卡片墙展示。

    仅统计 has_subtitle 的文件；单文件存在多个字幕时对齐状态取最差
    （misaligned > unknown > aligned），语言取去重后的并集。返回 {file_id: SubtitleSummaryInfo}。
    """
    record_map = {record.subtitle_path: record for record in session.exec(select(SubtitleAlignmentState)).all()}

    files = session.exec(
        select(ScannedFile).where(ScannedFile.type == media_type, ScannedFile.has_subtitle.is_(True))
    ).all()

    summary: dict[int, SubtitleSummaryInfo] = {}
    for media in files:
        if media.id is None:
            continue

        statuses = []
        languages: list[str] = []
        for sub_path in SubtitleInspectionService._find_related_subtitle_files(Path(media.file_path)):
            record = record_map.get(str(sub_path))
            alignment = _resolve_alignment_from_record(record, sub_path) if record is not None else AlignmentStateInfo()
            statuses.append(alignment.status)

            language = _detect_subtitle_display_language(sub_path)
            if language and language not in languages:
                languages.append(language)

        if statuses:
            summary[media.id] = SubtitleSummaryInfo(
                alignment_status=max(statuses, key=lambda s: _ALIGNMENT_SEVERITY.get(s, 1)),
                languages=languages,
            )

    return summary


def record_alignment_result(
    subtitle_path: Path | str,
    file_id: Optional[int],
    status: str,
    max_shift_ms: Optional[float] = None,
    mean_shift_ms: Optional[float] = None,
    session: Optional[Session] = None,
) -> None:
    """写入/更新字幕的对齐状态（同时记录当前文件签名）。"""

    def _save(target_session: Session) -> None:
        sub_path = Path(subtitle_path)
        size_bytes, mtime_ns = compute_file_signature(sub_path)
        path_str = str(sub_path)
        record = target_session.exec(
            select(SubtitleAlignmentState).where(SubtitleAlignmentState.subtitle_path == path_str)
        ).first()
        now = datetime.now()
        if record is None:
            record = SubtitleAlignmentState(
                subtitle_path=path_str,
                file_id=file_id,
                status=status,
                max_shift_ms=max_shift_ms,
                mean_shift_ms=mean_shift_ms,
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                checked_at=now,
                updated_at=now,
            )
        else:
            record.file_id = file_id
            record.status = status
            record.max_shift_ms = max_shift_ms
            record.mean_shift_ms = mean_shift_ms
            record.size_bytes = size_bytes
            record.mtime_ns = mtime_ns
            record.checked_at = now
            record.updated_at = now
        target_session.add(record)
        target_session.commit()

    if session is not None:
        _save(session)
    else:
        with session_scope() as new_session:
            _save(new_session)


def mark_alignment_unknown(subtitle_path: Path | str, session: Optional[Session] = None) -> None:
    """将字幕对齐状态重置为 unknown（删除状态记录）。"""

    def _delete(target_session: Session) -> None:
        record = target_session.exec(
            select(SubtitleAlignmentState).where(SubtitleAlignmentState.subtitle_path == str(subtitle_path))
        ).first()
        if record is not None:
            target_session.delete(record)
            target_session.commit()

    if session is not None:
        _delete(session)
    else:
        with session_scope() as new_session:
            _delete(new_session)


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
    alignment_status: str = ALIGNMENT_STATUS_UNKNOWN
    alignment_max_shift_ms: float | None = None
    alignment_mean_shift_ms: float | None = None
    alignment_checked_at: str | None = None

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
            info = cls._inspect_single_subtitle(sub_path, session)
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
    def _inspect_single_subtitle(cls, sub_path: Path, session: Optional[Session] = None) -> ExistingSubtitleInfo:
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

        if session is not None:
            alignment = resolve_alignment_state(session, sub_path)
        else:
            alignment = AlignmentStateInfo()

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
            alignment_status=alignment.status,
            alignment_max_shift_ms=alignment.max_shift_ms,
            alignment_mean_shift_ms=alignment.mean_shift_ms,
            alignment_checked_at=alignment.checked_at,
        )
