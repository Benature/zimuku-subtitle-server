import json
import logging
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlmodel import Session, col, select

from ..core.config import ConfigManager, SettingKey, get_trash_path
from ..core.utils import SUBTITLE_EXTENSIONS
from ..db.models import ScannedFile, SubtitleTrash
from .subtitle_inspection_service import (
    SubtitleInspectionError,
    SubtitleInspectionService,
    SubtitleInvalidRequestError,
    SubtitleNotFoundError,
)

logger = logging.getLogger(__name__)

DEFAULT_TRASH_RETENTION_DAYS = 365


@dataclass(frozen=True)
class SubtitleTrashResult:
    trash_id: int
    file_id: int | None
    media_filename: str | None
    subtitle_filename: str
    original_path: str
    trash_path: str
    has_backup: bool
    size_bytes: int
    trashed_at: str
    remaining_subtitles: list[str]
    has_subtitle: bool
    is_permanent_deletion: bool = False
    message: str = "字幕已安全移入回收站（支持随时还原），非永久删除"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubtitleRestoreResult:
    trash_id: int
    file_id: int | None
    subtitle_filename: str
    restored_path: str
    has_backup_restored: bool
    restored_at: str
    has_subtitle: bool
    message: str = "字幕已成功从回收站还原"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubtitleTrashPurgeResult:
    retention_days: int
    cutoff: str | None
    purged_count: int
    purged_records: list[dict[str, Any]]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubtitleTrashService:
    """字幕安全回收与版本还原服务（严格避免永久删除，支持审计与一键还原）。"""

    @classmethod
    def get_retention_days(cls) -> int:
        """读取回收站保留天数配置（默认 365 天，0 表示永久保留）。"""
        return ConfigManager.get_int(SettingKey.TRASH_RETENTION_DAYS, DEFAULT_TRASH_RETENTION_DAYS)

    @classmethod
    def purge_expired(
        cls,
        session: Session,
        *,
        retention_days: Optional[int] = None,
    ) -> SubtitleTrashPurgeResult:
        """彻底删除超过保留时长的回收站条目（文件与记录）。

        仅清理未还原且回收时间早于截止时间的条目；retention_days=0 表示永久保留，不做任何清理。
        """
        days = retention_days if retention_days is not None else cls.get_retention_days()
        if days <= 0:
            return SubtitleTrashPurgeResult(
                retention_days=0,
                cutoff=None,
                purged_count=0,
                purged_records=[],
                message="回收站保留策略为永久保留（0 天），未执行清理",
            )

        cutoff = datetime.now() - timedelta(days=days)
        stmt = select(SubtitleTrash).where(
            col(SubtitleTrash.is_restored).is_(False),
            SubtitleTrash.trashed_at < cutoff,
        )
        expired_records = list(session.exec(stmt).all())

        purged_records: list[dict[str, Any]] = []
        for record in expired_records:
            entry_dir = Path(record.trash_path).parent
            try:
                if entry_dir.is_dir():
                    shutil.rmtree(entry_dir)
            except OSError as exc:
                logger.warning("清理过期回收站目录失败 (%s): %s", entry_dir, exc)
                continue

            purged_records.append(
                {
                    "trash_id": record.id,
                    "subtitle_filename": record.subtitle_filename,
                    "original_path": record.original_path,
                    "trashed_at": record.trashed_at.isoformat() if record.trashed_at else "",
                }
            )
            session.delete(record)
            logger.info(
                "回收站条目已过期并彻底删除: trash_id=%s, file=%s, trashed_at=%s",
                record.id,
                record.subtitle_filename,
                record.trashed_at,
            )

        session.commit()
        return SubtitleTrashPurgeResult(
            retention_days=days,
            cutoff=cutoff.isoformat(),
            purged_count=len(purged_records),
            purged_records=purged_records,
            message=f"已按保留策略（{days} 天）彻底删除 {len(purged_records)} 条过期回收站记录",
        )

    @classmethod
    def trash_subtitle(
        cls,
        session: Session,
        *,
        file_id: Optional[int] = None,
        filename: Optional[str] = None,
        subtitle_path: Optional[str] = None,
    ) -> SubtitleTrashResult:
        """将媒体字幕安全移入系统回收站（保留元数据与备份，非永久删除）。"""
        # 先按保留策略清理过期条目，保持回收站体量可控（失败不阻塞本次回收）
        try:
            cls.purge_expired(session)
        except Exception as exc:
            logger.warning("自动清理过期回收站条目失败（忽略，继续回收）: %s", exc)

        target_sub, media = cls._resolve_target_subtitle(
            session=session,
            file_id=file_id,
            filename=filename,
            subtitle_path=subtitle_path,
        )

        if not target_sub.is_file():
            raise SubtitleNotFoundError(f"待回收的字幕文件不存在: {target_sub}")

        suffix = target_sub.suffix.lower()
        if suffix not in SUBTITLE_EXTENSIONS:
            raise SubtitleInvalidRequestError(f"文件格式 '{suffix}' 不是受支持的字幕格式")

        # 检查是否有原版对齐备份 (.orig)
        orig_backup = target_sub.with_name(f"{target_sub.stem}.orig{target_sub.suffix}")
        has_backup = orig_backup.is_file()

        try:
            stat = target_sub.stat()
            file_size = stat.st_size
        except OSError as exc:
            raise SubtitleInspectionError(f"无法读取待回收字幕文件状态: {exc}") from exc

        # 构建独立的回收站条目目录
        trash_root = Path(get_trash_path()) / "subtitles"
        trash_root.mkdir(parents=True, exist_ok=True)

        now_utc = datetime.now(timezone.utc)
        timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
        token = uuid.uuid4().hex[:8]
        entry_folder_name = f"{timestamp_str}_{token}_{target_sub.name}"
        trash_entry_dir = trash_root / entry_folder_name
        trash_entry_dir.mkdir(parents=True, exist_ok=True)

        dest_sub_path = trash_entry_dir / target_sub.name
        dest_backup_path = (trash_entry_dir / orig_backup.name) if has_backup else None

        # 移动文件到回收站
        try:
            shutil.move(str(target_sub), str(dest_sub_path))
            if has_backup and dest_backup_path:
                shutil.move(str(orig_backup), str(dest_backup_path))
        except OSError as exc:
            logger.exception("移入回收站失败: %s", exc)
            # 尝试回滚已移动的文件
            if dest_sub_path.exists() and not target_sub.exists():
                try:
                    shutil.move(str(dest_sub_path), str(target_sub))
                except Exception:
                    pass
            if dest_backup_path and dest_backup_path.exists() and not orig_backup.exists():
                try:
                    shutil.move(str(dest_backup_path), str(orig_backup))
                except Exception:
                    pass
            raise SubtitleInspectionError(f"移动文件至回收站失败: {exc}") from exc

        # 写入元数据 trashinfo.json
        meta_data = {
            "original_path": str(target_sub),
            "filename": target_sub.name,
            "size_bytes": file_size,
            "trashed_at": now_utc.isoformat(),
            "file_id": media.id if media else None,
            "media_filename": media.filename if media else None,
            "has_backup": has_backup,
            "backup_original_path": str(orig_backup) if has_backup else None,
            "is_permanent_deletion": False,
        }
        meta_file = trash_entry_dir / "trashinfo.json"
        try:
            meta_file.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("写入回收站元数据文件失败: %s", exc)

        # 写入持久化数据表
        trash_record = SubtitleTrash(
            file_id=media.id if media else None,
            media_filename=media.filename if media else None,
            subtitle_filename=target_sub.name,
            original_path=str(target_sub),
            trash_path=str(dest_sub_path),
            backup_original_path=str(orig_backup) if has_backup else None,
            backup_trash_path=str(dest_backup_path) if has_backup and dest_backup_path else None,
            size_bytes=file_size,
            trashed_at=datetime.now(),
            is_restored=False,
        )
        session.add(trash_record)

        remaining_subtitles: list[str] = []
        if media:
            remaining_paths = SubtitleInspectionService._find_related_subtitle_files(Path(media.file_path))
            remaining_subtitles = [p.name for p in remaining_paths]
            media.has_subtitle = len(remaining_subtitles) > 0
            session.add(media)

        session.commit()
        session.refresh(trash_record)

        logger.info(
            "字幕已安全移入回收站: %s -> %s (trash_id=%s)",
            target_sub,
            dest_sub_path,
            trash_record.id,
        )

        return SubtitleTrashResult(
            trash_id=trash_record.id or 0,
            file_id=media.id if media else None,
            media_filename=media.filename if media else None,
            subtitle_filename=target_sub.name,
            original_path=str(target_sub),
            trash_path=str(dest_sub_path),
            has_backup=has_backup,
            size_bytes=file_size,
            trashed_at=trash_record.trashed_at.isoformat(),
            remaining_subtitles=remaining_subtitles,
            has_subtitle=media.has_subtitle if media else False,
            is_permanent_deletion=False,
            message=f"字幕 '{target_sub.name}' 已成功移入系统回收站（非永久删除，支持随时还原）",
        )

    @classmethod
    def restore_subtitle(
        cls,
        session: Session,
        *,
        trash_id: Optional[int] = None,
        file_id: Optional[int] = None,
        filename: Optional[str] = None,
        subtitle_path: Optional[str] = None,
        overwrite: bool = False,
    ) -> SubtitleRestoreResult:
        """从回收站中还原字幕文件至原视频目录。"""
        trash_record = cls._resolve_trash_record(
            session=session,
            trash_id=trash_id,
            file_id=file_id,
            filename=filename,
            subtitle_path=subtitle_path,
        )

        sub_in_trash = Path(trash_record.trash_path)
        if not sub_in_trash.is_file():
            raise SubtitleNotFoundError(f"回收站内的字幕文件已丢失或不存在: {trash_record.trash_path}")

        dest_sub = Path(trash_record.original_path)
        if dest_sub.exists() and not overwrite:
            raise SubtitleInvalidRequestError(
                f"还原目标位置已存在同名文件 '{dest_sub.name}'，若需覆盖请指定 overwrite=True"
            )

        # 确保目标父目录存在
        dest_sub.parent.mkdir(parents=True, exist_ok=True)

        has_backup_restored = False
        backup_in_trash = Path(trash_record.backup_trash_path) if trash_record.backup_trash_path else None
        dest_backup = Path(trash_record.backup_original_path) if trash_record.backup_original_path else None

        try:
            shutil.move(str(sub_in_trash), str(dest_sub))
            if backup_in_trash and backup_in_trash.is_file() and dest_backup:
                shutil.move(str(backup_in_trash), str(dest_backup))
                has_backup_restored = True
        except OSError as exc:
            logger.exception("从回收站还原失败: %s", exc)
            raise SubtitleInspectionError(f"从回收站还原文件失败: {exc}") from exc

        # 更新数据库状态
        trash_record.is_restored = True
        trash_record.restored_at = datetime.now()
        session.add(trash_record)

        media: Optional[ScannedFile] = None
        if trash_record.file_id:
            media = session.get(ScannedFile, trash_record.file_id)
            if media:
                media.has_subtitle = True
                session.add(media)

        session.commit()
        session.refresh(trash_record)

        logger.info(
            "字幕已从回收站还原: %s -> %s (trash_id=%s)",
            trash_record.trash_path,
            dest_sub,
            trash_record.id,
        )

        return SubtitleRestoreResult(
            trash_id=trash_record.id or 0,
            file_id=trash_record.file_id,
            subtitle_filename=dest_sub.name,
            restored_path=str(dest_sub),
            has_backup_restored=has_backup_restored,
            restored_at=trash_record.restored_at.isoformat() if trash_record.restored_at else "",
            has_subtitle=media.has_subtitle if media else True,
            message=f"字幕 '{dest_sub.name}' 已成功从回收站还原",
        )

    @classmethod
    def list_trashed(
        cls,
        session: Session,
        *,
        file_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 50,
        include_restored: bool = False,
    ) -> tuple[list[SubtitleTrash], int]:
        """分页查询回收站中的字幕记录。"""
        stmt = select(SubtitleTrash)
        if file_id is not None:
            stmt = stmt.where(SubtitleTrash.file_id == file_id)
        if not include_restored:
            stmt = stmt.where(col(SubtitleTrash.is_restored).is_(False))

        # 查询总数
        from sqlmodel import func

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one() or 0

        # 分页查询
        stmt = stmt.order_by(col(SubtitleTrash.id).desc()).offset(offset).limit(limit)
        items = list(session.exec(stmt).all())
        return items, total

    @classmethod
    def _resolve_target_subtitle(
        cls,
        session: Session,
        file_id: Optional[int],
        filename: Optional[str],
        subtitle_path: Optional[str],
    ) -> tuple[Path, Optional[ScannedFile]]:
        """根据 file_id/filename 或 subtitle_path 定位具体的字幕文件与关联媒体记录。"""
        if file_id is not None:
            media = session.get(ScannedFile, file_id)
            if media is None:
                raise SubtitleNotFoundError(f"未找到媒体文件 ID: {file_id}")

            video_path = Path(media.file_path)
            subtitles = SubtitleInspectionService._find_related_subtitle_files(video_path)
            if not subtitles:
                raise SubtitleNotFoundError(f"媒体文件 '{media.filename}' 暂无任何关联字幕")

            if filename:
                safe_name = Path(filename).name
                if safe_name != filename or ".." in filename or "/" in filename or "\\" in filename:
                    raise SubtitleInvalidRequestError("filename 格式无效")

                target = next((p for p in subtitles if p.name == safe_name), None)
                if target is None:
                    available = [p.name for p in subtitles]
                    raise SubtitleNotFoundError(f"未找到指定字幕 '{filename}'。可用字幕: {', '.join(available)}")
                return target, media
            else:
                if len(subtitles) == 1:
                    return subtitles[0], media
                else:
                    available = [p.name for p in subtitles]
                    raise SubtitleInvalidRequestError(
                        f"存在多个关联字幕，请通过 filename 参数指定其中一个。可用字幕: {', '.join(available)}"
                    )

        if subtitle_path:
            clean_path = Path(subtitle_path).resolve()
            if not clean_path.exists():
                raise SubtitleNotFoundError(f"字幕文件不存在: {subtitle_path}")

            # 尝试通过所在目录和前缀查找对应的 ScannedFile
            media = cls._find_media_for_subtitle_path(session, clean_path)
            return clean_path, media

        raise SubtitleInvalidRequestError("必须提供 file_id 或 subtitle_path 参数以指定待移入回收站的字幕")

    @classmethod
    def _resolve_trash_record(
        cls,
        session: Session,
        trash_id: Optional[int],
        file_id: Optional[int],
        filename: Optional[str],
        subtitle_path: Optional[str],
    ) -> SubtitleTrash:
        """解析并获取待还原的 SubtitleTrash 记录。"""
        if trash_id is not None:
            record = session.get(SubtitleTrash, trash_id)
            if record is None:
                raise SubtitleNotFoundError(f"未找到回收站记录 ID: {trash_id}")
            if record.is_restored:
                raise SubtitleInvalidRequestError(f"回收站记录 {trash_id} 此前已完成还原")
            return record

        if file_id is not None and filename:
            stmt = (
                select(SubtitleTrash)
                .where(
                    SubtitleTrash.file_id == file_id,
                    SubtitleTrash.subtitle_filename == filename,
                    col(SubtitleTrash.is_restored).is_(False),
                )
                .order_by(col(SubtitleTrash.id).desc())
            )
            record = session.exec(stmt).first()
            if record is None:
                raise SubtitleNotFoundError(f"在回收站中未找到媒体 {file_id} 对应的字幕 '{filename}'")
            return record

        if subtitle_path:
            stmt = (
                select(SubtitleTrash)
                .where(
                    SubtitleTrash.original_path == str(Path(subtitle_path).resolve()),
                    col(SubtitleTrash.is_restored).is_(False),
                )
                .order_by(col(SubtitleTrash.id).desc())
            )
            record = session.exec(stmt).first()
            if record is None:
                raise SubtitleNotFoundError(f"在回收站中未找到原路径为 '{subtitle_path}' 的未还原记录")
            return record

        raise SubtitleInvalidRequestError("必须提供 trash_id、(file_id + filename) 或 subtitle_path")

    @classmethod
    def _find_media_for_subtitle_path(cls, session: Session, sub_path: Path) -> Optional[ScannedFile]:
        """尝试根据字幕文件路径反查关联的 ScannedFile 记录。"""
        parent_dir = sub_path.parent
        # 若在 Subs 目录下，父目录为视频所在目录
        video_dir = parent_dir.parent if parent_dir.name.lower() == "subs" else parent_dir

        stem = sub_path.stem.lower()
        # 查找 video_dir 下的所有 ScannedFile
        stmt = select(ScannedFile).where(col(ScannedFile.file_path).startswith(str(video_dir)))
        candidates = list(session.exec(stmt).all())
        for candidate in candidates:
            cand_stem = Path(candidate.file_path).stem.lower()
            if stem.startswith(cand_stem):
                return candidate
        return None
