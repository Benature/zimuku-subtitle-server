import type { ScannedFile } from '../types/api';

export interface HomeStats {
  totalFiles: number;
  hasSubtitle: number;
  missingSubtitle: number;
  totalMovies: number;
  hasSubtitleMovies: number;
  missingMovies: number;
  totalSeries: number;
  hasSubtitleSeries: number;
  missingSeries: number;
}

interface SubtitleStats {
  total: number;
  hasSubtitle: number;
  missingSubtitle: number;
}

function buildSubtitleStats(files: ScannedFile[]): SubtitleStats {
  const total = files.length;
  // 允许无字幕的文件不计入缺失统计
  const hasSubtitle = files.filter(file => file.has_subtitle || file.allow_no_subtitle).length;

  return {
    total,
    hasSubtitle,
    missingSubtitle: total - hasSubtitle,
  };
}

export function buildHomeStats(movieFiles: ScannedFile[], tvFiles: ScannedFile[]): HomeStats {
  const movieStats = buildSubtitleStats(movieFiles);
  const tvStats = buildSubtitleStats(tvFiles);

  return {
    totalFiles: movieStats.total + tvStats.total,
    hasSubtitle: movieStats.hasSubtitle + tvStats.hasSubtitle,
    missingSubtitle: movieStats.missingSubtitle + tvStats.missingSubtitle,
    totalMovies: movieStats.total,
    hasSubtitleMovies: movieStats.hasSubtitle,
    missingMovies: movieStats.missingSubtitle,
    totalSeries: tvStats.total,
    hasSubtitleSeries: tvStats.hasSubtitle,
    missingSeries: tvStats.missingSubtitle,
  };
}

export function buildRecentMedia(movieFiles: ScannedFile[], tvFiles: ScannedFile[], limit = 6): ScannedFile[] {
  const titlesSeen = new Set<string>();
  const recentFiles: ScannedFile[] = [];
  const allFiles = [...movieFiles, ...tvFiles].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  );

  for (const file of allFiles) {
    // 首页最近媒体按“类型 + 标题”去重，避免同一剧集多集把列表占满。
    const key = `${file.type}:${file.extracted_title}`;
    if (titlesSeen.has(key)) {
      continue;
    }

    titlesSeen.add(key);
    recentFiles.push(file);

    if (recentFiles.length >= limit) {
      break;
    }
  }

  return recentFiles;
}
