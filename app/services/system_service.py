import os
import shutil
from typing import Any, Dict, List

from sqlmodel import Session, func, select

from ..core.config import get_download_path
from ..core.scraper.agent import (
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MIN_REQUEST_INTERVAL,
    DEFAULT_TIMEOUT,
)
from ..core.subtitle_languages import list_subtitle_languages
from ..db.models import SearchCache, SubtitleTask


class SystemService:
    @staticmethod
    def get_subtitle_languages() -> list[dict[str, str]]:
        return list_subtitle_languages()

    @staticmethod
    def _get_log_file_path() -> str:
        return os.getenv("ZIMUKU_LOG_FILE", "app.log")

    @staticmethod
    def _get_runtime_config() -> Dict[str, Any]:
        def read_float(key: str, default: float) -> float:
            try:
                value = float(os.getenv(key, default))
                return value if value > 0 else default
            except (TypeError, ValueError):
                return default

        def read_int(key: str, default: int) -> int:
            try:
                value = int(os.getenv(key, default))
                return value if value > 0 else default
            except (TypeError, ValueError):
                return default

        return {
            "task_state_backend": "database",
            "scraper": {
                "timeout_seconds": read_float("ZIMUKU_REQUEST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT),
                "max_retries": read_int("ZIMUKU_REQUEST_MAX_RETRIES", DEFAULT_MAX_RETRIES),
                "backoff_seconds": read_float("ZIMUKU_REQUEST_BACKOFF_SECONDS", DEFAULT_BACKOFF_SECONDS),
                "min_interval_seconds": read_float("ZIMUKU_REQUEST_MIN_INTERVAL_SECONDS", DEFAULT_MIN_REQUEST_INTERVAL),
            },
        }

    @staticmethod
    def get_stats(session: Session) -> Dict[str, Any]:
        total_tasks = session.exec(select(func.count()).select_from(SubtitleTask)).one()
        completed_tasks = session.exec(
            select(func.count()).select_from(SubtitleTask).where(SubtitleTask.status == "completed")
        ).one()
        failed_tasks = session.exec(
            select(func.count()).select_from(SubtitleTask).where(SubtitleTask.status == "failed")
        ).one()

        total_cache = session.exec(select(func.count()).select_from(SearchCache)).one()

        storage_path = get_download_path()
        storage_info = {"path": storage_path, "total_size_mb": 0, "free_space_gb": 0}

        if os.path.exists(storage_path):
            total_size = 0
            for dirpath, _, filenames in os.walk(storage_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total_size += os.path.getsize(fp)
            storage_info["total_size_mb"] = round(total_size / (1024 * 1024), 2)

            _, _, free = shutil.disk_usage(storage_path)
            storage_info["free_space_gb"] = round(free / (1024 * 1024 * 1024), 2)

        return {
            "tasks": {
                "total": total_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks,
                "pending": total_tasks - completed_tasks - failed_tasks,
            },
            "cache": {"total_entries": total_cache},
            "storage": storage_info,
            "runtime": SystemService._get_runtime_config(),
        }

    @staticmethod
    def get_logs(lines: int = 100) -> List[str]:
        log_file = SystemService._get_log_file_path()
        if os.path.exists(log_file):
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.readlines()
                    return content[-lines:]
            except Exception as e:
                return [f"Error reading log file: {e}"]
        return ["Log file not found. Ensure logging is configured to write to app.log"]
