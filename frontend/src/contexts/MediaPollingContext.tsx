import {
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import type { TaskStatus } from '../api';
import { queryKeys } from '../lib/queryKeys';
import { MediaPollingContext, type MediaPollingContextValue } from './mediaPollingContext.shared';
import {
  useMediaFilesQuery,
  useMediaPathsQuery,
  useMediaTaskStatusQuery,
} from '../hooks/queries/useMediaQueries';

interface OptimisticStatusState {
  isScanning: boolean | null;
  matchingFiles: Set<number>;
  matchingSeasons: Map<string, { title: string; season: number }>;
  aligningSeries: Set<string>;
}

const ACTIVE_POLL_INTERVAL = 2000;
const IDLE_POLL_INTERVAL = 30000;
type MediaType = 'movie' | 'tv';

const initialOptimisticStatus: OptimisticStatusState = {
  isScanning: null,
  matchingFiles: new Set<number>(),
  matchingSeasons: new Map<string, { title: string; season: number }>(),
  aligningSeries: new Set<string>(),
};

function hasActiveTasks(status: TaskStatus | undefined): boolean {
  if (!status) {
    return false;
  }

  return (
    status.is_scanning ||
    status.matching_files.length > 0 ||
    status.matching_seasons.length > 0 ||
    status.aligning_series.length > 0
  );
}

function getSeasonKey(title: string, season: number): string {
  return `${title}::${season}`;
}

function mergeStatus(
  baseStatus: TaskStatus | undefined,
  optimisticStatus: OptimisticStatusState,
): TaskStatus {
  const mergedMatchingFiles = new Set(baseStatus?.matching_files ?? []);
  const mergedMatchingSeasons = new Map<string, { title: string; season: number }>();

  for (const match of baseStatus?.matching_seasons ?? []) {
    mergedMatchingSeasons.set(getSeasonKey(match.title, match.season), match);
  }

  for (const fileId of optimisticStatus.matchingFiles) {
    mergedMatchingFiles.add(fileId);
  }

  for (const [key, value] of optimisticStatus.matchingSeasons) {
    mergedMatchingSeasons.set(key, value);
  }

  const mergedAligningSeries = new Set(baseStatus?.aligning_series ?? []);
  for (const title of optimisticStatus.aligningSeries) {
    mergedAligningSeries.add(title);
  }

  return {
    is_scanning: optimisticStatus.isScanning ?? baseStatus?.is_scanning ?? false,
    matching_files: Array.from(mergedMatchingFiles),
    matching_seasons: Array.from(mergedMatchingSeasons.values()),
    aligning_series: Array.from(mergedAligningSeries),
    aligning_files: baseStatus?.aligning_files ?? [],
  };
}

async function invalidateMediaData(queryClient: QueryClient, type: MediaType | 'all'): Promise<void> {
  const fileQueries =
    type === 'all'
      ? [
          queryClient.invalidateQueries({ queryKey: queryKeys.media.files('movie') }),
          queryClient.invalidateQueries({ queryKey: queryKeys.media.files('tv') }),
        ]
      : [queryClient.invalidateQueries({ queryKey: queryKeys.media.files(type) })];

  await Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.media.paths() }),
    ...fileQueries,
    queryClient.invalidateQueries({ queryKey: queryKeys.media.taskStatus() }),
  ]);
}

export function MediaPollingProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [optimisticStatus, setOptimisticStatus] = useState<OptimisticStatusState>(initialOptimisticStatus);

  const mediaPathsQuery = useMediaPathsQuery();
  const movieFilesQuery = useMediaFilesQuery('movie');
  const tvFilesQuery = useMediaFilesQuery('tv');
  const statusQuery = useMediaTaskStatusQuery({
    // 活跃任务保持高频轮询；空闲时放宽到 30s，并避免后台标签页持续打点。
    refetchInterval: query => (
      hasActiveTasks(query.state.data) ? ACTIVE_POLL_INTERVAL : IDLE_POLL_INTERVAL
    ),
    refetchIntervalInBackground: false,
  });

  const refreshMovie = useCallback(async (): Promise<void> => {
    await invalidateMediaData(queryClient, 'movie');
  }, [queryClient]);

  const refreshTv = useCallback(async (): Promise<void> => {
    await invalidateMediaData(queryClient, 'tv');
  }, [queryClient]);

  const refreshAll = useCallback(async (): Promise<void> => {
    await invalidateMediaData(queryClient, 'all');
  }, [queryClient]);

  const setIsScanningOptimistic = useCallback((value: boolean): void => {
    setOptimisticStatus(prev => ({
      ...prev,
      isScanning: value,
    }));
  }, []);

  const setMatchingFileOptimistic = useCallback((fileId: number, isMatching: boolean): void => {
    setOptimisticStatus(prev => {
      const matchingFiles = new Set(prev.matchingFiles);

      if (isMatching) {
        matchingFiles.add(fileId);
      } else {
        matchingFiles.delete(fileId);
      }

      return {
        ...prev,
        matchingFiles,
      };
    });
  }, []);

  const setMatchingSeasonOptimistic = useCallback(
    (title: string, season: number, isMatching: boolean): void => {
      setOptimisticStatus(prev => {
        const matchingSeasons = new Map(prev.matchingSeasons);
        const seasonKey = getSeasonKey(title, season);

        if (isMatching) {
          matchingSeasons.set(seasonKey, { title, season });
        } else {
          matchingSeasons.delete(seasonKey);
        }

        return {
          ...prev,
          matchingSeasons,
        };
      });
    },
    [],
  );

  const setAligningSeriesOptimistic = useCallback((title: string, isAligning: boolean): void => {
    setOptimisticStatus(prev => {
      const aligningSeries = new Set(prev.aligningSeries);

      if (isAligning) {
        aligningSeries.add(title);
      } else {
        aligningSeries.delete(title);
      }

      return {
        ...prev,
        aligningSeries,
      };
    });
  }, []);

  const value = useMemo<MediaPollingContextValue>(() => {
    const status = mergeStatus(statusQuery.data, optimisticStatus);
    const allPaths = mediaPathsQuery.data ?? [];

    return {
      movie: {
        paths: allPaths.filter(path => path.type === 'movie'),
        files: movieFilesQuery.data ?? [],
      },
      tv: {
        paths: allPaths.filter(path => path.type === 'tv'),
        files: tvFilesQuery.data ?? [],
      },
      status,
      fetchMovieData: refreshMovie,
      fetchTvData: refreshTv,
      fetchAllData: refreshAll,
      refreshMovie,
      refreshTv,
      refreshAll,
      setIsScanningOptimistic,
      setMatchingFileOptimistic,
      setMatchingSeasonOptimistic,
      setAligningSeriesOptimistic,
    };
  }, [
    mediaPathsQuery.data,
    movieFilesQuery.data,
    optimisticStatus,
    refreshAll,
    refreshMovie,
    refreshTv,
    setIsScanningOptimistic,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
    setAligningSeriesOptimistic,
    statusQuery.data,
    tvFilesQuery.data,
  ]);

  return <MediaPollingContext.Provider value={value}>{children}</MediaPollingContext.Provider>;
}
