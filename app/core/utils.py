import os
import re
from pathlib import Path
from typing import Any, Dict

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}
NOISE_TOKENS_PATTERN = r"(?i)(1080p|720p|2160p|4k|bluray|web-dl|x264|x265|hevc|aac).*$"


def parse_media_filename(filename: str) -> Dict[str, Any]:
    """解析文件名：提取标题、年份、季、集"""
    name = os.path.splitext(filename)[0]
    result: Dict[str, Any] = {"extracted_title": name, "year": None, "season": None, "episode": None}

    # 提取季和集 (e.g. S01E02, s1e2, S1.E2)
    se_match = re.search(r"(?i)s(\d+)[._\s-]*e(\d+)", name)
    if se_match:
        result["season"] = int(se_match.group(1))
        result["episode"] = int(se_match.group(2))
        name = name[: se_match.start()].strip()

    # 查找年份 19xx 或 20xx
    match = re.search(r"\b(19\d{2}|20\d{2})\b", name)
    if match:
        result["year"] = match.group(1)
        name = name[: match.start()].strip()

    # 将 ._ 替换为空格并清理常见词
    name = re.sub(r"[\._]", " ", name)
    name = re.sub(NOISE_TOKENS_PATTERN, "", name).strip()
    result["extracted_title"] = name
    return result


def check_has_subtitle(file_path: Path) -> bool:
    """检查是否存在同名字幕文件（支持语言后缀）"""
    video_stem = file_path.stem.lower()
    dir_path = file_path.parent

    try:
        if not dir_path.exists():
            return False
        for subtitle_file in dir_path.iterdir():
            if subtitle_file.is_file() and subtitle_file.suffix.lower() in SUBTITLE_EXTENSIONS:
                sub_stem = subtitle_file.stem.lower()
                # 字幕文件名以视频文件名开头（支持语言后缀如 .简体）
                if sub_stem.startswith(video_stem):
                    return True
    except Exception:
        pass
    return False
