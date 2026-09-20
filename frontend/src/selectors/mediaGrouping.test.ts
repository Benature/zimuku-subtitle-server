import { describe, expect, it } from 'vitest';
import { buildGroupedMedia, buildMovieGroups, buildTvGroups } from './mediaGrouping';
import type { ScannedFile } from '../types/api';

const movieFiles: ScannedFile[] = [
  {
    id: 1,
    filename: 'Movie A.mkv',
    extracted_title: 'Movie A',
    file_path: '/movies/Movie A.mkv',
    year: '2024',
    has_subtitle: true,
    allow_no_subtitle: false,
    type: 'movie',
    created_at: '2026-03-21T10:00:00',
  },
  {
    id: 2,
    filename: 'Movie A.mp4',
    extracted_title: 'Movie A',
    file_path: '/movies/Movie A.mp4',
    year: '2024',
    has_subtitle: false,
    allow_no_subtitle: false,
    type: 'movie',
    created_at: '2026-03-20T10:00:00',
  },
];

const tvFiles: ScannedFile[] = [
  {
    id: 10,
    filename: 'Series S01E02.mkv',
    extracted_title: 'Series',
    file_path: '/tv/Series/S01E02.mkv',
    year: '2023',
    season: 1,
    episode: 2,
    has_subtitle: false,
    allow_no_subtitle: false,
    type: 'tv',
    created_at: '2026-03-22T09:00:00',
  },
  {
    id: 11,
    filename: 'Series S01E01.mkv',
    extracted_title: 'Series',
    file_path: '/tv/Series/S01E01.mkv',
    year: '2023',
    season: 1,
    episode: 1,
    has_subtitle: true,
    allow_no_subtitle: false,
    type: 'tv',
    created_at: '2026-03-21T09:00:00',
  },
];

describe('mediaGrouping selectors', () => {
  it('按标题聚合电影并统计字幕数量', () => {
    const groups = buildMovieGroups(movieFiles, '未知');

    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      title: 'Movie A',
      totalCount: 2,
      hasSubCount: 1,
    });
  });

  it('按季聚合剧集并保持集数顺序', () => {
    const groups = buildTvGroups(tvFiles, '未知');

    expect(groups).toHaveLength(1);
    expect(groups[0].seasons[1].map(file => file.episode)).toEqual([1, 2]);
  });

  it('支持缺失字幕筛选和年份排序', () => {
    const groups = buildGroupedMedia(
      [...movieFiles, { ...movieFiles[0], id: 3, extracted_title: 'Movie B', filename: 'Movie B.mkv', year: '2020', has_subtitle: false, file_path: '/movies/Movie B.mkv' }],
      'movie',
      '',
      'year',
      'desc',
      'missing',
      '未知'
    );

    expect(groups.map(group => group.title)).toEqual(['Movie A', 'Movie B']);
  });

  it('全部文件标记允许无字幕时作品视为无需补字幕', () => {
    const flaggedFiles: ScannedFile[] = [
      { ...movieFiles[0], id: 20, has_subtitle: false, allow_no_subtitle: true },
      { ...movieFiles[1], id: 21, allow_no_subtitle: true },
    ];

    const groups = buildMovieGroups(flaggedFiles, '未知');

    expect(groups[0].allowNoSubtitle).toBe(true);
    // 缺字幕筛选应排除已标记作品
    const filtered = buildGroupedMedia(flaggedFiles, 'movie', '', 'name', 'asc', 'missing', '未知');
    expect(filtered).toHaveLength(0);
  });

  it('仅部分文件标记时作品仍视为需要字幕', () => {
    const partialFiles: ScannedFile[] = [
      { ...movieFiles[0], id: 30, has_subtitle: false, allow_no_subtitle: true },
      { ...movieFiles[1], id: 31 },
    ];

    const groups = buildMovieGroups(partialFiles, '未知');

    expect(groups[0].allowNoSubtitle).toBe(false);
    const filtered = buildGroupedMedia(partialFiles, 'movie', '', 'name', 'asc', 'missing', '未知');
    expect(filtered).toHaveLength(1);
  });
});
