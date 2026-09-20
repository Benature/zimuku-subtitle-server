import logging
import shutil
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from ..api.schemas import AlignerStatusResponse, SubtitleAlignmentCheckResponse, SubtitleAlignResponse
from ..core.aligner import SubtitleAligner
from ..core.system_load import ensure_system_not_busy, evaluate_system_load, read_system_load
from ..db.models import ScannedFile, SubtitleTask
from .subtitle_inspection_service import (
    ALIGNMENT_STATUS_ALIGNED,
    ALIGNMENT_STATUS_MISALIGNED,
    SubtitleInspectionService,
    mark_alignment_unknown,
    record_alignment_result,
)

logger = logging.getLogger(__name__)


class SubtitleAlignService:
    """音轨对齐、对齐状态检查与字幕版本恢复服务。"""

    @classmethod
    def get_status(cls) -> AlignerStatusResponse:
        status = SubtitleAligner.get_status()
        return AlignerStatusResponse(
            available=status.available,
            engine=status.engine,
            ffmpeg_available=status.ffmpeg_available,
            alass_path=status.alass_path,
            ffsubsync_path=status.ffsubsync_path,
            message=status.message,
        )

    @classmethod
    def _resolve_video_and_subtitle(
        cls,
        session: Session,
        file_id: int,
        filename: Optional[str],
    ) -> tuple[ScannedFile, Path, Path]:
        media = session.get(ScannedFile, file_id)
        if media is None:
            raise LookupError(f"未找到媒体文件 ID: {file_id}")

        video_path = Path(media.file_path)
        if not video_path.is_file():
            raise LookupError(f"媒体视频文件不存在: {video_path}")

        subtitle_paths = SubtitleInspectionService._find_related_subtitle_files(video_path)
        if not subtitle_paths:
            raise LookupError(f"媒体文件 '{media.filename}' 暂无任何关联字幕")

        target_sub: Optional[Path] = None
        if filename:
            safe_name = Path(filename).name
            if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
                raise ValueError("filename 格式无效")

            for sub_p in subtitle_paths:
                if sub_p.name == safe_name:
                    target_sub = sub_p
                    break

            if target_sub is None:
                available = [p.name for p in subtitle_paths]
                raise LookupError(f"未找到指定字幕 '{filename}'。可用字幕: {', '.join(available)}")
        else:
            if len(subtitle_paths) == 1:
                target_sub = subtitle_paths[0]
            else:
                available = [p.name for p in subtitle_paths]
                raise ValueError(f"存在多个关联字幕，请指定具体字幕文件名: {', '.join(available)}")

        return media, video_path, target_sub

    @staticmethod
    def _backup_original(target_sub: Path) -> Path:
        """备份原字幕（仅在最初未备份时建立，保留最原始版本）。"""
        backup_path = target_sub.with_name(f"{target_sub.stem}.orig{target_sub.suffix}")
        if not backup_path.exists():
            shutil.copy2(target_sub, backup_path)
            logger.info("Created original backup for subtitle %s at %s", target_sub, backup_path)
        return backup_path

    @classmethod
    async def align_media_subtitle(
        cls,
        session: Session,
        file_id: int,
        filename: Optional[str] = None,
        split_penalty: float = 7.0,
        force: bool = False,
    ) -> SubtitleAlignResponse:
        if not force:
            ensure_system_not_busy()

        media, video_path, target_sub = cls._resolve_video_and_subtitle(session, file_id, filename)

        sub_suffix = target_sub.suffix.lower()
        if sub_suffix not in SubtitleAligner.SUPPORTED_SUBTITLE_FORMATS:
            raise ValueError(f"字幕格式 '{sub_suffix}' 不支持音轨对齐")

        backup_path = cls._backup_original(target_sub)

        logger.info(
            "Starting subtitle alignment for media=%s, sub=%s, video=%s",
            media.id,
            target_sub.name,
            video_path,
        )
        await SubtitleAligner.align(
            reference_path=video_path,
            subtitle_path=target_sub,
            output_path=target_sub,
            split_penalty=split_penalty,
        )

        record_alignment_result(
            subtitle_path=target_sub,
            file_id=media.id,
            status=ALIGNMENT_STATUS_ALIGNED,
            session=session,
        )

        return SubtitleAlignResponse(
            status="ok",
            message=f"字幕 '{target_sub.name}' 音轨对齐完成",
            file_id=media.id,
            subtitle_filename=target_sub.name,
            backup_filename=backup_path.name,
            has_backup=True,
        )

    @classmethod
    async def check_media_subtitle_alignment(
        cls,
        session: Session,
        file_id: int,
        filename: Optional[str] = None,
        threshold_ms: float = 100.0,
        force: bool = False,
    ) -> SubtitleAlignmentCheckResponse:
        if not force:
            ensure_system_not_busy()

        media, video_path, target_sub = cls._resolve_video_and_subtitle(session, file_id, filename)

        sub_suffix = target_sub.suffix.lower()
        if sub_suffix not in SubtitleAligner.SUPPORTED_SUBTITLE_FORMATS:
            raise ValueError(f"字幕格式 '{sub_suffix}' 不支持音轨对齐检查")

        result = await SubtitleAligner.check_alignment(
            reference_path=video_path,
            subtitle_path=target_sub,
            threshold_ms=threshold_ms,
        )

        record_alignment_result(
            subtitle_path=target_sub,
            file_id=media.id,
            status=ALIGNMENT_STATUS_ALIGNED if result.aligned else ALIGNMENT_STATUS_MISALIGNED,
            max_shift_ms=result.max_shift_ms,
            mean_shift_ms=result.mean_shift_ms,
            session=session,
        )

        return SubtitleAlignmentCheckResponse(
            status="ok",
            aligned=result.aligned,
            checked_cues=result.checked_cues,
            max_shift_ms=result.max_shift_ms,
            mean_shift_ms=result.mean_shift_ms,
            threshold_ms=result.threshold_ms,
            message=f"字幕 '{target_sub.name}': {result.message}",
            file_id=media.id,
            subtitle_filename=target_sub.name,
        )

    @classmethod
    def restore_media_subtitle(
        cls,
        session: Session,
        file_id: int,
        filename: str,
    ) -> SubtitleAlignResponse:
        media = session.get(ScannedFile, file_id)
        if media is None:
            raise LookupError(f"未找到媒体文件 ID: {file_id}")

        safe_name = Path(filename).name
        if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
            raise ValueError("filename 格式无效")

        video_path = Path(media.file_path)
        subtitle_paths = SubtitleInspectionService._find_related_subtitle_files(video_path)
        target_sub = next((p for p in subtitle_paths if p.name == safe_name), None)
        if target_sub is None:
            # 即使原字幕可能已被重命名，根据期望位置定位
            target_sub = video_path.parent / safe_name

        backup_path = target_sub.with_name(f"{target_sub.stem}.orig{target_sub.suffix}")
        if not backup_path.is_file():
            raise LookupError(f"未找到字幕 '{filename}' 的原始备份文件 (.orig)，无法还原")

        # 覆盖还原原字幕
        shutil.move(str(backup_path), str(target_sub))
        logger.info("Restored original subtitle %s from %s", target_sub, backup_path)
        mark_alignment_unknown(target_sub, session=session)

        return SubtitleAlignResponse(
            status="ok",
            message=f"字幕 '{target_sub.name}' 已成功还原为原始版本",
            file_id=media.id,
            subtitle_filename=target_sub.name,
            backup_filename=None,
            has_backup=False,
        )

    @classmethod
    async def auto_align_for_task(cls, task: SubtitleTask, save_path: str) -> bool:
        """下载任务完成后的自动对齐入口（失败仅记录日志，不影响任务状态）。

        :return: 是否成功执行了自动对齐
        """
        sub_path = Path(save_path)
        if sub_path.suffix.lower() not in SubtitleAligner.SUPPORTED_SUBTITLE_FORMATS:
            logger.info("task %s: skip auto-align, unsupported subtitle format %s", task.id, sub_path.suffix)
            return False

        if not sub_path.is_file():
            logger.warning("task %s: skip auto-align, subtitle file missing: %s", task.id, sub_path)
            return False

        video_path = Path(task.target_path) if task.target_path else None
        if not video_path or not video_path.is_file():
            logger.info("task %s: skip auto-align, no associated video file", task.id)
            return False

        busy_reason = evaluate_system_load(read_system_load())
        if busy_reason:
            logger.info("task %s: skip auto-align, system busy: %s", task.id, busy_reason)
            return False

        try:
            cls._backup_original(sub_path)
            await SubtitleAligner.align(
                reference_path=video_path,
                subtitle_path=sub_path,
                output_path=sub_path,
            )
            record_alignment_result(
                subtitle_path=sub_path,
                file_id=task.file_id,
                status=ALIGNMENT_STATUS_ALIGNED,
            )
            logger.info("task %s: auto-align completed for %s", task.id, sub_path.name)
            return True
        except Exception as exc:
            logger.warning("task %s: auto-align failed for %s: %s", task.id, sub_path.name, exc)
            return False

    @classmethod
    async def align_task_subtitle(
        cls,
        session: Session,
        task_id: int,
        split_penalty: float = 7.0,
        force: bool = False,
    ) -> SubtitleAlignResponse:
        task = session.get(SubtitleTask, task_id)
        if task is None:
            raise LookupError(f"未找到任务 ID: {task_id}")

        if task.status != "completed":
            raise ValueError(f"任务尚未完成下载 (当前状态: {task.status})，无法执行音轨对齐")

        # 若任务已关联媒体记录，直接通过媒体服务对齐
        if task.file_id:
            return await cls.align_media_subtitle(
                session=session,
                file_id=task.file_id,
                filename=Path(task.save_path).name if task.save_path else None,
                split_penalty=split_penalty,
                force=force,
            )

        if task.target_path:
            media = session.exec(select(ScannedFile).where(ScannedFile.file_path == task.target_path)).first()
            if media and media.id:
                return await cls.align_media_subtitle(
                    session=session,
                    file_id=media.id,
                    filename=Path(task.save_path).name if task.save_path else None,
                    split_penalty=split_penalty,
                    force=force,
                )

        # 兜底：直接依据任务保存路径与目标视频路径对齐
        if not force:
            ensure_system_not_busy()

        if not task.save_path or not Path(task.save_path).is_file():
            raise LookupError("任务缺少有效的字幕文件保存路径")

        sub_path = Path(task.save_path)
        video_path = Path(task.target_path) if task.target_path else None
        if not video_path or not video_path.is_file():
            raise LookupError("任务未关联有效的视频文件，无法执行音轨对齐")

        backup_path = cls._backup_original(sub_path)

        await SubtitleAligner.align(
            reference_path=video_path,
            subtitle_path=sub_path,
            output_path=sub_path,
            split_penalty=split_penalty,
        )

        record_alignment_result(
            subtitle_path=sub_path,
            file_id=task.file_id,
            status=ALIGNMENT_STATUS_ALIGNED,
            session=session,
        )

        return SubtitleAlignResponse(
            status="ok",
            message=f"字幕 '{sub_path.name}' 音轨对齐完成",
            file_id=task.file_id,
            subtitle_filename=sub_path.name,
            backup_filename=backup_path.name,
            has_backup=True,
        )
