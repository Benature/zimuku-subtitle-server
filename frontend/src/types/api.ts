// Media Types
export interface MediaMetadata {
  file_id: number;
  filename: string;
  nfo_data: {
    title?: string;
    year?: string;
    plot?: string;
    rating?: string;
    genres?: string[];
    director?: string;
    runtime?: string;
  } | null;
  poster_path: string | null;
  fanart_path: string | null;
  txt_info: Record<string, string> | null;
}

export interface ScannedFile {
  id: number;
  filename: string;
  extracted_title: string | null;
  file_path: string;
  year?: string | null;
  season?: number | null;
  episode?: number | null;
  has_subtitle: boolean;
  series_root_path?: string;
  type: 'movie' | 'tv';
  created_at: string;
}

export interface MediaPath {
  id: number;
  path: string;
  type: string;
  enabled: boolean;
  last_scanned_at?: string;
}

export interface TaskStatus {
  is_scanning: boolean;
  matching_files: number[];
  matching_seasons: { title: string; season: number }[];
}

// Task Types
export interface Task {
  id: number;
  title: string;
  status: 'pending' | 'downloading' | 'completed' | 'failed';
  source_url: string;
  save_path?: string;
  error_msg?: string;
  created_at: string;
  updated_at: string;
}

// Settings Types
export interface Setting {
  id: number;
  key: string;
  value: string;
  description?: string;
  updated_at: string;
}

export interface SubtitleLanguage {
  code: string;
  display_name: string;
  filename_tag: string;
}

// Search Types
export interface SearchResult {
  title: string;
  link: string;
  lang?: string[];
  download_count?: string;
  author?: string;
  format?: string;
  fps?: string;
  rating?: string;
}

// Media Selector Types
export interface MediaSelection {
  id: number | string;
  title: string;
  type: 'movie' | 'tv';
  path: string;
  year?: number;
  episode_count?: number;
  season?: number;
  episodes?: number[];
}

// Sidebar Types
export interface SidebarItem {
  id: string;
  displayTitle: string;
  year?: string;
  totalCount: number;
  hasSubCount: number;
  poster?: string | null;
  createdAt?: string;
}

export type SortOption = 'name' | 'year' | 'created' | 'status';
export type FilterOption = 'all' | 'missing';
export type SortOrder = 'asc' | 'desc';

// Subtitle & Alignment Types
export interface ExistingSubtitle {
  filename: string;
  file_path: string;
  format: string;
  size_bytes: number;
  modified_at: string;
  filename_language?: string | null;
  is_binary: boolean;
  detected_language: string;
  detected_language_name: string;
  is_bilingual: boolean;
  encoding: string;
  has_backup: boolean;
  backup_filename?: string | null;
}

export interface AlignerStatus {
  available: boolean;
  engine?: string | null;
  ffmpeg_available: boolean;
  message: string;
}

export interface SubtitleAlignResponse {
  status: string;
  message: string;
  file_id?: number | null;
  subtitle_filename: string;
  backup_filename?: string | null;
  has_backup: boolean;
}
