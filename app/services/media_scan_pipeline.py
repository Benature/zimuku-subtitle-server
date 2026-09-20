import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from sqlmodel import Session, col, select

from ..core.metadata import find_nfo_file, parse_nfo
from ..core.utils import check_has_subtitle, parse_media_filename
from ..db.models import MediaPath, ScannedFile
from .auto_match_workflow import normalize_media_title

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".ts", ".rmvb"}


@dataclass
class DiscoveredMediaFile:
    path_id: int
    media_type: str
    file_path: str
    filename: str
    extracted_title: str
    year: Optional[str]
    nfo_title: Optional[str]
    nfo_original_title: Optional[str]
    nfo_aliases: Optional[str]
    season: Optional[int]
    episode: Optional[int]
    has_subtitle: bool
    series_root_path: Optional[str]


class MediaScanPipeline:
    def __init__(self, session: Session, path_type: Optional[str] = None):
        self.session = session
        self.path_type = path_type

    def run(self) -> None:
        self.cleanup_orphan_records()

        media_paths = self.load_enabled_paths()
        self.cleanup_missing_files(media_paths)

        if not media_paths:
            return

        existing_records = self.load_existing_records(media_paths)
        discovered_files: List[DiscoveredMediaFile] = []
        scanned_path_ids: Set[int] = set()

        for media_path in media_paths:
            path_files = self.discover_path(media_path)
            if path_files is None:
                continue
            discovered_files.extend(path_files)
            if media_path.id is not None:
                scanned_path_ids.add(media_path.id)
            media_path.last_scanned_at = datetime.now()
            self.session.add(media_path)

        self.cleanup_records_missing_from_discovery(discovered_files, existing_records, scanned_path_ids)
        flagged_work_keys = self.load_flagged_work_keys()
        self.reconcile_records(discovered_files, existing_records, flagged_work_keys)
        self.session.commit()

    @staticmethod
    def build_work_key(media_type: str, title: Optional[str], filename: str) -> tuple[str, str]:
        """作品级标记键：媒体类型 + 规范化标题（与去年份标题的匹配口径一致）。"""
        return (media_type, normalize_media_title(title or filename))

    def load_flagged_work_keys(self) -> Set[tuple[str, str]]:
        """加载所有被标记「允许无字幕」的作品键，供新扫描文件继承标记。"""
        statement = select(ScannedFile).where(col(ScannedFile.allow_no_subtitle).is_(True))
        return {
            self.build_work_key(record.type, record.extracted_title, record.filename)
            for record in self.session.exec(statement).all()
        }

    def cleanup_orphan_records(self) -> None:
        path_ids = [path_id for path_id in self.session.exec(select(MediaPath.id)).all() if path_id is not None]
        statement = select(ScannedFile)
        if path_ids:
            statement = statement.where(col(ScannedFile.path_id).notin_(path_ids))
        orphan_files = self.session.exec(statement).all()

        for orphan_file in orphan_files:
            self.session.delete(orphan_file)

        if orphan_files:
            logger.info(f"清理了 {len(orphan_files)} 条孤儿文件记录")
            self.session.commit()

    @staticmethod
    def is_path_accessible(media_path: MediaPath) -> bool:
        scan_dir = Path(media_path.path)
        return scan_dir.exists() and scan_dir.is_dir()

    def cleanup_missing_files(self, media_paths: Sequence[MediaPath]) -> None:
        # 挂载点缺失（如磁盘未挂载、容器挂载配置丢失）时，媒体根目录整体不可访问，
        # 其下文件必然全部"不存在"，若照常清理会误删全部记录；此时跳过这些路径的清理
        inaccessible_ids = {
            media_path.id
            for media_path in media_paths
            if media_path.id is not None and not self.is_path_accessible(media_path)
        }
        if inaccessible_ids:
            logger.warning(
                "媒体路径不可访问，跳过其文件记录清理: %s",
                [media_path.path for media_path in media_paths if media_path.id in inaccessible_ids],
            )

        statement = select(ScannedFile)
        if self.path_type:
            statement = statement.where(ScannedFile.type == self.path_type)

        removed_files = []
        for scanned_file in self.session.exec(statement).all():
            if scanned_file.path_id in inaccessible_ids:
                continue
            if not Path(scanned_file.file_path).exists():
                self.session.delete(scanned_file)
                removed_files.append(scanned_file)

        if removed_files:
            logger.info(f"清理了 {len(removed_files)} 条物理已不存在的记录")
            self.session.commit()

    def load_enabled_paths(self) -> List[MediaPath]:
        statement = select(MediaPath).where(MediaPath.enabled)
        if self.path_type:
            statement = statement.where(MediaPath.type == self.path_type)
        return list(self.session.exec(statement).all())

    def load_existing_records(self, media_paths: Sequence[MediaPath]) -> Dict[str, ScannedFile]:
        path_ids = [media_path.id for media_path in media_paths if media_path.id is not None]
        if not path_ids:
            return {}

        statement = select(ScannedFile).where(col(ScannedFile.path_id).in_(path_ids))
        return {record.file_path: record for record in self.session.exec(statement).all()}

    def discover_path(self, media_path: MediaPath) -> Optional[List[DiscoveredMediaFile]]:
        scan_dir = Path(media_path.path)
        if not scan_dir.exists() or not scan_dir.is_dir():
            # 返回 None 让调用方跳过该路径的清理与扫描，避免挂载缺失时误删记录
            logger.warning(f"媒体路径不可访问，跳过扫描: {media_path.path}")
            return None

        logger.info(f"扫描路径: {media_path.path}")
        logger.debug(f"开始扫描路径: {media_path.path}")

        discovered_files: List[DiscoveredMediaFile] = []
        try:
            for root_dir in self.iter_scan_roots(scan_dir):
                discovered_files.extend(self.discover_root_files(media_path, root_dir))
        except Exception as exc:
            logger.error(f"扫描 {media_path.path} 出错: {exc}")
            return None
        return discovered_files

    def discover_root_files(self, media_path: MediaPath, root_dir: Path) -> List[DiscoveredMediaFile]:
        extracted_title = root_dir.name
        series_root_path = self.build_series_root_path(media_path.type, root_dir)
        root_nfo_data = self.load_root_nfo_data(media_path.type, root_dir)
        return [
            self.build_discovered_file(
                media_path=media_path,
                file_path=file_path,
                extracted_title=extracted_title,
                series_root_path=series_root_path,
                root_nfo_data=root_nfo_data,
            )
            for file_path in self.iter_video_files(root_dir, media_path.type)
        ]

    @staticmethod
    def load_root_nfo_data(media_type: str, root_dir: Path) -> Optional[dict]:
        nfo_path = root_dir / "tvshow.nfo" if media_type == "tv" else find_nfo_file(root_dir)
        return parse_nfo(nfo_path) if nfo_path else None

    def iter_scan_roots(self, scan_dir: Path) -> Iterable[Path]:
        for child in scan_dir.iterdir():
            logger.debug(f"处理子目录: {child}")
            if child.is_dir():
                yield child

    @staticmethod
    def build_series_root_path(media_type: str, root_dir: Path) -> Optional[str]:
        if media_type != "tv":
            return None
        return str(root_dir.absolute())

    def iter_video_files(self, root_dir: Path, media_type: str) -> Iterable[Path]:
        iterator = root_dir.rglob("*") if media_type == "tv" else root_dir.iterdir()
        for file_path in iterator:
            if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
                yield file_path

    def build_discovered_file(
        self,
        media_path: MediaPath,
        file_path: Path,
        extracted_title: str,
        series_root_path: Optional[str],
        root_nfo_data: Optional[dict],
    ) -> DiscoveredMediaFile:
        filename = file_path.name
        parsed = parse_media_filename(filename)
        nfo_data = root_nfo_data or self.load_file_nfo_data(file_path, filename)
        nfo_title, nfo_original_title, nfo_aliases = self.extract_nfo_search_fields(nfo_data)
        return DiscoveredMediaFile(
            path_id=media_path.id or 0,
            media_type=media_path.type,
            file_path=str(file_path.absolute()),
            filename=filename,
            extracted_title=extracted_title,
            year=parsed["year"],
            nfo_title=nfo_title,
            nfo_original_title=nfo_original_title,
            nfo_aliases=nfo_aliases,
            season=parsed["season"],
            episode=parsed["episode"],
            has_subtitle=check_has_subtitle(file_path),
            series_root_path=series_root_path,
        )

    @staticmethod
    def load_file_nfo_data(file_path: Path, filename: str) -> Optional[dict]:
        nfo_path = find_nfo_file(file_path.parent, filename)
        return parse_nfo(nfo_path) if nfo_path else None

    @staticmethod
    def extract_nfo_search_fields(nfo_data: Optional[dict]) -> tuple[Optional[str], Optional[str], Optional[str]]:
        if not nfo_data:
            return None, None, None

        aliases = nfo_data.get("aliases", [])
        aliases_json = json.dumps(aliases, ensure_ascii=False) if aliases else None
        return nfo_data.get("title"), nfo_data.get("original_title"), aliases_json

    def reconcile_records(
        self,
        discovered_files: Sequence[DiscoveredMediaFile],
        existing_records: Dict[str, ScannedFile],
        flagged_work_keys: Optional[Set[tuple[str, str]]] = None,
    ) -> None:
        flagged_work_keys = flagged_work_keys or set()
        for discovered in discovered_files:
            existing_file = existing_records.get(discovered.file_path)
            if existing_file is None:
                # 新文件继承同作品已有的「允许无字幕」标记，避免新增剧集/版本被重复补全
                allow_no_subtitle = (
                    self.build_work_key(discovered.media_type, discovered.extracted_title, discovered.filename)
                    in flagged_work_keys
                )
                existing_file = self.create_scanned_file(discovered, allow_no_subtitle=allow_no_subtitle)
            else:
                self.apply_discovered_fields(existing_file, discovered)

            self.session.add(existing_file)

    def cleanup_records_missing_from_discovery(
        self,
        discovered_files: Sequence[DiscoveredMediaFile],
        existing_records: Dict[str, ScannedFile],
        scanned_path_ids: Set[int],
    ) -> None:
        discovered_paths = {discovered.file_path for discovered in discovered_files}
        removed_files = []

        for existing_file in existing_records.values():
            if existing_file.path_id not in scanned_path_ids:
                continue
            if existing_file.file_path in discovered_paths:
                continue

            self.session.delete(existing_file)
            removed_files.append(existing_file)

        if removed_files:
            logger.info(f"清理了 {len(removed_files)} 条本次扫描未发现的旧文件记录")

    @staticmethod
    def create_scanned_file(discovered: DiscoveredMediaFile, allow_no_subtitle: bool = False) -> ScannedFile:
        return ScannedFile(
            path_id=discovered.path_id,
            type=discovered.media_type,
            file_path=discovered.file_path,
            filename=discovered.filename,
            extracted_title=discovered.extracted_title,
            year=discovered.year,
            nfo_title=discovered.nfo_title,
            nfo_original_title=discovered.nfo_original_title,
            nfo_aliases=discovered.nfo_aliases,
            season=discovered.season,
            episode=discovered.episode,
            has_subtitle=discovered.has_subtitle,
            allow_no_subtitle=allow_no_subtitle,
            series_root_path=discovered.series_root_path,
        )

    @staticmethod
    def apply_discovered_fields(existing_file: ScannedFile, discovered: DiscoveredMediaFile) -> None:
        existing_file.path_id = discovered.path_id
        existing_file.type = discovered.media_type
        existing_file.filename = discovered.filename
        existing_file.extracted_title = discovered.extracted_title
        existing_file.year = discovered.year
        existing_file.nfo_title = discovered.nfo_title
        existing_file.nfo_original_title = discovered.nfo_original_title
        existing_file.nfo_aliases = discovered.nfo_aliases
        existing_file.season = discovered.season
        existing_file.episode = discovered.episode
        existing_file.has_subtitle = discovered.has_subtitle
        existing_file.series_root_path = discovered.series_root_path
