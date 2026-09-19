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
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    target_path: Optional[str] = None
    target_type: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    language: Optional[str] = None


class SeasonMatchRequest(BaseModel):
    title: str = Field(min_length=1)
    season: int = Field(ge=1)


class SettingUpdateRequest(BaseModel):
    key: str
    value: str
    description: Optional[str] = None


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
