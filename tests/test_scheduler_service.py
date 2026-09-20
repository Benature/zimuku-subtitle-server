from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, delete

from app.core.config import SettingKey
from app.core.mediaserver import UnwatchedIndex
from app.core.notifier import ScheduledJobStats
from app.db.models import MediaPath, ScannedFile, SubtitleTask
from app.db.session import create_db_and_tables, engine
from app.services.auto_match_workflow import BatchMatchStats
from app.services.scheduler_service import SCHEDULED_JOB_ID, SchedulerService


@pytest.fixture(autouse=True)
def clean_app_db():
    create_db_and_tables()
    with Session(engine) as session:
        session.exec(delete(ScannedFile))
        session.exec(delete(MediaPath))
        session.exec(delete(SubtitleTask))
        session.commit()


@pytest.fixture(name="service")
def service_fixture():
    service = SchedulerService()
    service._started = True
    yield service


def _config_map(enabled: str, cron: str):
    def _get(key, default=None):
        values = {
            SettingKey.SCHEDULE_ENABLED: enabled,
            SettingKey.SCHEDULE_CRON: cron,
        }
        return values.get(key, default if default is not None else "")

    return _get


def test_reload_adds_job_when_enabled(service):
    with patch("app.services.scheduler_service.ConfigManager") as config_mock:
        config_mock.get_bool.return_value = True
        config_mock.get.side_effect = _config_map("true", "0 3 * * *")
        service.reload()

    assert service._scheduler.get_job(SCHEDULED_JOB_ID) is not None
    # 调度器未启动时 job 处于 pending 状态，next_run_time 为空
    assert service.next_run_time() is None


def test_reload_removes_job_when_disabled(service):
    with patch("app.services.scheduler_service.ConfigManager") as config_mock:
        config_mock.get_bool.return_value = True
        config_mock.get.side_effect = _config_map("true", "0 3 * * *")
        service.reload()

    with patch("app.services.scheduler_service.ConfigManager") as config_mock:
        config_mock.get_bool.return_value = False
        config_mock.get.side_effect = _config_map("false", "0 3 * * *")
        service.reload()

    assert service._scheduler.get_job(SCHEDULED_JOB_ID) is None


def test_reload_removes_job_on_invalid_cron(service):
    with patch("app.services.scheduler_service.ConfigManager") as config_mock:
        config_mock.get_bool.return_value = True
        config_mock.get.side_effect = _config_map("true", "not-a-cron")
        service.reload()

    assert service._scheduler.get_job(SCHEDULED_JOB_ID) is None


@pytest.mark.anyio
async def test_run_now_rejects_concurrent_execution(service):
    await service._run_lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="运行中"):
            await service.run_now()
    finally:
        service._run_lock.release()


@pytest.mark.anyio
async def test_execute_pipeline_orchestrates_scan_match_notify(service):
    batch_stats = BatchMatchStats(total=3, matched=2, failed_files=["a.mkv"], titles=["Show A"], remaining_works=4)

    with (
        patch(
            "app.services.scheduler_service.MediaService.run_media_scan_and_match",
            new=AsyncMock(),
        ) as scan_mock,
        patch("app.services.scheduler_service.SchedulerService._count_scanned_files", return_value=10),
        patch("app.services.scheduler_service.LibraryMatchWorkflow") as workflow_cls,
        patch(
            "app.services.scheduler_service.SchedulerService._notify",
            new=AsyncMock(),
        ) as notify_mock,
    ):
        workflow_cls.return_value.run = AsyncMock(return_value=batch_stats)
        stats = await service._execute_pipeline()

    scan_mock.assert_awaited_once()
    notify_mock.assert_awaited_once()
    assert stats.scanned_files == 10
    assert stats.missing_subtitle == 3
    assert stats.matched == 2
    assert stats.failed_files == ["a.mkv"]
    assert stats.titles == ["Show A"]
    assert stats.remaining_works == 4


@pytest.mark.anyio
async def test_execute_pipeline_passes_unwatched_index_to_workflow(service):
    index = UnwatchedIndex(titles={"show a"}, item_count=1)

    with (
        patch(
            "app.services.scheduler_service.MediaService.run_media_scan_and_match",
            new=AsyncMock(),
        ),
        patch("app.services.scheduler_service.SchedulerService._count_scanned_files", return_value=0),
        patch(
            "app.services.scheduler_service.fetch_unwatched_index",
            new=AsyncMock(return_value=index),
        ),
        patch("app.services.scheduler_service.LibraryMatchWorkflow") as workflow_cls,
        patch(
            "app.services.scheduler_service.SchedulerService._notify",
            new=AsyncMock(),
        ),
    ):
        workflow_cls.return_value.run = AsyncMock(return_value=BatchMatchStats())
        await service._execute_pipeline()

    assert workflow_cls.call_args.kwargs["unwatched"] is index


@pytest.mark.anyio
async def test_notify_skips_when_disabled():
    with patch("app.services.scheduler_service.ConfigManager") as config_mock:
        config_mock.get_bool.return_value = False
        with patch("app.services.scheduler_service.FeishuNotifier") as notifier_cls:
            await SchedulerService._notify(ScheduledJobStats())
            notifier_cls.assert_not_called()


@pytest.mark.anyio
async def test_notify_skips_when_webhook_missing():
    notifier_mock = AsyncMock()
    notifier_mock.configured = False

    with (
        patch("app.services.scheduler_service.ConfigManager") as config_mock,
        patch("app.services.scheduler_service.FeishuNotifier", return_value=notifier_mock),
    ):
        config_mock.get_bool.return_value = True
        await SchedulerService._notify(ScheduledJobStats())

    notifier_mock.send_scheduled_report.assert_not_called()


@pytest.mark.anyio
async def test_notify_fetches_backdrops_and_passes_images_to_report():
    notifier_mock = AsyncMock()
    notifier_mock.configured = True
    notifier_mock.image_upload_configured = True
    stats = ScheduledJobStats(matched=1, titles=["Show A"])
    fetch_mock = AsyncMock(return_value={"Show A": b"img-bytes"})

    with (
        patch("app.services.scheduler_service.ConfigManager") as config_mock,
        patch("app.services.scheduler_service.FeishuNotifier", return_value=notifier_mock),
        patch("app.services.scheduler_service.fetch_backdrops", fetch_mock),
    ):
        config_mock.get_bool.return_value = True
        await SchedulerService._notify(stats)

    fetch_mock.assert_awaited_once_with(["Show A"])
    notifier_mock.send_scheduled_report.assert_awaited_once_with(stats, images={"Show A": b"img-bytes"})


@pytest.mark.anyio
async def test_notify_skips_backdrop_fetch_without_app_credentials():
    notifier_mock = AsyncMock()
    notifier_mock.configured = True
    notifier_mock.image_upload_configured = False
    stats = ScheduledJobStats(matched=1, titles=["Show A"])
    fetch_mock = AsyncMock(return_value={})

    with (
        patch("app.services.scheduler_service.ConfigManager") as config_mock,
        patch("app.services.scheduler_service.FeishuNotifier", return_value=notifier_mock),
        patch("app.services.scheduler_service.fetch_backdrops", fetch_mock),
    ):
        config_mock.get_bool.return_value = True
        await SchedulerService._notify(stats)

    fetch_mock.assert_not_called()
    notifier_mock.send_scheduled_report.assert_awaited_once_with(stats, images={})


@pytest.mark.anyio
async def test_run_now_records_last_run_summary(service):
    stats = ScheduledJobStats(scanned_files=5, missing_subtitle=1, matched=1)

    with patch.object(SchedulerService, "_execute_pipeline", new=AsyncMock(return_value=stats)):
        summary = await service.run_now(trigger="manual")

    assert summary.trigger == "manual"
    assert summary.error is None
    assert summary.stats["matched"] == 1
    assert service.last_run is summary
