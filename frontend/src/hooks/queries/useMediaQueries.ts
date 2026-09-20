import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';
import {
  addMediaPath,
  deleteMediaPath,
  fetchMediaMetadata,
  fetchMediaSubtitleSummary,
  getTaskStatus,
  listMediaPaths,
  listScannedFiles,
  triggerMediaMatch,
} from '../../api';
import { queryKeys } from '../../lib/queryKeys';
import type { MediaPath, ScannedFile, SubtitleSummaryEntry, TaskStatus } from '../../types/api';

type MediaType = 'movie' | 'tv';
type AddMediaPathVariables = { path: string; pathType: MediaType };
type DeleteMediaPathVariables = { id: number; pathType: MediaType };

async function invalidateMediaPathQueries(
  queryClient: QueryClient,
  pathType: MediaType,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.media.paths() }),
    queryClient.invalidateQueries({ queryKey: queryKeys.media.files(pathType) }),
  ]);
}

async function invalidateMediaMatchQueries(
  queryClient: QueryClient,
  pathType?: MediaType,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.media.taskStatus() }),
    queryClient.invalidateQueries({ queryKey: queryKeys.media.files(pathType) }),
    // 前缀匹配，同时失效 movie/tv 两个字幕汇总缓存
    queryClient.invalidateQueries({ queryKey: [...queryKeys.media.all, 'subtitle-summary'] }),
  ]);
}

type MediaPathsQueryOptions = Omit<
  UseQueryOptions<MediaPath[], Error, MediaPath[], ReturnType<typeof queryKeys.media.paths>>,
  'queryKey' | 'queryFn'
>;

type MediaFilesQueryOptions = Omit<
  UseQueryOptions<ScannedFile[], Error, ScannedFile[], ReturnType<typeof queryKeys.media.files>>,
  'queryKey' | 'queryFn'
>;

export function useMediaPathsQuery(options?: MediaPathsQueryOptions) {
  return useQuery({
    queryKey: queryKeys.media.paths(),
    queryFn: listMediaPaths,
    ...options,
  });
}

export function useMediaFilesQuery(pathType?: 'movie' | 'tv', options?: MediaFilesQueryOptions) {
  return useQuery({
    queryKey: queryKeys.media.files(pathType),
    queryFn: () => listScannedFiles(pathType),
    ...options,
  });
}

type MediaSubtitleSummaryQueryOptions = Omit<
  UseQueryOptions<Record<string, SubtitleSummaryEntry>, Error>,
  'queryKey' | 'queryFn'
>;

export function useMediaSubtitleSummaryQuery(
  mediaType: 'movie' | 'tv',
  options?: MediaSubtitleSummaryQueryOptions
) {
  return useQuery<Record<string, SubtitleSummaryEntry>, Error>({
    queryKey: queryKeys.media.subtitleSummary(mediaType),
    queryFn: () => fetchMediaSubtitleSummary(mediaType),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    throwOnError: false,
    ...options,
  });
}

export function useMediaMetadataQuery(fileId: number | null) {
  return useQuery({
    queryKey: queryKeys.media.metadata(fileId),
    queryFn: () => fetchMediaMetadata(fileId!),
    enabled: fileId !== null,
    staleTime: 5 * 60 * 1000,
    retry: 1,
    throwOnError: false,
  });
}

type MediaTaskStatusQueryOptions = Omit<
  UseQueryOptions<TaskStatus, Error, TaskStatus, ReturnType<typeof queryKeys.media.taskStatus>>,
  'queryKey' | 'queryFn'
>;

export function useMediaTaskStatusQuery(options?: MediaTaskStatusQueryOptions) {
  return useQuery({
    queryKey: queryKeys.media.taskStatus(),
    queryFn: getTaskStatus,
    ...options,
  });
}

export function useAddMediaPathMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ path, pathType }: AddMediaPathVariables) =>
      addMediaPath(path, pathType),
    onSuccess: async (_, variables) => {
      await invalidateMediaPathQueries(queryClient, variables.pathType);
    },
  });
}

export function useDeleteMediaPathMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, pathType }: DeleteMediaPathVariables) =>
      deleteMediaPath(id).then(() => pathType),
    onSuccess: async pathType => {
      await invalidateMediaPathQueries(queryClient, pathType);
    },
  });
}

export function useTriggerMediaMatchMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (pathType?: MediaType) => triggerMediaMatch(pathType),
    onSuccess: async (_, pathType) => {
      await invalidateMediaMatchQueries(queryClient, pathType);
    },
  });
}
