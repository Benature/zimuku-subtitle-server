import { describe, expect, it } from 'vitest';
import {
  buildSidebarItem,
  getCurrentSeasonFiles,
  getGroupSubtitleSummary,
  getNextSelectedSeason,
  getNextSelectedTitle,
  getSelectionFromUrl,
  getTotalEpisodesCount,
  isSelectedSeasonMatching,
  orderSidebarEntriesByDisplayYear,
} from './mediaBrowser';
import type { MediaMetadata, TaskStatus } from '../types/api';
import type { TvGroup } from './mediaGrouping';

const seriesGroup: TvGroup = {
  title: 'Series',
  year: '2020',
  totalCount: 2,
  hasSubCount: 1,
  firstPath: '/tv/Series/S01E01.mkv',
  seriesRootPath: '/tv/Series',
  firstFileId: 11,
  createdAt: '2026-03-21T09:00:00',
  seasons: {
    1: [
      {
        id: 11,
        filename: 'Series S01E01.mkv',
        extracted_title: 'Series',
        file_path: '/tv/Series/S01E01.mkv',
        year: '2020',
        season: 1,
        episode: 1,
        has_subtitle: true,
        type: 'tv',
        created_at: '2026-03-21T09:00:00',
      },
    ],
    2: [
      {
        id: 12,
        filename: 'Series S02E01.mkv',
        extracted_title: 'Series',
        file_path: '/tv/Series/S02E01.mkv',
        year: '2021',
        season: 2,
        episode: 1,
        has_subtitle: false,
        type: 'tv',
        created_at: '2026-03-22T09:00:00',
      },
    ],
  },
};

const metadata: MediaMetadata = {
  file_id: 11,
  filename: 'Series S01E01.mkv',
  nfo_data: {
    title: 'Series (NFO)',
    year: '2024',
  },
  poster_path: 'poster.jpg',
  fanart_path: null,
  txt_info: null,
};

const status: TaskStatus = {
  is_scanning: false,
  matching_files: [],
  matching_seasons: [{ title: 'Series', season: 2 }],
};

describe('mediaBrowser selectors', () => {
  it('sidebar item 优先使用 metadata 展示字段', () => {
    expect(buildSidebarItem(seriesGroup, metadata)).toMatchObject({
      displayTitle: 'Series (NFO)',
      year: '2024',
      poster: '/api/media/poster?path=poster.jpg',
    });
  });

  it('按展示年份排序侧栏条目', () => {
    const entries = [
      { group: { ...seriesGroup, title: 'A', year: '2020' }, item: { id: 'A', displayTitle: 'A', year: '2025', totalCount: 1, hasSubCount: 1 } },
      { group: { ...seriesGroup, title: 'B', year: '2024' }, item: { id: 'B', displayTitle: 'B', year: '2023', totalCount: 1, hasSubCount: 1 } },
    ];

    expect(orderSidebarEntriesByDisplayYear(entries, 'desc').map(entry => entry.item.id)).toEqual(['A', 'B']);
  });

  it('对齐状态只统计有字幕的文件，取最差状态', () => {
    // seriesGroup 中 id=11 有字幕，id=12 无字幕
    expect(
      getGroupSubtitleSummary(seriesGroup, { '11': { alignment_status: 'aligned', languages: [] } }).alignmentStatus
    ).toBe('aligned');
    expect(
      getGroupSubtitleSummary(seriesGroup, {
        '11': { alignment_status: 'misaligned', languages: [] },
        '12': { alignment_status: 'aligned', languages: [] },
      }).alignmentStatus
    ).toBe('misaligned');
    // 无字幕文件缺失记录不影响聚合
    expect(getGroupSubtitleSummary(seriesGroup, {}).alignmentStatus).toBe('unknown');
    expect(getGroupSubtitleSummary(seriesGroup, undefined).alignmentStatus).toBe('unknown');
  });

  it('字幕语言取所有文件语言的并集并去重', () => {
    const summary = getGroupSubtitleSummary(seriesGroup, {
      '11': { alignment_status: 'aligned', languages: ['简英双语', '英语'] },
    });

    expect(summary.languages).toEqual(['简英双语', '英语']);
  });

  it('没有字幕文件的作品不展示对齐与语言标签', () => {
    const noSubGroup: TvGroup = {
      ...seriesGroup,
      seasons: {
        1: seriesGroup.seasons[2].map(file => ({ ...file, id: 21 })),
      },
    };

    const summary = getGroupSubtitleSummary(noSubGroup, {
      '21': { alignment_status: 'aligned', languages: ['英语'] },
    });
    expect(summary.alignmentStatus).toBeNull();
    expect(summary.languages).toEqual([]);
  });

  it('能解析 URL 选中项并回退默认选中', () => {
    expect(getSelectionFromUrl([seriesGroup], 'Series', '2')).toEqual({ title: 'Series', season: 2 });
    expect(getNextSelectedTitle([seriesGroup], null)).toBe('Series');
    expect(getNextSelectedSeason([1, 2], 3)).toBe(1);
  });

  it('能计算当前季文件、总集数和季级匹配状态', () => {
    expect(getCurrentSeasonFiles(seriesGroup, 2)).toHaveLength(1);
    expect(getTotalEpisodesCount(seriesGroup)).toBe(2);
    expect(isSelectedSeasonMatching(status, seriesGroup, 2)).toBe(true);
  });
});
