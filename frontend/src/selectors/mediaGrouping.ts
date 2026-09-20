import { getMediaSeasonNumber, getMediaTitle, parseMediaYear } from '../lib/mediaUtils';
import type { ScannedFile, FilterOption, SortOption, SortOrder } from '../types/api';

export interface BaseMediaGroup {
  title: string;
  year?: string;
  createdAt?: string;
  hasSubCount: number;
  totalCount: number;
  /** 作品下所有文件均标记「允许无字幕」时为 true，不再参与缺字幕补全 */
  allowNoSubtitle: boolean;
}

export interface MovieGroup extends BaseMediaGroup {
  files: ScannedFile[];
}

export interface TvGroup extends BaseMediaGroup {
  firstPath: string;
  seriesRootPath: string;
  firstFileId: number;
  seasons: Record<number, ScannedFile[]>;
}

function getSubtitleRatio(group: BaseMediaGroup): number {
  if (group.totalCount === 0) {
    return 0;
  }

  return group.hasSubCount / group.totalCount;
}

function buildMediaTitle(file: ScannedFile, unknownLabel: string): string {
  return getMediaTitle(file, unknownLabel);
}

function addFileToSeasonGroup(seasons: Record<number, ScannedFile[]>, file: ScannedFile): void {
  const season = getMediaSeasonNumber(file.season);

  if (!seasons[season]) {
    seasons[season] = [];
  }

  seasons[season].push(file);
  seasons[season].sort((a, b) => (a.episode || 0) - (b.episode || 0));
}

function applySearchAndFilter<T extends BaseMediaGroup>(
  groups: T[],
  searchTerm: string,
  filterOption: FilterOption,
): T[] {
  const searchedGroups = groups.filter(group => matchesSearchTerm(group.title, searchTerm));
  return filterGroups(searchedGroups, filterOption);
}

function sortGroups<T extends BaseMediaGroup>(
  groups: T[],
  sortOption: SortOption,
  sortOrder: SortOrder
): T[] {
  return [...groups].sort((a, b) => {
    let comparison = 0;

    if (sortOption === 'year') {
      const yearA = parseMediaYear(a.year);
      const yearB = parseMediaYear(b.year);
      comparison = yearA - yearB;
    } else if (sortOption === 'created') {
      comparison = (a.createdAt || '').localeCompare(b.createdAt || '');
    } else if (sortOption === 'status') {
      const ratioA = getSubtitleRatio(a);
      const ratioB = getSubtitleRatio(b);
      comparison = ratioA - ratioB;
    } else {
      comparison = a.title.localeCompare(b.title);
    }

    return sortOrder === 'asc' ? comparison : -comparison;
  });
}

function filterGroups<T extends BaseMediaGroup>(groups: T[], filterOption: FilterOption): T[] {
  if (filterOption === 'missing') {
    return groups.filter(group => !group.allowNoSubtitle && group.hasSubCount < group.totalCount);
  }

  return groups;
}

function matchesSearchTerm(title: string, searchTerm: string): boolean {
  return title.toLowerCase().includes(searchTerm.toLowerCase());
}

export function buildMovieGroups(files: ScannedFile[], unknownLabel: string): MovieGroup[] {
  const groups = new Map<string, MovieGroup>();

  for (const file of files) {
    const title = buildMediaTitle(file, unknownLabel);

    if (!groups.has(title)) {
      groups.set(title, {
        title,
        year: file.year ?? undefined,
        files: [],
        createdAt: file.created_at,
        hasSubCount: 0,
        totalCount: 0,
        allowNoSubtitle: true,
      });
    }

    const group = groups.get(title)!;
    group.files.push(file);
    group.totalCount += 1;
    group.allowNoSubtitle = group.allowNoSubtitle && file.allow_no_subtitle;
    if (file.has_subtitle) {
      group.hasSubCount += 1;
    }
  }

  return Array.from(groups.values());
}

export function buildTvGroups(files: ScannedFile[], unknownLabel: string): TvGroup[] {
  const groups = new Map<string, TvGroup>();

  for (const file of files) {
    const title = buildMediaTitle(file, unknownLabel);

    if (!groups.has(title)) {
      groups.set(title, {
        title,
        year: file.year ?? undefined,
        totalCount: 0,
        hasSubCount: 0,
        firstPath: file.file_path,
        seriesRootPath: file.series_root_path || file.file_path.split('/').slice(0, -1).join('/'),
        firstFileId: file.id,
        createdAt: file.created_at,
        seasons: {},
        allowNoSubtitle: true,
      });
    }

    const group = groups.get(title)!;
    addFileToSeasonGroup(group.seasons, file);
    group.totalCount += 1;
    group.allowNoSubtitle = group.allowNoSubtitle && file.allow_no_subtitle;
    if (file.has_subtitle) {
      group.hasSubCount += 1;
    }
  }

  return Array.from(groups.values());
}

export function buildGroupedMedia(
  files: ScannedFile[],
  type: 'movie',
  searchTerm: string,
  sortOption: SortOption,
  sortOrder: SortOrder,
  filterOption: FilterOption,
  unknownLabel: string
): MovieGroup[];
export function buildGroupedMedia(
  files: ScannedFile[],
  type: 'tv',
  searchTerm: string,
  sortOption: SortOption,
  sortOrder: SortOrder,
  filterOption: FilterOption,
  unknownLabel: string
): TvGroup[];
export function buildGroupedMedia(
  files: ScannedFile[],
  type: 'movie' | 'tv',
  searchTerm: string,
  sortOption: SortOption,
  sortOrder: SortOrder,
  filterOption: FilterOption,
  unknownLabel: string
): MovieGroup[] | TvGroup[] {
  if (type === 'movie') {
    const groups = buildMovieGroups(files, unknownLabel);
    const filteredGroups = applySearchAndFilter(groups, searchTerm, filterOption);

    return sortGroups(filteredGroups, sortOption, sortOrder);
  }

  const groups = buildTvGroups(files, unknownLabel);
  const filteredGroups = applySearchAndFilter(groups, searchTerm, filterOption);

  return sortGroups(filteredGroups, sortOption, sortOrder);
}
