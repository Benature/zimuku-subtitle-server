from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class StatusResponse(BaseModel):
    status: str = "ok"


class TaskTriggerResponse(StatusResponse):
    message: str
    task_kind: str
    target: Optional[str] = None


class ActionResponse(StatusResponse):
    message: str
    cleared_count: Optional[int] = None


class TaskListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[Any]


class TaskCreateRequest(BaseModel):
    title: Optional[str] = None
    source_url: str = Field(min_length=1)
    target_path: Optional[str] = None
    target_type: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    language: Optional[str] = None
    file_id: Optional[int] = None


class FileSubtitleDownloadRequest(BaseModel):
    source_url: str = Field(min_length=1)
    title: Optional[str] = None
    language: Optional[str] = None


class SeasonMatchRequest(BaseModel):
    title: str = Field(min_length=1)
    season: int = Field(ge=1)


class SettingUpdateRequest(BaseModel):
    key: str
    value: str
    description: Optional[str] = None


class ScheduleStatusResponse(BaseModel):
    enabled: bool
    cron: str
    next_run_time: Optional[str] = None
    running: bool
    last_run: Optional[dict] = None


class FeishuTestResponse(StatusResponse):
    message: str
    delivered: bool


class SubtitleLanguageResponse(BaseModel):
    code: str
    display_name: str
    filename_tag: str


class MediaMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: int
    filename: str
    nfo_data: Optional[dict[str, Any]] = None
    poster_path: Optional[str] = None
    fanart_path: Optional[str] = None
    txt_info: Optional[dict[str, Any]] = None


class MediaSummary(BaseModel):
    media_key: str
    level: str
    media_type: str
    title: str
    nfo_title: Optional[str] = None
    nfo_original_title: Optional[str] = None
    nfo_aliases: list[str]
    year: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    path_ids: list[int]
    file_count: int
    subtitle_file_count: int
    missing_subtitle_file_count: int


class MediaListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[MediaSummary]


class SubtitleSummaryResponse(BaseModel):
    """单个媒体文件的字幕汇总（卡片墙展示用）。"""

    alignment_status: str = "unknown"
    languages: list[str] = []


class ExistingSubtitleResponse(BaseModel):
    filename: str
    file_path: str
    format: str
    size_bytes: int
    modified_at: str
    filename_language: Optional[str] = None
    is_binary: bool
    detected_language: str
    detected_language_name: str
    is_bilingual: bool
    encoding: str
    chinese_char_count: int
    english_word_count: int
    bilingual_dialogue_count: int
    sample_dialogues: list[str]
    confidence: float
    details: dict[str, Any]
    has_backup: bool = False
    backup_filename: Optional[str] = None
    alignment_status: str = "unknown"
    alignment_max_shift_ms: Optional[float] = None
    alignment_mean_shift_ms: Optional[float] = None
    alignment_checked_at: Optional[str] = None


class SubtitleContentResponse(BaseModel):
    file_id: int
    media_filename: str
    subtitle_filename: str
    subtitle_path: str
    format: str
    encoding: str
    is_binary: bool
    clean_text: bool
    total_lines: int
    returned_lines: int
    lines: list[str]
    analysis: dict[str, Any]


class AlignerStatusResponse(BaseModel):
    available: bool
    engine: Optional[str] = None
    ffmpeg_available: bool
    alass_path: Optional[str] = None
    ffsubsync_path: Optional[str] = None
    message: str


class SubtitleAlignRequest(BaseModel):
    filename: Optional[str] = None
    split_penalty: float = Field(default=7.0, ge=0.0, le=1000.0)


class SubtitleRestoreRequest(BaseModel):
    filename: str = Field(min_length=1)


class SubtitleAlignResponse(StatusResponse):
    message: str
    file_id: Optional[int] = None
    subtitle_filename: str
    backup_filename: Optional[str] = None
    has_backup: bool = True


class SubtitleAlignmentCheckRequest(BaseModel):
    filename: Optional[str] = None
    threshold_ms: float = Field(default=100.0, ge=0.0, le=60000.0)


class SubtitleAlignmentCheckResponse(StatusResponse):
    aligned: bool
    checked_cues: int
    max_shift_ms: float
    mean_shift_ms: float
    threshold_ms: float
    message: str
    file_id: Optional[int] = None
    subtitle_filename: str


class SubtitleTrashRequest(BaseModel):
    file_id: Optional[int] = None
    filename: Optional[str] = None
    subtitle_path: Optional[str] = None


class SubtitleTrashResponse(StatusResponse):
    trash_id: int
    file_id: Optional[int] = None
    media_filename: Optional[str] = None
    subtitle_filename: str
    original_path: str
    trash_path: str
    has_backup: bool
    size_bytes: int
    trashed_at: str
    remaining_subtitles: list[str]
    has_subtitle: bool
    is_permanent_deletion: bool = False
    message: str


class SubtitleTrashRestoreRequest(BaseModel):
    trash_id: Optional[int] = None
    file_id: Optional[int] = None
    filename: Optional[str] = None
    subtitle_path: Optional[str] = None
    overwrite: bool = False


class SubtitleTrashRestoreResponse(StatusResponse):
    trash_id: int
    file_id: Optional[int] = None
    subtitle_filename: str
    restored_path: str
    has_backup_restored: bool
    restored_at: str
    has_subtitle: bool
    message: str


class SubtitleTrashItem(BaseModel):
    id: int
    file_id: Optional[int] = None
    media_filename: Optional[str] = None
    subtitle_filename: str
    original_path: str
    trash_path: str
    backup_original_path: Optional[str] = None
    size_bytes: int
    trashed_at: str
    is_restored: bool
    restored_at: Optional[str] = None


class SubtitleTrashListResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[SubtitleTrashItem]


class SubtitleTrashPurgeRequest(BaseModel):
    retention_days: Optional[int] = Field(
        default=None, ge=0, description="覆盖保留天数；不传则使用系统配置 trash_retention_days（默认 365）"
    )


class SubtitleTrashPurgeResponse(StatusResponse):
    retention_days: int
    cutoff: Optional[str] = None
    purged_count: int
    purged_records: list[dict[str, Any]]
    message: str
