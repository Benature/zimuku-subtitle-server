import json
import logging
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from sqlmodel import Session, col, or_, select

from ..db.models import MediaPath, ScannedFile
from ..db.session import session_scope
from .auto_match_workflow import AutoMatchWorkflow, SeasonMatchWorkflow, normalize_media_title
from .errors import ConflictError
from .media_scan_pipeline import MediaScanPipeline
from .subtitle_align_service import SubtitleAlignService
from .subtitle_inspection_service import SubtitleInspectionService

logger = logging.getLogger(__name__)

MEDIA_LEVEL_TYPES = {"movie": "movie", "show": "tv", "season": "tv", "episode": "tv"}


class MediaTaskStatus:
    def __init__(self):
        self.is_scanning = False
        self.matching_files: Set[int] = set()
        self.matching_seasons: Set[Tuple[str, int]] = set()
        self.aligning_series: Set[str] = set()
        self.aligning_files: Set[int] = set()

    def to_dict(self):
        return {
            "is_scanning": self.is_scanning,
            "matching_files": list(self.matching_files),
            "matching_seasons": [{"title": t, "season": s} for t, s in self.matching_seasons],
            "aligning_series": list(self.aligning_series),
            "aligning_files": list(self.aligning_files),
        }


global_task_status = MediaTaskStatus()


class MediaService:
    @staticmethod
    def list_paths(session: Session) -> List[MediaPath]:
        return list(session.exec(select(MediaPath)).all())

    @staticmethod
    def _build_files_statement(path_type: Optional[str] = None):
        statement = select(ScannedFile)
        if path_type:
            statement = statement.where(ScannedFile.type == path_type)
        return statement.order_by(col(ScannedFile.created_at).desc())

    @staticmethod
    def add_path(session: Session, path: str, path_type: str) -> MediaPath:
        existing = session.exec(select(MediaPath).where(MediaPath.path == path)).first()
        if existing:
            raise ConflictError("Path already exists")

        new_path = MediaPath(path=path, type=path_type)
        session.add(new_path)
        session.commit()
        session.refresh(new_path)
        return new_path

    @staticmethod
    def delete_path(session: Session, path_id: int) -> bool:
        path = session.get(MediaPath, path_id)
        if not path:
            return False

        statement = select(ScannedFile).where(ScannedFile.path_id == path_id)
        file_records = session.exec(statement).all()
        for file_record in file_records:
            session.delete(file_record)

        session.delete(path)
        session.commit()
        return True

    @staticmethod
    def update_path(
        session: Session, path_id: int, enabled: Optional[bool] = None, path_type: Optional[str] = None
    ) -> Optional[MediaPath]:
        db_path = session.get(MediaPath, path_id)
        if not db_path:
            return None

        if enabled is not None:
            db_path.enabled = enabled
        if path_type is not None:
            db_path.type = path_type

        session.add(db_path)
        session.commit()
        session.refresh(db_path)
        return db_path

    @staticmethod
    def list_files(session: Session, path_type: Optional[str] = None) -> List[ScannedFile]:
        statement = MediaService._build_files_statement(path_type)
        return list(session.exec(statement).all())

    @staticmethod
    def list_files_paginated(
        session: Session,
        path_type: Optional[str] = None,
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> List[ScannedFile]:
        statement = MediaService._build_files_statement(path_type).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return list(session.exec(statement).all())

    @staticmethod
    def list_media_paginated(
        session: Session,
        level: str,
        media_type: Optional[str] = None,
        query: Optional[str] = None,
        title: Optional[str] = None,
        season: Optional[int] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[List[dict[str, Any]], int]:
        """按逻辑媒体层级聚合扫描文件，而非直接暴露文件记录。"""
        expected_type = MEDIA_LEVEL_TYPES[level]
        if media_type and media_type != expected_type:
            raise ValueError(f"level '{level}' 仅支持 media_type '{expected_type}'")

        statement = select(ScannedFile).where(ScannedFile.type == expected_type)
        if title:
            statement = statement.where(ScannedFile.extracted_title == title)
        if season is not None:
            statement = statement.where(ScannedFile.season == season)

        matching_group_keys = None
        if query and query.strip():
            pattern = f"%{query.strip().lower()}%"
            matching_statement = statement.where(
                or_(
                    col(ScannedFile.extracted_title).ilike(pattern),
                    col(ScannedFile.filename).ilike(pattern),
                    col(ScannedFile.year).ilike(pattern),
                    col(ScannedFile.nfo_title).ilike(pattern),
                    col(ScannedFile.nfo_original_title).ilike(pattern),
                    col(ScannedFile.nfo_aliases).ilike(pattern),
                )
            )
            matching_group_keys = set()
            for file_record in session.exec(matching_statement).all():
                summary = MediaService._build_media_summary(level, file_record)
                if summary is not None:
                    matching_group_keys.add(summary[0])

        files = list(session.exec(statement).all())
        grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
        for file_record in files:
            summary = MediaService._build_media_summary(level, file_record)
            if summary is None:
                continue

            group_key, item = summary
            if matching_group_keys is not None and group_key not in matching_group_keys:
                continue
            existing = grouped.get(group_key)
            if existing is None:
                item["path_ids"] = {file_record.path_id}
                item["file_count"] = 1
                item["subtitle_file_count"] = int(file_record.has_subtitle)
                item["allow_no_subtitle"] = bool(file_record.allow_no_subtitle)
                item["no_subtitle_allowed_file_count"] = int(file_record.allow_no_subtitle)
                grouped[group_key] = item
                continue

            existing["path_ids"].add(file_record.path_id)
            existing["file_count"] += 1
            existing["subtitle_file_count"] += int(file_record.has_subtitle)
            existing["allow_no_subtitle"] = existing["allow_no_subtitle"] and bool(file_record.allow_no_subtitle)
            existing["no_subtitle_allowed_file_count"] += int(file_record.allow_no_subtitle)

        items = []
        for item in grouped.values():
            item["path_ids"] = sorted(item["path_ids"])
            # 允许无字幕的文件不计入缺失：它们是有意不配字幕的
            item["missing_subtitle_file_count"] = (
                item["file_count"] - item["subtitle_file_count"] - item["no_subtitle_allowed_file_count"]
            )
            items.append(item)

        items.sort(key=lambda item: (item["title"].casefold(), item["season"] or 0, item["episode"] or 0))
        total = len(items)
        return items[offset : offset + limit], total

    @staticmethod
    def _build_media_summary(level: str, file_record: ScannedFile) -> Optional[tuple[tuple[Any, ...], dict[str, Any]]]:
        title = file_record.extracted_title or file_record.filename
        if level == "movie":
            group_key = ("movie", title, file_record.year)
            media_key = f"movie:{title}:{file_record.year or 'unknown'}"
            return group_key, MediaService._create_media_summary(
                level, media_key, title, file_record, year=file_record.year
            )
        if level == "show":
            group_key = ("show", title)
            return group_key, MediaService._create_media_summary(level, f"show:{title}", title, file_record)
        if file_record.season is None:
            return None
        if level == "season":
            group_key = ("season", title, file_record.season)
            media_key = f"show:{title}:season:{file_record.season}"
            return group_key, MediaService._create_media_summary(
                level, media_key, title, file_record, season=file_record.season
            )
        if file_record.episode is None:
            return None
        group_key = ("episode", title, file_record.season, file_record.episode)
        media_key = f"show:{title}:season:{file_record.season}:episode:{file_record.episode}"
        return group_key, MediaService._create_media_summary(
            level,
            media_key,
            title,
            file_record,
            season=file_record.season,
            episode=file_record.episode,
        )

    @staticmethod
    def _create_media_summary(
        level: str,
        media_key: str,
        title: str,
        file_record: ScannedFile,
        year: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> dict[str, Any]:
        return {
            "media_key": media_key,
            "level": level,
            "media_type": MEDIA_LEVEL_TYPES[level],
            "title": title,
            "nfo_title": file_record.nfo_title,
            "nfo_original_title": file_record.nfo_original_title,
            "nfo_aliases": MediaService._deserialize_aliases(file_record.nfo_aliases),
            "year": year,
            "season": season,
            "episode": episode,
        }

    @staticmethod
    def _deserialize_aliases(aliases: Optional[str]) -> List[str]:
        if not aliases:
            return []
        try:
            parsed_aliases = json.loads(aliases)
        except json.JSONDecodeError:
            return []
        return parsed_aliases if isinstance(parsed_aliases, list) else []

    @staticmethod
    def get_file(session: Session, file_id: int) -> Optional[ScannedFile]:
        return session.get(ScannedFile, file_id)

    @staticmethod
    def set_work_allow_no_subtitle(session: Session, media_type: str, title: str, allow: bool) -> int:
        """按作品（电影/剧集，含去年份规范化标题匹配）设置「允许无字幕」标记。

        标记作用于作品下的全部文件；批量/季补全跳过已标记作品。返回更新的文件数。
        """
        query_title = normalize_media_title(title)
        statement = select(ScannedFile).where(
            or_(
                ScannedFile.extracted_title == query_title,
                ScannedFile.extracted_title == title,
            ),
            ScannedFile.type == media_type,
        )
        files = session.exec(statement).all()
        if not files:
            raise LookupError(f"未找到作品: {title}")

        for file_record in files:
            file_record.allow_no_subtitle = allow
            session.add(file_record)
        session.commit()
        return len(files)

    @staticmethod
    async def run_media_scan_and_match(path_type: Optional[str] = None) -> None:
        """刷新媒体库文件记录，不执行字幕搜索、下载或移动。"""
        global_task_status.is_scanning = True
        try:
            with session_scope() as session:
                MediaScanPipeline(session=session, path_type=path_type).run()
        finally:
            global_task_status.is_scanning = False

    @staticmethod
    async def run_auto_match_process(file_id: int) -> bool:
        return await MediaService._run_auto_match_internal(file_id)

    @staticmethod
    async def _run_auto_match_internal(file_id: int) -> bool:
        global_task_status.matching_files.add(file_id)
        try:
            service = AutoMatchWorkflow(session_factory=session_scope)
            return await service.run_for_file(file_id)
        except Exception as e:
            logger.error(f"自动匹配异常: {e}", exc_info=True)
            return False
        finally:
            global_task_status.matching_files.discard(file_id)

    @staticmethod
    async def run_season_match_process(title: str, season: int) -> None:
        global_task_status.matching_seasons.add((title, season))
        try:
            service = SeasonMatchWorkflow(
                session_factory=session_scope,
                auto_match_runner=MediaService.run_auto_match_process,
            )
            await service.run_for_season(title, season)
        except Exception as e:
            logger.debug(f"季匹配异常: title={title}, season={season}, error={e}")
            raise
        finally:
            global_task_status.matching_seasons.discard((title, season))

    @staticmethod
    def _load_series_file_ids(session: Session, title: str) -> List[int]:
        """按剧集标题（含去年份规范化匹配）加载全部 TV 文件 ID，按季/集排序。"""
        query_title = normalize_media_title(title)
        statement = (
            select(ScannedFile)
            .where(
                or_(
                    ScannedFile.extracted_title == query_title,
                    ScannedFile.extracted_title == title,
                ),
                ScannedFile.type == "tv",
            )
            .order_by(col(ScannedFile.season), col(ScannedFile.episode), col(ScannedFile.id))
        )
        files = session.exec(statement).all()
        return [file_record.id for file_record in files if file_record.id is not None]

    @staticmethod
    async def run_series_align_process(title: str) -> None:
        """对指定剧集全部视频文件的所有关联字幕顺序执行音轨对齐（后台任务）。

        单集/单条字幕失败仅记录日志，不中断整体流程；对齐前自动备份 .orig。
        """
        global_task_status.aligning_series.add(title)
        stats = {"aligned": 0, "failed": 0, "skipped_files": 0}
        try:
            with session_scope() as session:
                file_ids = MediaService._load_series_file_ids(session, title)

            logger.info("剧集批量对齐开始: title=%s, files=%s", title, len(file_ids))
            for file_id in file_ids:
                global_task_status.aligning_files.add(file_id)
                try:
                    with session_scope() as session:
                        media = session.get(ScannedFile, file_id)
                        if media is None:
                            continue
                        subtitle_names = [
                            p.name
                            for p in SubtitleInspectionService._find_related_subtitle_files(Path(media.file_path))
                        ]

                    if not subtitle_names:
                        stats["skipped_files"] += 1
                        continue

                    for subtitle_name in subtitle_names:
                        try:
                            with session_scope() as session:
                                await SubtitleAlignService.align_media_subtitle(
                                    session=session,
                                    file_id=file_id,
                                    filename=subtitle_name,
                                )
                            stats["aligned"] += 1
                        except Exception as exc:
                            stats["failed"] += 1
                            logger.warning(
                                "剧集批量对齐单条失败: title=%s, file_id=%s, sub=%s, error=%s",
                                title,
                                file_id,
                                subtitle_name,
                                exc,
                            )
                finally:
                    global_task_status.aligning_files.discard(file_id)
            logger.info("剧集批量对齐完成: title=%s, stats=%s", title, stats)
        except Exception as e:
            logger.error(f"剧集批量对齐异常: title={title}, error={e}", exc_info=True)
            raise
        finally:
            global_task_status.aligning_series.discard(title)
