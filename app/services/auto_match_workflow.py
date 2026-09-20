import asyncio
import json
import logging
import re
import shutil
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from sqlmodel import Session, col, or_, select

from ..core.archive import ArchiveManager
from ..core.config import get_temp_path
from ..core.jellyfin import UnwatchedIndex
from ..core.observability import log_context
from ..core.scraper import ZimukuAgent
from ..db.models import ScannedFile

logger = logging.getLogger(__name__)

SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".vtt", ".sub")


def normalize_media_title(title: str) -> str:
    return re.sub(r"\s*\(\d{4}\)", "", title).strip()


def build_search_queries(
    extracted_title: Optional[str],
    nfo_title: Optional[str] = None,
    nfo_original_title: Optional[str] = None,
    nfo_aliases: Optional[str] = None,
) -> List[str]:
    """构建按优先级排序、去重后的搜索词列表。

    优先使用 NFO 元数据（nfo_title → nfo_original_title → aliases），
    最后回退到目录名提取的 extracted_title。
    """
    aliases: List[str] = []
    if nfo_aliases:
        try:
            parsed = json.loads(nfo_aliases)
            if isinstance(parsed, list):
                aliases = [str(alias) for alias in parsed]
        except (ValueError, TypeError):
            logger.debug("nfo_aliases JSON 解析失败，忽略: %s", nfo_aliases)

    queries: List[str] = []
    for candidate in [nfo_title, nfo_original_title, *aliases, extracted_title]:
        if not candidate:
            continue
        normalized = normalize_media_title(candidate)
        if normalized and normalized not in queries:
            queries.append(normalized)
    return queries


@dataclass
class FileMatchContext:
    file_path: str
    filename: str
    extracted_title: str
    media_type: str
    season: Optional[int]
    episode: Optional[int]
    search_queries: List[str] = field(default_factory=list)


@dataclass
class SubtitleCandidate:
    path: Path
    score: int


class SubtitleCandidateScorer:
    @staticmethod
    def score(path: Path, season: Optional[int] = None, episode: Optional[int] = None) -> int:
        score = 0
        name_upper = path.name.upper()
        name_lower = path.name.lower()

        if season is not None and episode is not None:
            season_episode_pattern = f"S{season:02d}E{episode:02d}"
            if season_episode_pattern in name_upper:
                score += 500
            else:
                other_seasons = re.findall(r"S(\d+)", name_upper)
                if other_seasons and all(int(value) != season for value in other_seasons):
                    score -= 1000
                if f"E{episode:02d}" in name_upper:
                    score += 50
        elif episode is not None and f"E{episode:02d}" in name_upper:
            score += 500

        if path.suffix.lower() in {".ass", ".srt"}:
            score += 50
        if any(token in name_lower for token in ["简体", "chs", "sc", "gb"]):
            score += 100
        if any(token in name_lower for token in ["双语", "bilingual", "eng&chs", "chs&eng"]):
            score += 80
        if any(token in name_lower for token in ["繁体", "cht", "tc", "big5"]) and "简" not in name_lower:
            score -= 30
        return score


class AutoMatchWorkflow:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        agent_factory: Optional[Callable[[], ZimukuAgent]] = None,
    ):
        self._session_factory = session_factory
        self._agent_factory = agent_factory or ZimukuAgent

    def load_file_context(self, file_id: int) -> Optional[FileMatchContext]:
        with self._session_factory() as session:
            file_record = session.get(ScannedFile, file_id)
            if not file_record or not file_record.extracted_title:
                return None

            return FileMatchContext(
                file_path=file_record.file_path,
                filename=file_record.filename,
                extracted_title=file_record.extracted_title,
                media_type=file_record.type,
                season=file_record.season,
                episode=file_record.episode,
                search_queries=build_search_queries(
                    extracted_title=file_record.extracted_title,
                    nfo_title=file_record.nfo_title,
                    nfo_original_title=file_record.nfo_original_title,
                    nfo_aliases=file_record.nfo_aliases,
                ),
            )

    def mark_file_has_subtitle(self, file_id: int):
        with self._session_factory() as session:
            file_record = session.get(ScannedFile, file_id)
            if not file_record:
                return

            file_record.has_subtitle = True
            session.add(file_record)
            session.commit()

    @staticmethod
    def _resolve_episode_context(file_context: FileMatchContext) -> tuple[Optional[int], Optional[int]]:
        if file_context.media_type != "tv":
            return None, None
        return file_context.season, file_context.episode

    async def run_for_file(self, file_id: int) -> bool:
        file_context = self.load_file_context(file_id)
        if not file_context:
            return False

        season, episode = self._resolve_episode_context(file_context)

        with log_context(correlation_id=f"auto-{file_id}", job_name="auto-match", entity_id=str(file_id)):
            logger.info("开始自动匹配: %s", file_context.filename)
            agent = self._agent_factory()
            try:
                results = await self._search_with_fallback_queries(agent, file_context, season, episode)
                if not results:
                    return False

                for attempt_index, best_match in enumerate(results[:5]):
                    logger.info("尝试候选字幕 attempt=%s link=%s", attempt_index + 1, best_match.link)
                    try:
                        matched = await self._try_candidate(
                            agent=agent,
                            file_id=file_id,
                            file_context=file_context,
                            match_link=best_match.link,
                            attempt_index=attempt_index,
                        )
                    except Exception as exc:
                        # 单个候选处理失败（如下载到损坏压缩包）不应中断后续候选重试
                        logger.warning(
                            "候选字幕处理异常 attempt=%s link=%s: %s", attempt_index + 1, best_match.link, exc
                        )
                        continue
                    if matched:
                        logger.info("成功为 %s 匹配字幕", file_context.filename)
                        return True

                logger.error("匹配不到合适字幕")
                return False
            finally:
                await agent.close()

    async def _search_with_fallback_queries(
        self,
        agent: ZimukuAgent,
        file_context: FileMatchContext,
        season: Optional[int],
        episode: Optional[int],
    ):
        """按优先级依次尝试搜索词，返回第一个有结果的搜索词对应的结果列表。"""
        queries = file_context.search_queries or [normalize_media_title(file_context.extracted_title)]
        for query in queries:
            results = await agent.search(query, season=season, episode=episode)
            if results:
                if query != queries[0]:
                    logger.info("回退搜索词命中 query=%s", query)
                return results
            logger.info("自动匹配无搜索结果 query=%s", query)
        return []

    async def _try_candidate(
        self,
        agent: ZimukuAgent,
        file_id: int,
        file_context: FileMatchContext,
        match_link: str,
        attempt_index: int,
    ) -> bool:
        download_links = await agent.get_download_page_links(match_link)
        if not download_links:
            return False

        filename, content = await agent.download_file(download_links, match_link)
        if not filename or not content:
            return False

        tmp_dir = self._build_tmp_dir(file_id, attempt_index)
        try:
            archive_path = tmp_dir / filename
            with open(archive_path, "wb") as file_obj:
                file_obj.write(content)

            season, episode = self._resolve_episode_context(file_context)
            candidates = self._collect_candidates(
                downloaded_path=archive_path,
                season=season,
                episode=episode,
            )
            if not candidates:
                return False

            target_subtitle = candidates[0].path
            video_path = Path(file_context.file_path)
            final_subtitle_path = video_path.parent / f"{video_path.stem}{target_subtitle.suffix}"
            shutil.move(str(target_subtitle), str(final_subtitle_path))
            self.mark_file_has_subtitle(file_id)
            return True
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _build_tmp_dir(file_id: int, attempt_index: int) -> Path:
        tmp_dir = Path(get_temp_path()) / f"auto_{file_id}_{attempt_index}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir

    @classmethod
    def _collect_candidates(
        cls,
        downloaded_path: Path,
        season: Optional[int],
        episode: Optional[int],
    ) -> List[SubtitleCandidate]:
        subtitle_files: List[Path] = []

        if ArchiveManager.is_archive(downloaded_path.name):
            extract_to = downloaded_path.parent / "extracted"
            extract_to.mkdir(exist_ok=True)
            extracted_files = ArchiveManager.extract(str(downloaded_path), str(extract_to))
            subtitle_files.extend(
                Path(path) for path in extracted_files if Path(path).suffix.lower() in SUBTITLE_EXTENSIONS
            )
        elif downloaded_path.suffix.lower() in SUBTITLE_EXTENSIONS:
            subtitle_files.append(downloaded_path)

        candidates = [
            SubtitleCandidate(
                path=path,
                score=SubtitleCandidateScorer.score(path, season=season, episode=episode),
            )
            for path in subtitle_files
        ]
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


@dataclass
class BatchMatchStats:
    """批量补全运行结果"""

    total: int = 0
    matched: int = 0
    failed_files: List[str] = field(default_factory=list)
    titles: List[str] = field(default_factory=list)
    remaining_works: int = 0

    @property
    def failed(self) -> int:
        return len(self.failed_files)


class SeasonMatchWorkflow:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        auto_match_runner: Callable[[int], Awaitable[bool]],
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._session_factory = session_factory
        self._auto_match_runner = auto_match_runner
        self._sleep = sleep_func

    def load_pending_file_ids(self, title: str, season: int) -> List[int]:
        query_title = normalize_media_title(title)

        with self._session_factory() as session:
            statement = select(ScannedFile).where(
                or_(
                    ScannedFile.extracted_title == query_title,
                    ScannedFile.extracted_title == title,
                ),
                ScannedFile.type == "tv",
                ScannedFile.season == season,
                col(ScannedFile.has_subtitle).is_(False),
                col(ScannedFile.allow_no_subtitle).is_(False),
            )
            files = session.exec(statement).all()
            return [file_record.id for file_record in files if file_record.id is not None]

    async def run_for_season(self, title: str, season: int):
        file_ids = self.load_pending_file_ids(title, season)
        if not file_ids:
            logger.debug("未找到匹配的文件: title=%s, season=%s", title, season)
            return

        with log_context(
            correlation_id=f"season-{season}-{len(file_ids)}",
            job_name="season-match",
            entity_id=str(season),
        ):
            logger.debug("季匹配开始: title=%s, season=%s, files=%s", title, season, len(file_ids))
            for file_id in file_ids:
                await self._auto_match_runner(file_id)
                await self._sleep(2)
            logger.debug("季匹配完成: title=%s, season=%s", title, season)


class LibraryMatchWorkflow:
    """全库批量补全：对缺失字幕的作品（剧集/电影）执行自动匹配。

    按 ``max_works`` 限制每次运行处理的作品数量（0 表示不限），避免单次运行请求过多导致封禁。
    作品优先级：Jellyfin 未观看的作品最优先（需启用 Jellyfin 联动且拉取成功），
    其次是有 NFO 元数据的作品，最后按缺字幕文件数降序、标题升序兜底。
    """

    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]],
        auto_match_runner: Callable[[int], Awaitable[bool]],
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_works: int = 0,
        unwatched: Optional[UnwatchedIndex] = None,
    ):
        self._session_factory = session_factory
        self._auto_match_runner = auto_match_runner
        self._sleep = sleep_func
        self._max_works = max_works
        self._unwatched = unwatched

    def load_pending_files(self) -> List[tuple[int, str]]:
        with self._session_factory() as session:
            statement = select(ScannedFile).where(
                col(ScannedFile.has_subtitle).is_(False),
                col(ScannedFile.allow_no_subtitle).is_(False),
            )
            files = session.exec(statement).all()
            return [(file_record.id, file_record.filename) for file_record in files if file_record.id is not None]

    def load_pending_groups(self) -> tuple[dict[str, List[tuple[int, str]]], set[str]]:
        """按作品（规范化标题）分组缺失字幕的文件（跳过允许无字幕的作品）。

        返回 (分组, 含 NFO 元数据的作品标题集合)：任一缺字幕文件带 nfo_title
        或 nfo_original_title 即视为该作品可检索到 NFO 元数据。
        """
        with self._session_factory() as session:
            statement = select(ScannedFile).where(
                col(ScannedFile.has_subtitle).is_(False),
                col(ScannedFile.allow_no_subtitle).is_(False),
            )
            files = session.exec(statement).all()

        groups: dict[str, List[tuple[int, str]]] = {}
        nfo_titles: set[str] = set()
        for file_record in files:
            if file_record.id is None:
                continue
            title = normalize_media_title(file_record.extracted_title or file_record.filename)
            groups.setdefault(title, []).append((file_record.id, file_record.filename))
            if file_record.nfo_title or file_record.nfo_original_title:
                nfo_titles.add(title)
        return groups, nfo_titles

    def _unwatched_titles(self, groups: dict[str, List[tuple[int, str]]]) -> set[str]:
        """返回命中 Jellyfin 未观看索引的作品标题集合（未启用/拉取失败时为空）。"""
        if not self._unwatched:
            return set()
        return {title for title in groups if self._unwatched.matches(title)}

    def select_works(
        self,
        groups: dict[str, List[tuple[int, str]]],
        nfo_titles: set[str],
    ) -> tuple[List[tuple[str, List]], int]:
        """按 Jellyfin 未观看优先 → NFO 元数据优先 → 缺字幕文件数降序（标题升序兜底）选择本次运行的作品，
        返回 (选中项, 剩余作品数)。"""
        unwatched_titles = self._unwatched_titles(groups)
        if unwatched_titles:
            logger.info("Jellyfin 未观看作品优先补全: %s", sorted(unwatched_titles))
        ordered = sorted(
            groups.items(),
            key=lambda item: (
                item[0] not in unwatched_titles,
                item[0] not in nfo_titles,
                -len(item[1]),
                item[0],
            ),
        )
        if self._max_works <= 0:
            return ordered, 0
        return ordered[: self._max_works], max(0, len(ordered) - self._max_works)

    async def run(self) -> BatchMatchStats:
        groups, nfo_titles = self.load_pending_groups()
        selected, remaining = self.select_works(groups, nfo_titles)
        stats = BatchMatchStats(
            total=sum(len(files) for _, files in selected),
            titles=[title for title, _ in selected],
            remaining_works=remaining,
        )
        if not selected:
            logger.debug("批量补全：没有缺失字幕的文件")
            return stats

        with log_context(correlation_id=f"library-{stats.total}", job_name="library-match"):
            logger.info(
                "批量补全开始：作品=%s，共 %s 个缺失字幕文件，剩余 %s 部作品待后续运行",
                stats.titles,
                stats.total,
                remaining,
            )
            for _, files in selected:
                for file_id, filename in files:
                    if await self._auto_match_runner(file_id):
                        stats.matched += 1
                    else:
                        stats.failed_files.append(filename)
                    await self._sleep(2)
            logger.info("批量补全完成：成功 %s / 失败 %s", stats.matched, stats.failed)
        return stats
