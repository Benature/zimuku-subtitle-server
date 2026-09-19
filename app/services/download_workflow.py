import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..core.archive import ArchiveManager
from ..core.config import get_download_path
from ..core.scraper import ZimukuAgent
from ..core.subtitle_detector import SubtitleDetector
from ..core.subtitle_languages import SUBTITLE_LANGUAGE_BY_CODE
from ..db.models import SubtitleTask

logger = logging.getLogger(__name__)

SUBTITLE_EXTENSIONS = (".srt", ".ass", ".ssa", ".sub", ".sup")


class DownloadWorkflowError(Exception):
    """下载流程中可预期的失败。"""


@dataclass
class DownloadArtifact:
    filename: str
    file_path: str
    save_path: str
    extracted_files: List[str]


@dataclass
class SubtitlePlacement:
    source_path: str
    destination_path: str


class SubtitleFileSelector:
    @staticmethod
    def collect_candidates(base_path: str) -> List[str]:
        if os.path.isdir(base_path):
            subtitle_files = []
            for root, _, files in os.walk(base_path):
                for filename in files:
                    if filename.lower().endswith(SUBTITLE_EXTENSIONS):
                        subtitle_files.append(os.path.join(root, filename))
            return sorted(subtitle_files)

        if base_path.lower().endswith(SUBTITLE_EXTENSIONS):
            return [base_path]
        return []

    @classmethod
    def select_best(
        cls,
        base_path: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> str:
        subtitle_candidates = cls.collect_candidates(base_path)
        if not subtitle_candidates:
            raise DownloadWorkflowError("下载结果中未找到可用字幕文件")
        if len(subtitle_candidates) == 1:
            return subtitle_candidates[0]

        # 如果下载包包含多集，且指定了集数，优先挑选匹配当前集数的字幕文件
        if episode is not None:
            ep_patterns = []
            if season is not None:
                ep_patterns.append(re.compile(rf"(?i)s0?{season}[._\s-]*e0?{episode}\b"))
            ep_patterns.extend(
                [
                    re.compile(rf"(?i)e0?{episode}\b"),
                    re.compile(rf"(?i)ep0?{episode}\b"),
                    re.compile(rf"(?i)第0?{episode}集"),
                    re.compile(rf"(?i)[._\s-]0?{episode}[._\s-]"),
                ]
            )
            for pattern in ep_patterns:
                matched = [c for c in subtitle_candidates if pattern.search(Path(c).name)]
                if matched:
                    return cls._pick_preferred(matched)

        return cls._pick_preferred(subtitle_candidates)

    @staticmethod
    def _pick_preferred(candidates: List[str]) -> str:
        def score(path_str: str) -> int:
            ext = Path(path_str).suffix.lower()
            s = 0
            if ext == ".ass":
                s += 20
            elif ext == ".ssa":
                s += 15
            elif ext == ".srt":
                s += 10
            name_lower = Path(path_str).name.lower()
            if any(k in name_lower for k in ["zh-cn-en", "chs&eng", "chs.eng", "双语", "简英"]):
                s += 10
            elif any(k in name_lower for k in ["zh-cn", "chs", "gb", "简体"]):
                s += 5
            return s

        return max(candidates, key=score)


class SubtitleMover:
    VIDEO_EXTENSIONS = (
        ".mp4",
        ".mkv",
        ".avi",
        ".wmv",
        ".mov",
        ".ts",
        ".flv",
        ".webm",
        ".m4v",
    )

    @classmethod
    def resolve_target_directory(cls, task: SubtitleTask) -> Optional[str]:
        if not task.target_path:
            return None
        target_p = Path(task.target_path)
        # 如果 target_path 是已有文件或以视频扩展名结尾，返回其所在目录
        if target_p.suffix.lower() in cls.VIDEO_EXTENSIONS or target_p.is_file():
            return str(target_p.parent)
        if task.target_type == "movie" and target_p.suffix:
            return str(target_p.parent)
        return str(target_p)

    @classmethod
    def find_video_basename(cls, task: SubtitleTask, target_dir: str) -> Optional[str]:
        if not task.target_path:
            return None

        target_p = Path(task.target_path)
        # 优先规则：若 target_path 本身就是视频文件，直接使用其 stem 作为视频基准名
        if target_p.suffix.lower() in cls.VIDEO_EXTENSIONS or target_p.is_file():
            return target_p.stem

        if not os.path.isdir(target_dir):
            return None

        try:
            files = os.listdir(target_dir)
        except OSError:
            return None

        video_files = [f for f in files if Path(f).suffix.lower() in cls.VIDEO_EXTENSIONS]
        if not video_files:
            return None

        # 剧集：按季和集查找匹配文件
        if task.target_type == "tv" and task.episode is not None:
            ep = task.episode
            se = task.season
            patterns = []
            if se is not None:
                patterns.append(re.compile(rf"(?i)s0?{se}[._\s-]*e0?{ep}\b"))
            patterns.extend(
                [
                    re.compile(rf"(?i)e0?{ep}\b"),
                    re.compile(rf"(?i)ep0?{ep}\b"),
                    re.compile(rf"(?i)第0?{ep}集"),
                    re.compile(rf"(?i)[._\s-]0?{ep}[._\s-]"),
                ]
            )
            for pattern in patterns:
                for vf in video_files:
                    if pattern.search(vf):
                        return Path(vf).stem

        # 若只有一个视频文件，直接匹配
        if len(video_files) == 1:
            return Path(video_files[0]).stem

        # 电影：按任务标题模糊查找
        if task.target_type == "movie" and task.title:
            title_lower = task.title.lower()
            for vf in video_files:
                if title_lower in vf.lower():
                    return Path(vf).stem

        return None

    @classmethod
    def resolve_language_tag(cls, language_hint: Optional[str], source_path: str) -> Optional[str]:
        if language_hint:
            lang_def = SUBTITLE_LANGUAGE_BY_CODE.get(language_hint)
            if lang_def:
                return lang_def.filename_tag
            tag_map = {
                "简英双语": "zh-CN-en",
                "双语": "zh-CN-en",
                "简体中文": "zh-CN",
                "简体": "zh-CN",
                "繁体中文": "zh-TW",
                "繁体": "zh-TW",
                "英语": "en",
                "英文": "en",
            }
            if language_hint in tag_map:
                return tag_map[language_hint]
            return language_hint

        # 自动通过文件内容或文件名分析语言
        try:
            analysis = SubtitleDetector.analyze_file(Path(source_path))
            if analysis.is_bilingual:
                return "zh-CN-en"
            if analysis.detected_language and analysis.detected_language != "unknown":
                lang_def = SUBTITLE_LANGUAGE_BY_CODE.get(analysis.detected_language)
                return lang_def.filename_tag if lang_def else analysis.detected_language
        except Exception:
            pass

        return None

    @classmethod
    def build_destination_path(cls, task: SubtitleTask, video_basename: str, source_path: str, target_dir: str) -> str:
        ext = Path(source_path).suffix
        lang_tag = cls.resolve_language_tag(task.language, source_path)
        base_name = f"{video_basename}.{lang_tag}" if lang_tag else video_basename

        target_file = Path(target_dir) / f"{base_name}{ext}"
        if not target_file.exists():
            return str(target_file)

        # 避免覆盖已有文件，追加序号
        index = 2
        while True:
            candidate = Path(target_dir) / f"{base_name}.{index}{ext}"
            if not candidate.exists():
                return str(candidate)
            index += 1

    @classmethod
    def plan_move(cls, task: SubtitleTask, save_path: str) -> SubtitlePlacement:
        target_dir = cls.resolve_target_directory(task)
        if not target_dir:
            raise DownloadWorkflowError("未配置目标目录")

        video_basename = cls.find_video_basename(task, target_dir)
        if not video_basename:
            raise DownloadWorkflowError(f"无法从 target_path 提取视频文件名: {task.target_path}")

        source_path = SubtitleFileSelector.select_best(save_path, season=task.season, episode=task.episode)
        destination_path = cls.build_destination_path(task, video_basename, source_path, target_dir)
        return SubtitlePlacement(source_path=source_path, destination_path=destination_path)

    @classmethod
    def move(cls, task: SubtitleTask, save_path: str) -> str:
        placement = cls.plan_move(task, save_path)
        shutil.move(placement.source_path, placement.destination_path)
        logger.info("task %s: subtitle moved to %s", task.id, placement.destination_path)
        return placement.destination_path


class DownloadWorkflow:
    def __init__(self, agent: Optional[ZimukuAgent] = None):
        self.agent = agent or ZimukuAgent()

    async def execute(self, task: SubtitleTask) -> DownloadArtifact:
        logger.info("task %s: resolving download links", task.id)
        download_links = await self.agent.get_download_page_links(task.source_url)
        if not download_links:
            raise DownloadWorkflowError("未能提取下载链接")

        logger.info("task %s: downloading remote file", task.id)
        filename, content = await self.agent.download_file(download_links, task.source_url)
        if not filename or not content:
            raise DownloadWorkflowError("下载失败，内容为空")

        file_path = self.persist_download(filename, content)
        save_path, extracted_files = self.prepare_local_artifact(file_path, filename)
        return DownloadArtifact(
            filename=filename,
            file_path=file_path,
            save_path=save_path,
            extracted_files=extracted_files,
        )

    @staticmethod
    def get_storage_path() -> str:
        return get_download_path()

    @classmethod
    def persist_download(cls, filename: str, content: bytes) -> str:
        storage_path = cls.get_storage_path()
        os.makedirs(storage_path, exist_ok=True)
        file_path = os.path.join(storage_path, filename)
        with open(file_path, "wb") as file_obj:
            file_obj.write(content)
        logger.info("download saved to %s", file_path)
        return file_path

    @staticmethod
    def prepare_local_artifact(file_path: str, filename: str) -> tuple[str, List[str]]:
        if ArchiveManager.is_archive(filename):
            extract_to = os.path.join(os.path.dirname(file_path), os.path.splitext(filename)[0])
            extracted_files = ArchiveManager.extract(file_path, extract_to)
            logger.info("archive extracted to %s (%s files)", extract_to, len(extracted_files))
            return extract_to, extracted_files

        return file_path, [file_path]

    async def close(self):
        await self.agent.close()
