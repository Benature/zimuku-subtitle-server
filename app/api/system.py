import logging

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..db.session import get_session
from ..services.system_service import SystemService
from .schemas import SubtitleLanguageResponse

router = APIRouter(prefix="/system", tags=["System"])
logger = logging.getLogger(__name__)


@router.get("/subtitle-languages", response_model=list[SubtitleLanguageResponse])
async def get_subtitle_languages():
    """获取系统支持的字幕语言目录。"""
    return SystemService.get_subtitle_languages()


@router.get("/stats")
async def get_system_stats(session: Session = Depends(get_session)):
    """获取系统统计信息"""
    return SystemService.get_stats(session)


@router.get("/logs")
async def get_recent_logs(lines: int = Query(default=100, ge=1, le=1000)):
    """获取最近的日志记录"""
    return SystemService.get_logs(lines)
