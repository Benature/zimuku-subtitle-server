import { useEffect, useMemo, useState, startTransition } from 'react';
import { useQueries } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  fetchMediaMetadata,
  type FilterOption,
  type SortOption,
  type SortOrder,
} from '../api';
import { useMediaGrouping, type MovieGroup, type TvGroup } from './useMediaGrouping';
import { useMediaPolling } from './useMediaPolling';
import { useMediaSubtitleSummaryQuery, useTriggerMediaMatchMutation } from './queries';
import { queryKeys } from '../lib/queryKeys';
import { useUIStore } from '../stores/useUIStore';
import type { SidebarItem } from '../types/api';
import {
  buildSidebarItem,
  findGroupByTitle,
  getCurrentSeasonFiles,
  getDefaultSortOrder,
  getGroupSubtitleSummary,
  getNextSelectedSeason,
  getNextSelectedTitle,
  getSelectionFromUrl,
  getSortedSeasonNumbers,
  isMovieGroup,
  isSelectedSeasonMatching as getIsSelectedSeasonMatching,
  orderSidebarEntries,
  type SidebarEntry,
  getTotalEpisodesCount,
} from '../selectors/mediaBrowser';

const DESKTOP_MEDIA_QUERY = '(min-width: 1024px)';

interface BaseControllerOptions {
  unknownLabel: string;
}

interface MovieControllerOptions extends BaseControllerOptions {
  type: 'movie';
}

interface TvControllerOptions extends BaseControllerOptions {
  type: 'tv';
}

interface BaseMediaBrowserController<TGroup extends MovieGroup | TvGroup> {
  files: ReturnType<typeof useMediaPolling>['files'];
  groupedItems: TGroup[];
  selectedItem: TGroup | undefined;
  sidebarItems: SidebarItem[];
  searchTerm: string;
  setSearchTerm: (value: string) => void;
  selectedTitle: string | null;
  setSelectedTitle: (title: string) => void;
  sortOption: SortOption;
  sortOrder: SortOrder;
  filterOption: FilterOption;
  handleSortChange: (option: SortOption) => void;
  setFilterOption: (option: FilterOption) => void;
  handleRefresh: () => Promise<void>;
  status: ReturnType<typeof useMediaPolling>['status'];
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setIsScanningOptimistic: ReturnType<typeof useMediaPolling>['setIsScanningOptimistic'];
  setMatchingFileOptimistic: ReturnType<typeof useMediaPolling>['setMatchingFileOptimistic'];
  setMatchingSeasonOptimistic: ReturnType<typeof useMediaPolling>['setMatchingSeasonOptimistic'];
}

interface MovieBrowserController extends BaseMediaBrowserController<MovieGroup> {
  type: 'movie';
}

interface TvBrowserController extends BaseMediaBrowserController<TvGroup> {
  type: 'tv';
  selectedSeason: number;
  setSelectedSeason: (season: number) => void;
  availableSeasons: number[];
  currentSeasonFiles: TvGroup['seasons'][number];
  totalEpisodesCount: number;
  isSelectedSeasonMatching: boolean;
}

function useKeepDesktopSidebarOpen(toggleSidebar: () => void) {
  useEffect(() => {
    const mediaQuery = window.matchMedia(DESKTOP_MEDIA_QUERY);
    const handleChange = (event: MediaQueryListEvent) => {
      if (event.matches && !useUIStore.getState().sidebarOpen) {
        toggleSidebar();
      }
    };

    mediaQuery.addEventListener('change', handleChange);
    return () => mediaQuery.removeEventListener('change', handleChange);
  }, [toggleSidebar]);
}

function getSidebarMetadataFileId(
  group: MovieGroup | TvGroup,
  type: 'movie' | 'tv',
): number | undefined {
  if (type === 'movie') {
    return isMovieGroup(group) ? group.files[0]?.id : undefined;
  }

  return isMovieGroup(group) ? undefined : group.firstFileId;
}

function useSidebarEntries<TGroup extends MovieGroup | TvGroup>(
  groups: TGroup[],
  type: 'movie' | 'tv'
) {
  const metadataQueries = useQueries({
    queries: groups.map(group => {
      const fileId = getSidebarMetadataFileId(group, type);

      return {
        queryKey: queryKeys.media.metadata(fileId ?? null),
        queryFn: () => fetchMediaMetadata(fileId!),
        staleTime: 10 * 60 * 1000,
        retry: 1,
        enabled: typeof fileId === 'number',
      };
    }),
  });

  return useMemo<SidebarEntry<TGroup>[]>(() => {
    return groups.map((group, index) => {
      const metadata = metadataQueries[index]?.data;

      return {
        group,
        item: buildSidebarItem(group, metadata),
      };
    });
  }, [groups, metadataQueries]);
}

export function useMediaBrowserController(options: MovieControllerOptions): MovieBrowserController;
export function useMediaBrowserController(options: TvControllerOptions): TvBrowserController;
export function useMediaBrowserController(
  options: MovieControllerOptions | TvControllerOptions
): MovieBrowserController | TvBrowserController {
  const { type, unknownLabel } = options;
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    files,
    status,
    setIsScanningOptimistic,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
  } = useMediaPolling(type);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTitle, setSelectedTitle] = useState<string | null>(null);
  const [sortOption, setSortOption] = useState<SortOption>('name');
  const [sortOrder, setSortOrder] = useState<SortOrder>('asc');
  const [filterOption, setFilterOption] = useState<FilterOption>('all');
  const [selectedSeason, setSelectedSeason] = useState(1);
  const { sidebarOpen, toggleSidebar } = useUIStore();
  const triggerMediaMatchMutation = useTriggerMediaMatchMutation();

  useKeepDesktopSidebarOpen(toggleSidebar);

  const groupedItems = useMediaGrouping(
    files,
    type,
    searchTerm,
    sortOption,
    sortOrder,
    filterOption,
    unknownLabel
  ) as MovieGroup[] | TvGroup[];

  const movieGroupedItems = type === 'movie' ? (groupedItems as MovieGroup[]) : [];
  const tvGroupedItems = type === 'tv' ? (groupedItems as TvGroup[]) : [];

  const movieSidebarEntries = useSidebarEntries(movieGroupedItems, 'movie');
  const tvSidebarEntries = useSidebarEntries(tvGroupedItems, 'tv');
  const orderedMovieEntries = useMemo(
    () => orderSidebarEntries(movieSidebarEntries, sortOption, sortOrder),
    [movieSidebarEntries, sortOption, sortOrder]
  );
  const orderedTvEntries = useMemo(
    () => orderSidebarEntries(tvSidebarEntries, sortOption, sortOrder),
    [tvSidebarEntries, sortOption, sortOrder]
  );
  const orderedEntries = type === 'movie' ? orderedMovieEntries : orderedTvEntries;

  const orderedGroupedItems = useMemo(() => orderedEntries.map(entry => entry.group), [orderedEntries]);
  const orderedMovieGroupedItems = useMemo(
    () => (type === 'movie' ? (orderedGroupedItems as MovieGroup[]) : []),
    [orderedGroupedItems, type]
  );
  const orderedTvGroupedItems = useMemo(
    () => (type === 'tv' ? (orderedGroupedItems as TvGroup[]) : []),
    [orderedGroupedItems, type]
  );

  const { data: subtitleSummary } = useMediaSubtitleSummaryQuery(type);

  const sidebarItems = useMemo(
    () =>
      orderedEntries.map(entry => {
        const summary = getGroupSubtitleSummary(entry.group, subtitleSummary);
        return {
          ...entry.item,
          alignmentStatus: summary.alignmentStatus,
          languages: summary.languages,
        };
      }),
    [orderedEntries, subtitleSummary]
  );

  useEffect(() => {
    const titleFromUrl = searchParams.get('title');
    const seasonFromUrl = searchParams.get('season');
    // URL 参数只负责“一次性恢复选中项”，消费后立即清掉，避免后续筛选/切换被旧参数反向覆盖。
    const urlSelection = type === 'movie'
      ? getSelectionFromUrl(orderedMovieGroupedItems, titleFromUrl, seasonFromUrl)
      : getSelectionFromUrl(orderedTvGroupedItems, titleFromUrl, seasonFromUrl);

    if (urlSelection?.title) {
      startTransition(() => {
        setSelectedTitle(urlSelection.title);
        if (type === 'tv' && typeof urlSelection.season === 'number') {
          setSelectedSeason(urlSelection.season);
        }
      });

      const nextParams = new URLSearchParams(searchParams);
      nextParams.delete('title');
      nextParams.delete('season');
      setSearchParams(nextParams, { replace: true });
      return;
    }

    const nextSelectedTitle = type === 'movie'
      ? getNextSelectedTitle(orderedMovieGroupedItems, selectedTitle)
      : getNextSelectedTitle(orderedTvGroupedItems, selectedTitle);

    if (nextSelectedTitle && nextSelectedTitle !== selectedTitle) {
      const timer = setTimeout(() => {
        // 延后到下一轮事件循环设置默认选中，避免和当前渲染批次里的 URL 消费/列表重排互相打架。
        setSelectedTitle(nextSelectedTitle);

        if (type === 'tv') {
          const firstItem = findGroupByTitle(orderedTvGroupedItems, nextSelectedTitle);
          const firstSeason = getSortedSeasonNumbers(firstItem)[0];
          if (typeof firstSeason === 'number') {
            setSelectedSeason(firstSeason);
          }
        }
      }, 0);

      return () => clearTimeout(timer);
    }
  }, [
    orderedMovieGroupedItems,
    orderedTvGroupedItems,
    searchParams,
    selectedTitle,
    setSearchParams,
    type,
  ]);

  const selectedItem = useMemo(
    () => (type === 'movie'
      ? findGroupByTitle(orderedMovieGroupedItems, selectedTitle)
      : findGroupByTitle(orderedTvGroupedItems, selectedTitle)),
    [orderedMovieGroupedItems, orderedTvGroupedItems, selectedTitle, type]
  );
  const selectedTvItem = useMemo(
    () => (type === 'tv' ? findGroupByTitle(orderedTvGroupedItems, selectedTitle) : undefined),
    [orderedTvGroupedItems, selectedTitle, type]
  );

  const availableSeasons = useMemo(
    () => (type === 'tv' ? getSortedSeasonNumbers(selectedTvItem) : []),
    [selectedTvItem, type]
  );

  useEffect(() => {
    if (type !== 'tv' || !selectedTvItem) return;
    const nextSeason = getNextSelectedSeason(availableSeasons, selectedSeason);
    if (nextSeason === null || nextSeason === selectedSeason) return;

    // 剧集在筛选、排序或 URL 恢复后，若当前季已失效则自动回到可用季。
    const timer = setTimeout(() => setSelectedSeason(nextSeason), 0);
    return () => clearTimeout(timer);
  }, [availableSeasons, selectedSeason, selectedTvItem, type]);

  const currentSeasonFiles = useMemo(() => {
    if (type !== 'tv') return [];

    return getCurrentSeasonFiles(selectedTvItem, selectedSeason);
  }, [selectedSeason, selectedTvItem, type]);

  const totalEpisodesCount = useMemo(() => {
    if (type !== 'tv') return 0;

    return getTotalEpisodesCount(selectedTvItem);
  }, [selectedTvItem, type]);

  const isSelectedSeasonMatching = useMemo(() => {
    if (type !== 'tv') return false;

    return getIsSelectedSeasonMatching(status, selectedTvItem, selectedSeason);
  }, [selectedSeason, selectedTvItem, status, type]);

  const handleSortChange = (option: SortOption) => {
    if (option === sortOption) {
      setSortOrder(current => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }

    setSortOption(option);
    setSortOrder(getDefaultSortOrder(option));
  };

  const handleRefresh = async () => {
    try {
      setIsScanningOptimistic(true);
      // 维持当前“点击后立即进入扫描中”的前端体验，同时复用统一 mutation 的失效刷新链路。
      setTimeout(() => setIsScanningOptimistic(false), 3000);
      await triggerMediaMatchMutation.mutateAsync(type);
    } catch (error: unknown) {
      console.error(error);
    }
  };

  if (type === 'movie') {
    return {
      type,
      files,
      groupedItems: orderedMovieGroupedItems,
      selectedItem: selectedItem as MovieGroup | undefined,
      sidebarItems,
      searchTerm,
      setSearchTerm,
      selectedTitle,
      setSelectedTitle,
      sortOption,
      sortOrder,
      filterOption,
      handleSortChange,
      setFilterOption,
      handleRefresh,
      status,
      sidebarOpen,
      toggleSidebar,
      setIsScanningOptimistic,
      setMatchingFileOptimistic,
      setMatchingSeasonOptimistic,
    };
  }

  return {
    type,
    files,
    groupedItems: orderedTvGroupedItems,
    selectedItem: selectedItem as TvGroup | undefined,
    sidebarItems,
    searchTerm,
    setSearchTerm,
    selectedTitle,
    setSelectedTitle,
    sortOption,
    sortOrder,
    filterOption,
    handleSortChange,
    setFilterOption,
    handleRefresh,
    status,
    sidebarOpen,
    toggleSidebar,
    setIsScanningOptimistic,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
    selectedSeason,
    setSelectedSeason,
    availableSeasons,
    currentSeasonFiles,
    totalEpisodesCount,
    isSelectedSeasonMatching,
  };
}
