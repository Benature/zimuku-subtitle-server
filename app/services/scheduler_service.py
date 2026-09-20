import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import func, select

from ..core.config import ConfigManager, SettingKey
from ..core.mediaserver import fetch_unwatched_index
from ..core.notifier import FeishuNotifier, ScheduledJobStats
from ..db.models import ScannedFile
from ..db.session import session_scope
from .auto_match_workflow import BatchMatchStats, LibraryMatchWorkflow
from .media_service import MediaService

logger = logging.getLogger(__name__)

SCHEDULED_JOB_ID = "scheduled_scan_and_match"


@dataclass
class ScheduledJobRunSummary:
    """最近一次定时/手动批量任务的运行摘要"""

    started_at: str = ""
    finished_at: str = ""
    trigger: str = "schedule"
    stats: dict = field(default_factory=dict)
    error: Optional[str] = None


class SchedulerService:
    """定时扫描补字幕调度器，封装 APScheduler 并联动配置变更。"""

    def __init__(self):
        self._scheduler = AsyncIOScheduler()
        self._run_lock = asyncio.Lock()
        self._started = False
        self._refcount = 0
        self.last_run: Optional[ScheduledJobRunSummary] = None

    def start(self):
        self._refcount += 1
        if self._started:
            return
        if self._scheduler.state != STATE_STOPPED:
            # 旧实例仍在运行（可能绑定在已失效的事件循环上），尽力关闭后丢弃
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
        # 已使用过的调度器会缓存旧事件循环引用，统一重建以绑定当前事件循环
        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        self._started = True
        self.reload()
        logger.info("定时任务调度器已启动")

    def shutdown(self):
        if self._refcount > 0:
            self._refcount -= 1
        if self._refcount or not self._started:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception as exc:
            logger.warning("关闭定时任务调度器时出现异常: %s", exc)
        self._started = False
        logger.info("定时任务调度器已关闭")

    def reload(self):
        """根据最新配置增删定时任务。"""
        if not self._started:
            return

        enabled = ConfigManager.get_bool(SettingKey.SCHEDULE_ENABLED, False)
        cron = ConfigManager.get(SettingKey.SCHEDULE_CRON)

        if not enabled:
            self._remove_job()
            logger.info("定时扫描补字幕已禁用")
            return

        try:
            trigger = CronTrigger.from_crontab(cron)
        except (ValueError, TypeError) as exc:
            self._remove_job()
            logger.error("定时任务 cron 表达式非法，已移除任务: %s (%s)", cron, exc)
            return

        self._scheduler.add_job(
            self._run_job_safe,
            trigger=trigger,
            id=SCHEDULED_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info("定时扫描补字幕已启用: cron=%s", cron)

    def _remove_job(self):
        if self._scheduler.get_job(SCHEDULED_JOB_ID):
            self._scheduler.remove_job(SCHEDULED_JOB_ID)

    def next_run_time(self) -> Optional[datetime]:
        job = self._scheduler.get_job(SCHEDULED_JOB_ID)
        # 调度器未运行时 job 处于 pending 状态，没有 next_run_time 属性
        return getattr(job, "next_run_time", None) if job else None

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    async def _run_job_safe(self):
        try:
            await self.run_now(trigger="schedule")
        except Exception as exc:
            logger.error("定时扫描补字幕执行异常: %s", exc, exc_info=True)

    async def run_now(self, trigger: str = "manual") -> ScheduledJobRunSummary:
        """执行一次完整的扫描 + 批量补全 + 通知流程，防重入。"""
        if self._run_lock.locked():
            logger.warning("已有扫描补全任务在运行，本次触发被跳过 (trigger=%s)", trigger)
            raise RuntimeError("已有扫描补全任务在运行中")

        async with self._run_lock:
            summary = ScheduledJobRunSummary(started_at=datetime.now().isoformat(timespec="seconds"), trigger=trigger)
            try:
                stats = await self._execute_pipeline()
                summary.stats = asdict(stats)
            except Exception as exc:
                summary.error = str(exc)
                raise
            finally:
                summary.finished_at = datetime.now().isoformat(timespec="seconds")
                self.last_run = summary
            return summary

    async def _execute_pipeline(self) -> ScheduledJobStats:
        stats = ScheduledJobStats()

        await MediaService.run_media_scan_and_match(None)
        stats.scanned_files = self._count_scanned_files()

        # 启用媒体服务器联动时拉取未观看索引（失败返回 None，自动回退原优先级）
        unwatched = await fetch_unwatched_index()

        workflow = LibraryMatchWorkflow(
            session_factory=session_scope,
            auto_match_runner=MediaService.run_auto_match_process,
            max_works=ConfigManager.get_int(SettingKey.SCHEDULE_MAX_WORKS_PER_RUN, 1),
            unwatched=unwatched,
        )
        batch_stats: BatchMatchStats = await workflow.run()
        stats.missing_subtitle = batch_stats.total
        stats.matched = batch_stats.matched
        stats.failed = batch_stats.failed
        stats.failed_files = batch_stats.failed_files
        stats.titles = batch_stats.titles
        stats.remaining_works = batch_stats.remaining_works

        await self._notify(stats)
        return stats

    @staticmethod
    def _count_scanned_files() -> int:
        with session_scope() as session:
            return session.exec(select(func.count()).select_from(ScannedFile)).one()

    @staticmethod
    async def _notify(stats: ScheduledJobStats):
        if not ConfigManager.get_bool(SettingKey.FEISHU_NOTIFY_ENABLED, False):
            return
        notifier = FeishuNotifier()
        if not notifier.configured:
            logger.warning("飞书通知已启用但未配置 webhook，跳过发送")
            return
        await notifier.send_scheduled_report(stats)


scheduler_service = SchedulerService()
