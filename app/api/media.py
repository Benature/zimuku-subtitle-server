from typing import List, Literal, Optional, TypeVar

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query
from fastapi.responses import FileResponse
from sqlmodel import Session

from ..db.models import MediaPath, ScannedFile, SubtitleTask
from ..db.session import get_session
from ..services.media_service import MediaService, global_task_status
from ..services.metadata_service import MetadataService
from ..services.subtitle_align_service import SubtitleAlignService
from ..services.subtitle_inspection_service import SubtitleInspectionService, get_subtitle_summary
from ..services.subtitle_trash_service import SubtitleTrashService
from ..services.task_service import TaskService
from .errors import raise_for_service_error
from .schemas import (
    ActionResponse,
    AlignerStatusResponse,
    ExistingSubtitleResponse,
    FileSubtitleDownloadRequest,
    MediaListResponse,
    MediaMetadataResponse,
    SeasonMatchRequest,
    SubtitleAlignmentCheckRequest,
    SubtitleAlignmentCheckResponse,
    SubtitleAlignRequest,
    SubtitleAlignResponse,
    SubtitleContentResponse,
    SubtitleRestoreRequest,
    SubtitleSummaryResponse,
    SubtitleTrashItem,
    SubtitleTrashListResponse,
    SubtitleTrashPurgeRequest,
    SubtitleTrashPurgeResponse,
    SubtitleTrashRequest,
    SubtitleTrashResponse,
    SubtitleTrashRestoreRequest,
    SubtitleTrashRestoreResponse,
    TaskTriggerResponse,
)

router = APIRouter(prefix="/media", tags=["Media"])
T = TypeVar("T")


def _build_trigger_response(message: str, task_kind: str, target: Optional[str] = None) -> TaskTriggerResponse:
    return TaskTriggerResponse(message=message, task_kind=task_kind, target=target)


def _require_resource(resource: T | None, detail: str) -> T:
    if resource is None:
        raise_for_service_error(LookupError(detail))

    return resource


@router.get("/task-status")
async def get_task_status() -> dict:
    """获取当前的后台任务状态"""
    return global_task_status.to_dict()


@router.get("/paths", response_model=List[MediaPath])
async def list_media_paths(session: Session = Depends(get_session)) -> List[MediaPath]:
    """获取所有媒体库扫描路径"""
    return MediaService.list_paths(session)


@router.post("/paths", response_model=MediaPath)
async def add_media_path(
    path: str,
    path_type: str = Query(default="movie", pattern="^(movie|tv)$"),
    session: Session = Depends(get_session),
) -> MediaPath:
    """添加媒体库扫描路径"""
    try:
        return MediaService.add_path(session, path, path_type)
    except Exception as exc:
        raise_for_service_error(exc)


@router.delete("/paths/{path_id}", response_model=ActionResponse)
async def delete_media_path(path_id: int, session: Session = Depends(get_session)) -> ActionResponse:
    """删除媒体库扫描路径"""
    success = MediaService.delete_path(session, path_id)
    if not success:
        raise_for_service_error(LookupError("Path not found"))
    return ActionResponse(message=f"Path {path_id} and its associated files deleted")


@router.patch("/paths/{path_id}", response_model=MediaPath)
async def update_media_path(
    path_id: int,
    enabled: Optional[bool] = None,
    path_type: Optional[str] = Query(default=None, pattern="^(movie|tv)$"),
    session: Session = Depends(get_session),
) -> MediaPath:
    """更新媒体库扫描路径配置"""
    updated = MediaService.update_path(session, path_id, enabled, path_type)
    if not updated:
        raise_for_service_error(LookupError("Path not found"))
    return updated


@router.get("/files", response_model=List[ScannedFile])
async def list_scanned_files(
    path_type: Optional[str] = Query(default=None, pattern="^(movie|tv)$"),
    offset: int = Query(default=0, ge=0),
    limit: Optional[int] = Query(default=None, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> List[ScannedFile]:
    """获取已扫描的媒体文件列表"""
    return MediaService.list_files_paginated(session, path_type, offset, limit)


@router.get("/subtitle-summary", response_model=dict[int, SubtitleSummaryResponse])
async def get_media_subtitle_summary(
    media_type: Literal["movie", "tv"] = Query(default="tv"),
    session: Session = Depends(get_session),
) -> dict[int, SubtitleSummaryResponse]:
    """按媒体文件汇总字幕信息（对齐状态 + 语言列表，{file_id: summary}），供卡片墙展示。"""
    summary = get_subtitle_summary(session, media_type)
    return {file_id: SubtitleSummaryResponse(**info.to_dict()) for file_id, info in summary.items()}


@router.get("/library", response_model=MediaListResponse)
async def list_media_library(
    level: Literal["movie", "show", "season", "episode"] = Query(default="show"),
    media_type: Optional[Literal["movie", "tv"]] = Query(default=None),
    query: Optional[str] = Query(default=None, min_length=1),
    title: Optional[str] = Query(default=None, min_length=1),
    season: Optional[int] = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> MediaListResponse:
    """按电影、剧、季或集聚合媒体库，并支持元数据模糊检索。"""
    try:
        items, total = MediaService.list_media_paginated(
            session,
            level=level,
            media_type=media_type,
            query=query,
            title=title,
            season=season,
            offset=offset,
            limit=limit,
        )
    except ValueError as exc:
        raise_for_service_error(exc)
    return MediaListResponse(total=total, offset=offset, limit=limit, items=items)


@router.post("/files/{file_id}/auto-match", response_model=TaskTriggerResponse)
async def auto_match_single_file(
    file_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
) -> TaskTriggerResponse:
    """针对单个视频文件触发全自动搜索、下载与归档逻辑"""
    file_record = _require_resource(MediaService.get_file(session, file_id), "File not found")

    background_tasks.add_task(MediaService.run_auto_match_process, file_id)
    return _build_trigger_response(
        message=f"Full auto-match process for '{file_record.filename}' started",
        task_kind="auto_match",
        target=str(file_id),
    )


@router.post("/tv/match-season", response_model=TaskTriggerResponse)
async def match_tv_season(
    background_tasks: BackgroundTasks,
    payload: Optional[SeasonMatchRequest] = Body(default=None),
    title: Optional[str] = Query(default=None, min_length=1),
    season: Optional[int] = Query(default=None, ge=1),
) -> TaskTriggerResponse:
    """触发特定剧集的特定季全自动补全字幕"""
    try:
        request = payload or SeasonMatchRequest(title=title or "", season=season or 0)
    except Exception as exc:
        raise_for_service_error(exc)
    background_tasks.add_task(MediaService.run_season_match_process, request.title, request.season)
    return _build_trigger_response(
        message=f"Matching process for '{request.title}' Season {request.season} started",
        task_kind="season_match",
        target=f"{request.title}:S{request.season:02d}",
    )


@router.post("/match", response_model=TaskTriggerResponse)
async def trigger_match(
    background_tasks: BackgroundTasks,
    path_type: Optional[str] = Query(default=None, pattern="^(movie|tv)$"),
    session: Session = Depends(get_session),
) -> TaskTriggerResponse:
    """手动刷新媒体库列表，不执行字幕搜索、下载或移动。"""
    background_tasks.add_task(MediaService.run_media_scan_and_match, path_type)
    return _build_trigger_response(
        message=f"Media library refresh task ({path_type or 'all'}) started",
        task_kind="media_scan",
        target=path_type or "all",
    )


@router.get("/metadata/{file_id}", response_model=MediaMetadataResponse)
async def get_file_metadata(file_id: int, session: Session = Depends(get_session)) -> MediaMetadataResponse:
    """获取媒体文件的元数据（NFO、海报、TXT）。"""
    try:
        return MediaMetadataResponse.model_validate(MetadataService.get_file_metadata(session, file_id))
    except Exception as exc:
        raise_for_service_error(exc)


@router.get("/poster")
async def get_poster(
    path: str = Query(..., description="URL-encoded relative poster path"), session: Session = Depends(get_session)
):
    """服务海报图片。"""
    try:
        poster_path, media_type = MetadataService.resolve_poster(session, path)
    except Exception as exc:
        raise_for_service_error(exc)
    return FileResponse(poster_path, media_type=media_type)


@router.get("/files/{file_id}/subtitles", response_model=List[ExistingSubtitleResponse])
async def get_media_subtitles(file_id: int, session: Session = Depends(get_session)) -> List[ExistingSubtitleResponse]:
    """获取指定媒体文件的已有字幕列表及其实际语言检测分析。"""
    try:
        subtitles = SubtitleInspectionService.get_existing_subtitles(session, file_id)
        return [ExistingSubtitleResponse.model_validate(sub.to_dict()) for sub in subtitles]
    except Exception as exc:
        raise_for_service_error(exc)


@router.get("/files/{file_id}/subtitles/content", response_model=SubtitleContentResponse)
async def get_media_subtitle_content(
    file_id: int,
    filename: Optional[str] = Query(default=None, description="字幕文件名，单字幕时可省略"),
    max_lines: int = Query(default=100, ge=0, le=2000, description="读取最大行数/对白数"),
    clean_text: bool = Query(default=True, description="是否清洗为纯对白文本，False 返回原始字幕行"),
    session: Session = Depends(get_session),
) -> SubtitleContentResponse:
    """读取指定媒体文件的已有字幕内容并进行语言分析。"""
    try:
        result = SubtitleInspectionService.read_subtitle_content(
            session,
            file_id=file_id,
            filename=filename,
            max_lines=max_lines,
            clean_text=clean_text,
        )
        return SubtitleContentResponse.model_validate(result.to_dict())
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/files/{file_id}/download-subtitle", response_model=SubtitleTask)
async def download_subtitle_for_file(
    file_id: int,
    payload: FileSubtitleDownloadRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> SubtitleTask:
    """为指定媒体文件创建字幕下载任务并自动关联归档。"""
    media = _require_resource(session.get(ScannedFile, file_id), f"Media file {file_id} not found")
    try:
        task = TaskService.create_task(
            session,
            title=payload.title or media.filename,
            source_url=payload.source_url,
            language=payload.language,
            file_id=file_id,
        )
    except Exception as exc:
        raise_for_service_error(exc)

    if task.id is None:
        raise_for_service_error(RuntimeError("Task ID missing after persistence"))

    background_tasks.add_task(TaskService.run_download_task, task.id)
    return task


@router.get("/aligner/status", response_model=AlignerStatusResponse)
async def get_aligner_status() -> AlignerStatusResponse:
    """获取音轨对齐工具组件的就绪状态"""
    return SubtitleAlignService.get_status()


@router.post("/files/{file_id}/align-subtitle", response_model=SubtitleAlignResponse)
async def align_media_subtitle(
    file_id: int,
    payload: Optional[SubtitleAlignRequest] = Body(default=None),
    session: Session = Depends(get_session),
) -> SubtitleAlignResponse:
    """对指定媒体文件的字幕执行音轨对齐"""
    try:
        filename = payload.filename if payload else None
        split_penalty = payload.split_penalty if payload else 7.0
        return await SubtitleAlignService.align_media_subtitle(
            session=session,
            file_id=file_id,
            filename=filename,
            split_penalty=split_penalty,
        )
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/files/{file_id}/check-subtitle-alignment", response_model=SubtitleAlignmentCheckResponse)
async def check_media_subtitle_alignment(
    file_id: int,
    payload: Optional[SubtitleAlignmentCheckRequest] = Body(default=None),
    session: Session = Depends(get_session),
) -> SubtitleAlignmentCheckResponse:
    """检查指定媒体文件的字幕与音轨是否已对齐（不修改字幕文件）"""
    try:
        filename = payload.filename if payload else None
        threshold_ms = payload.threshold_ms if payload else 100.0
        return await SubtitleAlignService.check_media_subtitle_alignment(
            session=session,
            file_id=file_id,
            filename=filename,
            threshold_ms=threshold_ms,
        )
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/files/{file_id}/restore-subtitle", response_model=SubtitleAlignResponse)
async def restore_media_subtitle(
    file_id: int,
    payload: SubtitleRestoreRequest,
    session: Session = Depends(get_session),
) -> SubtitleAlignResponse:
    """将已对齐的字幕还原为其原始备份版本"""
    try:
        return SubtitleAlignService.restore_media_subtitle(
            session=session,
            file_id=file_id,
            filename=payload.filename,
        )
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/files/{file_id}/subtitles/trash", response_model=SubtitleTrashResponse)
async def trash_media_subtitle_by_id(
    file_id: int,
    payload: Optional[SubtitleTrashRequest] = Body(default=None),
    filename: Optional[str] = Query(default=None, description="字幕文件名（单字幕时可省略）"),
    session: Session = Depends(get_session),
) -> SubtitleTrashResponse:
    """将指定媒体文件的字幕安全移入系统回收站（非永久删除，支持随时还原）"""
    try:
        sub_name = (payload.filename if payload and payload.filename else None) or filename
        sub_path = payload.subtitle_path if payload else None
        result = SubtitleTrashService.trash_subtitle(
            session=session,
            file_id=file_id,
            filename=sub_name,
            subtitle_path=sub_path,
        )
        return SubtitleTrashResponse.model_validate(result.to_dict())
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/subtitles/trash", response_model=SubtitleTrashResponse)
async def trash_subtitle(
    payload: SubtitleTrashRequest,
    session: Session = Depends(get_session),
) -> SubtitleTrashResponse:
    """通用字幕安全移入回收站接口（支持通过 file_id+filename 或绝对路径指定字幕）"""
    try:
        result = SubtitleTrashService.trash_subtitle(
            session=session,
            file_id=payload.file_id,
            filename=payload.filename,
            subtitle_path=payload.subtitle_path,
        )
        return SubtitleTrashResponse.model_validate(result.to_dict())
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/subtitles/trash/restore", response_model=SubtitleTrashRestoreResponse)
async def restore_trashed_subtitle(
    payload: SubtitleTrashRestoreRequest,
    session: Session = Depends(get_session),
) -> SubtitleTrashRestoreResponse:
    """从回收站中还原字幕文件至原视频目录"""
    try:
        result = SubtitleTrashService.restore_subtitle(
            session=session,
            trash_id=payload.trash_id,
            file_id=payload.file_id,
            filename=payload.filename,
            subtitle_path=payload.subtitle_path,
            overwrite=payload.overwrite,
        )
        return SubtitleTrashRestoreResponse.model_validate(result.to_dict())
    except Exception as exc:
        raise_for_service_error(exc)


@router.post("/subtitles/trash/purge", response_model=SubtitleTrashPurgeResponse)
async def purge_trashed_subtitles(
    payload: Optional[SubtitleTrashPurgeRequest] = Body(default=None),
    session: Session = Depends(get_session),
) -> SubtitleTrashPurgeResponse:
    """按保留策略彻底删除过期回收站条目（默认保留 trash_retention_days 配置的天数，默认 365 天）"""
    try:
        retention_days = payload.retention_days if payload else None
        result = SubtitleTrashService.purge_expired(session=session, retention_days=retention_days)
        return SubtitleTrashPurgeResponse.model_validate(result.to_dict())
    except Exception as exc:
        raise_for_service_error(exc)


@router.get("/subtitles/trash", response_model=SubtitleTrashListResponse)
async def list_trashed_subtitles(
    file_id: Optional[int] = Query(default=None, description="按媒体文件 ID 过滤"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    include_restored: bool = Query(default=False, description="是否包含已还原记录"),
    session: Session = Depends(get_session),
) -> SubtitleTrashListResponse:
    """分页查询系统回收站中的字幕记录"""
    try:
        items, total = SubtitleTrashService.list_trashed(
            session=session,
            file_id=file_id,
            offset=offset,
            limit=limit,
            include_restored=include_restored,
        )
        serialized_items = [
            SubtitleTrashItem(
                id=item.id or 0,
                file_id=item.file_id,
                media_filename=item.media_filename,
                subtitle_filename=item.subtitle_filename,
                original_path=item.original_path,
                trash_path=item.trash_path,
                backup_original_path=item.backup_original_path,
                size_bytes=item.size_bytes,
                trashed_at=item.trashed_at.isoformat() if item.trashed_at else "",
                is_restored=item.is_restored,
                restored_at=item.restored_at.isoformat() if item.restored_at else None,
            )
            for item in items
        ]
        return SubtitleTrashListResponse(
            total=total,
            offset=offset,
            limit=limit,
            items=serialized_items,
        )
    except Exception as exc:
        raise_for_service_error(exc)
