from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks

from ..core.config import ConfigManager, SettingKey
from ..core.notifier import FeishuNotifier
from ..services.scheduler_service import scheduler_service
from .schemas import FeishuTestResponse, ScheduleStatusResponse, TaskTriggerResponse

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.get("/status", response_model=ScheduleStatusResponse)
async def get_schedule_status() -> ScheduleStatusResponse:
    """获取定时扫描补字幕的配置与运行状态"""
    next_run = scheduler_service.next_run_time()
    last_run = scheduler_service.last_run
    return ScheduleStatusResponse(
        enabled=ConfigManager.get_bool(SettingKey.SCHEDULE_ENABLED, False),
        cron=ConfigManager.get(SettingKey.SCHEDULE_CRON),
        next_run_time=next_run.isoformat() if next_run else None,
        running=scheduler_service.is_running,
        last_run=asdict(last_run) if last_run else None,
    )


@router.post("/run-now", response_model=TaskTriggerResponse)
async def run_schedule_now(background_tasks: BackgroundTasks) -> TaskTriggerResponse:
    """立即执行一次完整的扫描 + 批量补全 + 通知流程"""
    background_tasks.add_task(scheduler_service.run_now, "manual")
    return TaskTriggerResponse(
        message="Manual scan-and-match task started",
        task_kind="scheduled_scan",
        target="all",
    )


@router.post("/feishu/test", response_model=FeishuTestResponse)
async def send_feishu_test() -> FeishuTestResponse:
    """发送飞书机器人测试通知"""
    notifier = FeishuNotifier()
    if not notifier.configured:
        return FeishuTestResponse(message="飞书 webhook 未配置", delivered=False)
    delivered = await notifier.send_test()
    return FeishuTestResponse(
        message="测试通知已发送" if delivered else "测试通知发送失败，请检查 webhook 与密钥",
        delivered=delivered,
    )
