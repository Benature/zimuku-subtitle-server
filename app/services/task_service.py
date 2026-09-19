import logging
import os
import shutil
from datetime import datetime
from typing import List, Optional, Tuple

from sqlmodel import Session, col, func, select

from ..core.config import ConfigManager, SettingKey
from ..core.observability import log_context
from ..db.models import ScannedFile, SubtitleTask
from ..db.session import session_scope
from .download_workflow import DownloadWorkflow, DownloadWorkflowError, SubtitleMover
from .subtitle_align_service import SubtitleAlignService

logger = logging.getLogger(__name__)


class TaskService:
    @staticmethod
    def _build_list_statement(status: Optional[str] = None):
        statement = select(SubtitleTask)
        if status:
            statement = statement.where(SubtitleTask.status == status)
        return statement

    @staticmethod
    def _save_task(session: Session, task: SubtitleTask) -> None:
        task.updated_at = datetime.now()
        session.add(task)
        session.commit()

    @staticmethod
    def create_task(
        session: Session,
        title: str,
        source_url: str,
        target_path: Optional[str] = None,
        target_type: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        language: Optional[str] = None,
        file_id: Optional[int] = None,
    ) -> SubtitleTask:
        resolved_title = title
        resolved_target_path = target_path
        resolved_target_type = target_type
        resolved_season = season
        resolved_episode = episode

        if file_id is not None:
            media = session.get(ScannedFile, file_id)
            if media:
                if not resolved_target_path:
                    resolved_target_path = media.file_path
                if not resolved_target_type:
                    resolved_target_type = media.type
                if resolved_season is None:
                    resolved_season = media.season
                if resolved_episode is None:
                    resolved_episode = media.episode
                if not resolved_title:
                    resolved_title = media.filename

        task = SubtitleTask(
            title=resolved_title,
            source_url=source_url,
            status="pending",
            target_path=resolved_target_path,
            target_type=resolved_target_type,
            season=resolved_season,
            episode=resolved_episode,
            language=language,
            file_id=file_id,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    @staticmethod
    def get_task(session: Session, task_id: int) -> Optional[SubtitleTask]:
        return session.get(SubtitleTask, task_id)

    @staticmethod
    def list_tasks(
        session: Session, offset: int = 0, limit: int = 10, status: Optional[str] = None
    ) -> Tuple[List[SubtitleTask], int]:
        statement = TaskService._build_list_statement(status).order_by(col(SubtitleTask.created_at).desc())
        count_statement = select(func.count()).select_from(TaskService._build_list_statement(status).subquery())
        total = session.exec(count_statement).one()

        items = list(session.exec(statement.offset(offset).limit(limit)).all())
        return items, total

    @staticmethod
    def delete_task(session: Session, task_id: int, delete_files: bool = False) -> bool:
        task = session.get(SubtitleTask, task_id)
        if not task:
            return False

        if delete_files and task.save_path and os.path.exists(task.save_path):
            try:
                if os.path.isdir(task.save_path):
                    shutil.rmtree(task.save_path)
                else:
                    os.remove(task.save_path)
            except Exception as e:
                logger.error(f"删除任务关联文件失败: {e}")

        session.delete(task)
        session.commit()
        return True

    @staticmethod
    def retry_task(session: Session, task_id: int) -> Optional[SubtitleTask]:
        task = session.get(SubtitleTask, task_id)
        if not task or task.status != "failed":
            return None

        task.status = "pending"
        task.error_msg = None
        TaskService._save_task(session, task)
        session.refresh(task)
        return task

    @staticmethod
    def clear_completed(session: Session) -> int:
        statement = select(SubtitleTask).where(SubtitleTask.status == "completed")
        tasks = list(session.exec(statement).all())
        count = len(tasks)
        for task in tasks:
            session.delete(task)
        session.commit()
        return count

    @staticmethod
    def _mark_task_started(session: Session, task: SubtitleTask):
        task.status = "downloading"
        task.error_msg = None
        TaskService._save_task(session, task)

    @staticmethod
    def _finalize_success(task: SubtitleTask, filename: str, save_path: str):
        task.filename = filename
        task.save_path = save_path
        task.status = "completed"
        task.error_msg = None

    @staticmethod
    def _finalize_failure(task: SubtitleTask, error: Exception):
        task.status = "failed"
        task.error_msg = str(error)

    @staticmethod
    async def run_download_task(task_id: int):
        with session_scope() as session:
            task = session.get(SubtitleTask, task_id)
            if not task:
                return
            workflow = DownloadWorkflow()
            TaskService._mark_task_started(session, task)
            task_snapshot = SubtitleTask.model_validate(task)

        final_filename: Optional[str] = None
        final_save_path: Optional[str] = None
        final_error: Optional[Exception] = None

        with log_context(correlation_id=f"task-{task_id}", job_name="download", entity_id=str(task_id)):
            try:
                logger.info("task %s: starting download workflow", task_id)
                artifact = await workflow.execute(task_snapshot)
                final_filename = artifact.filename
                final_save_path = artifact.save_path

                if task_snapshot.target_path:
                    logger.info("task %s: moving subtitle into target path", task_id)
                    final_save_path = SubtitleMover.move(task_snapshot, artifact.save_path)

                # 下载完成后按配置自动执行音轨对齐（失败不影响任务结果）
                if ConfigManager.get_bool(SettingKey.AUTO_ALIGN_AFTER_DOWNLOAD, True):
                    aligned = await SubtitleAlignService.auto_align_for_task(task_snapshot, final_save_path)
                    if aligned:
                        logger.info("task %s: auto subtitle alignment applied", task_id)
            except (DownloadWorkflowError, OSError) as exc:
                logger.error("task %s failed: %s", task_id, exc)
                final_error = exc
            except Exception as exc:
                logger.exception("task %s failed with unexpected error", task_id)
                final_error = exc
            finally:
                try:
                    await workflow.close()
                finally:
                    with session_scope() as session:
                        task = session.get(SubtitleTask, task_id)
                        if not task:
                            return

                        if final_error is None and final_filename and final_save_path:
                            TaskService._finalize_success(task, final_filename, final_save_path)
                            # 关联更新 ScannedFile 状态
                            media_record = None
                            if task.file_id:
                                media_record = session.get(ScannedFile, task.file_id)
                            if not media_record and task.target_path:
                                media_record = session.exec(
                                    select(ScannedFile).where(ScannedFile.file_path == task.target_path)
                                ).first()
                            if media_record:
                                media_record.has_subtitle = True
                                session.add(media_record)
                                logger.info(
                                    "task %s: marked scanned_file %s has_subtitle=True",
                                    task.id,
                                    media_record.id,
                                )
                        elif final_error is not None:
                            TaskService._finalize_failure(task, final_error)

                        TaskService._save_task(session, task)
