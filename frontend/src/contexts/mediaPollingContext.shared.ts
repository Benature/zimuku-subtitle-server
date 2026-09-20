import { createContext } from 'react';
import type { MediaPath, ScannedFile, TaskStatus } from '../api';

interface MediaCollectionState {
  paths: MediaPath[];
  files: ScannedFile[];
}

interface MediaPollingState {
  movie: MediaCollectionState;
  tv: MediaCollectionState;
  status: TaskStatus;
}

export interface MediaPollingContextValue extends MediaPollingState {
  fetchMovieData: () => Promise<void>;
  fetchTvData: () => Promise<void>;
  fetchAllData: () => Promise<void>;
  refreshMovie: () => Promise<void>;
  refreshTv: () => Promise<void>;
  refreshAll: () => Promise<void>;
  setIsScanningOptimistic: (value: boolean) => void;
  setMatchingFileOptimistic: (fileId: number, isMatching: boolean) => void;
  setMatchingSeasonOptimistic: (title: string, season: number, isMatching: boolean) => void;
  setAligningSeriesOptimistic: (title: string, isAligning: boolean) => void;
}

export const MediaPollingContext = createContext<MediaPollingContextValue | null>(null);
