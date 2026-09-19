from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Setting(SQLModel, table=True):
    """系统配置表"""

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    value: str
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.now)


class SearchCache(SQLModel, table=True):
    """搜索结果缓存表"""

    id: Optional[int] = Field(default=None, primary_key=True)
    query: str = Field(index=True, unique=True)
    # 存储 SubtitleResult 列表的 JSON 字符串
    results_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime


class SubtitleTask(SQLModel, table=True):
    """字幕下载/处理任务表"""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    source_url: str
    status: str = Field(default="pending")  # pending, downloading, completed, failed
    filename: Optional[str] = None
    save_path: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    # Target path for moving file after download
    target_path: Optional[str] = None  # Target directory for moved file
    target_type: Optional[str] = None  # "movie" or "tv"
    season: Optional[int] = None  # For TV series
    episode: Optional[int] = None  # For TV series
    language: Optional[str] = None  # For filename (简体/繁体/etc)
    file_id: Optional[int] = Field(default=None, index=True, foreign_key="scannedfile.id")


class MediaPath(SQLModel, table=True):
    """媒体库扫描路径表"""

    id: Optional[int] = Field(default=None, primary_key=True)
    path: str = Field(index=True, unique=True)
    type: str = Field(default="movie")  # movie, tv
    enabled: bool = Field(default=True)
    last_scanned_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ScannedFile(SQLModel, table=True):
    """扫描到的媒体文件"""

    id: Optional[int] = Field(default=None, primary_key=True)
    path_id: int = Field(foreign_key="mediapath.id")
    type: str = Field(default="movie")  # movie, tv
    file_path: str = Field(index=True, unique=True)
    filename: str
    extracted_title: Optional[str] = None
    year: Optional[str] = None
    nfo_title: Optional[str] = Field(default=None, index=True)
    nfo_original_title: Optional[str] = Field(default=None, index=True)
    nfo_aliases: Optional[str] = None  # JSON-encoded NFO aliases
    season: Optional[int] = None
    episode: Optional[int] = None
    has_subtitle: bool = Field(default=False)
    series_root_path: Optional[str] = Field(default=None)  # TV series root directory
    created_at: datetime = Field(default_factory=datetime.now)


class SubtitleTrash(SQLModel, table=True):
    """字幕回收站记录表（安全保存已回收的字幕文件与元数据，支持还原）"""

    id: Optional[int] = Field(default=None, primary_key=True)
    file_id: Optional[int] = Field(default=None, index=True, foreign_key="scannedfile.id")
    media_filename: Optional[str] = None
    subtitle_filename: str
    original_path: str = Field(index=True)
    trash_path: str
    backup_original_path: Optional[str] = None
    backup_trash_path: Optional[str] = None
    size_bytes: int = 0
    trashed_at: datetime = Field(default_factory=datetime.now)
    is_restored: bool = Field(default=False)
    restored_at: Optional[datetime] = None
