import { useMediaPollingContext } from './useMediaPollingContext';

export type { MediaPath, ScannedFile, TaskStatus } from '../api';

type MediaType = 'movie' | 'tv';

export function useMediaPolling(type: MediaType) {
  const {
    movie,
    tv,
    status,
    refreshMovie,
    refreshTv,
    refreshAll,
    setIsScanningOptimistic,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
    setAligningSeriesOptimistic,
  } = useMediaPollingContext();

  const data = type === 'movie' ? movie : tv;
  const fetchData = type === 'movie' ? refreshMovie : refreshTv;

  return {
    paths: data.paths,
    files: data.files,
    status,
    fetchData,
    refreshMovie,
    refreshTv,
    refreshAll,
    setIsScanningOptimistic,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
    setAligningSeriesOptimistic,
  };
}
