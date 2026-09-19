export const API_BASE = '/api';

export const API_ENDPOINTS = {
  // Media
  MEDIA_PATHS: '/media/paths',
  MEDIA_FILES: '/media/files',
  MEDIA_METADATA: (fileId: number) => `/media/metadata/${fileId}`,
  MEDIA_POSTER: '/media/poster',
  MEDIA_MATCH: '/media/match',
  MEDIA_AUTO_MATCH: (fileId: number) => `/media/files/${fileId}/auto-match`,
  MEDIA_TV_MATCH_SEASON: '/media/tv/match-season',
  MEDIA_TASK_STATUS: '/media/task-status',
  MEDIA_SUBTITLES: (fileId: number) => `/media/files/${fileId}/subtitles`,
  MEDIA_ALIGN_SUBTITLE: (fileId: number) => `/media/files/${fileId}/align-subtitle`,
  MEDIA_RESTORE_SUBTITLE: (fileId: number) => `/media/files/${fileId}/restore-subtitle`,
  MEDIA_ALIGNER_STATUS: '/media/aligner/status',

  // Tasks
  TASKS: '/tasks/',
  TASK_RETRY: (taskId: number) => `/tasks/${taskId}/retry`,
  TASK_CLEAR_COMPLETED: '/tasks/clear-completed',
  TASK_ALIGN_SUBTITLE: (taskId: number) => `/tasks/${taskId}/align-subtitle`,

  // Search
  SEARCH: '/search/',

  // Settings
  SETTINGS: '/settings/',

  // System
  SUBTITLE_LANGUAGES: '/system/subtitle-languages',
} as const;
