export const queryKeys = {
  media: {
    all: ['media'] as const,
    paths: () => [...queryKeys.media.all, 'paths'] as const,
    files: (pathType?: 'movie' | 'tv') => [...queryKeys.media.all, 'files', pathType ?? 'all'] as const,
    metadata: (fileId: number | null) => [...queryKeys.media.all, 'metadata', fileId] as const,
    taskStatus: () => [...queryKeys.media.all, 'task-status'] as const,
  },
  tasks: {
    all: ['tasks'] as const,
    list: () => [...queryKeys.tasks.all, 'list'] as const,
  },
  settings: {
    all: ['settings'] as const,
    list: () => [...queryKeys.settings.all, 'list'] as const,
  },
  schedule: {
    all: ['schedule'] as const,
    status: () => [...queryKeys.schedule.all, 'status'] as const,
  },
  system: {
    all: ['system'] as const,
    subtitleLanguages: () => [...queryKeys.system.all, 'subtitle-languages'] as const,
  },
  search: {
    all: ['search'] as const,
    results: (query: string) => [...queryKeys.search.all, 'results', query] as const,
  },
} as const;
