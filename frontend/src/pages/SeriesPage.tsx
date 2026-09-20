import { useState } from 'react';
import axios from 'axios';
import { useTranslation } from 'react-i18next';
import { alignSeriesSubtitles, autoMatchFile, matchTVSeason } from '../api';
import { AllowNoSubtitleToggle } from '../components/AllowNoSubtitleToggle';
import ConfirmDialog from '../components/ConfirmDialog';
import { MediaGridToolbar } from '../components/MediaGridToolbar';
import { MediaCard } from '../components/MediaCard';
import { MediaInfoCard } from '../components/MediaInfoCard';
import { MediaItem } from '../components/MediaItem';
import { Search, Loader2, AudioWaveform } from 'lucide-react';
import { useMediaBrowserController } from '../hooks/useMediaBrowserController';
import { useToast } from '../hooks/useToast';

export default function SeriesPage() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const {
    selectedItem: selectedSeries,
    sidebarItems,
    searchTerm,
    setSearchTerm,
    selectedTitle: selectedSeriesTitle,
    setSelectedTitle: setSelectedSeriesTitle,
    sortOption,
    sortOrder,
    filterOption,
    handleSortChange,
    setFilterOption,
    handleRefresh,
    status,
    setMatchingFileOptimistic,
    setMatchingSeasonOptimistic,
    setAligningSeriesOptimistic,
    selectedSeason,
    setSelectedSeason,
    availableSeasons,
    currentSeasonFiles,
    totalEpisodesCount,
    isSelectedSeasonMatching,
    isSelectedSeriesAligning,
  } = useMediaBrowserController({
    type: 'tv',
    unknownLabel: t('page.series.unknownSeries'),
  });

  // 从仪表盘等页面带 ?title= 跳转进来时，直接展开详情面板。
  const [detailOpen, setDetailOpen] = useState(
    () => new URLSearchParams(window.location.search).has('title')
  );

  const handleSelect = (id: string) => {
    setSelectedSeriesTitle(id);
    setDetailOpen(true);
  };

  const handleAutoSearch = async (fileId: number) => {
    setMatchingFileOptimistic(fileId, true);
    setTimeout(() => setMatchingFileOptimistic(fileId, false), 3000);
    try {
      await autoMatchFile(fileId);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('mediaConfig.triggerFailed') + ': ' + message, 'error');
      setMatchingFileOptimistic(fileId, false);
    }
  };

  const handleMatchSeason = async (title: string, season: number) => {
    setMatchingSeasonOptimistic(title, season, true);
    const timeoutId = setTimeout(() => setMatchingSeasonOptimistic(title, season, false), 3000);
    try {
      await matchTVSeason(title, season);
    } catch (err: unknown) {
      clearTimeout(timeoutId);
      setMatchingSeasonOptimistic(title, season, false);
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('mediaConfig.triggerFailed') + ': ' + message, 'error');
    }
  };

  // 全剧对齐确认弹窗状态：force 标记是否为系统繁忙后的强制执行确认
  const [alignConfirm, setAlignConfirm] = useState<{ title: string; force: boolean } | null>(null);

  const triggerAlignSeries = async (title: string, force: boolean) => {
    setAligningSeriesOptimistic(title, true);
    const timeoutId = setTimeout(() => setAligningSeriesOptimistic(title, false), 3000);
    try {
      await alignSeriesSubtitles(title, force);
    } catch (err: unknown) {
      clearTimeout(timeoutId);
      setAligningSeriesOptimistic(title, false);
      // 系统繁忙（503 资源守卫）时展示原因并提供强制执行入口
      if (!force && axios.isAxiosError(err) && err.response?.status === 503) {
        const detail = (err.response.data as { detail?: string } | undefined)?.detail;
        showToast(detail || err.message, 'error');
        setAlignConfirm({ title, force: true });
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('mediaConfig.triggerFailed') + ': ' + message, 'error');
    }
  };

  const handleAlignSeries = (title: string) => {
    setAlignConfirm({ title, force: false });
  };

  return (
    <div className="flex gap-6 w-full h-[calc(100vh-120px)] min-h-0 max-w-[1800px]">
      <section className="flex-1 flex flex-col min-w-0 min-h-0 bg-surface-container-low rounded-2xl border border-outline-variant/5 overflow-hidden">
        <MediaGridToolbar
          title={t('tv')}
          searchTerm={searchTerm}
          onSearchTermChange={setSearchTerm}
          searchPlaceholder={t('page.series.placeholder')}
          onRefresh={handleRefresh}
          isRefreshing={status.is_scanning}
          sortOption={sortOption}
          onSortOptionChange={handleSortChange}
          sortOrder={sortOrder}
          filterOption={filterOption}
          onFilterOptionChange={setFilterOption}
        />

        <div className="flex-1 overflow-y-auto custom-scrollbar p-6">
          {sidebarItems.length > 0 ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-5">
              {sidebarItems.map(item => (
                <MediaCard
                  key={item.id}
                  item={item}
                  selected={detailOpen && selectedSeriesTitle === item.id}
                  onSelect={handleSelect}
                />
              ))}
            </div>
          ) : (
            <div className="text-center text-sm text-on-surface-variant font-label py-10 opacity-70">
              {t('page.series.noSeries')}
            </div>
          )}
        </div>
      </section>

      {selectedSeries && detailOpen && (
        <>
          <div
            className="lg:hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            onClick={() => setDetailOpen(false)}
          />
          <section className="fixed lg:static inset-y-6 right-4 left-4 sm:left-auto sm:w-[520px] lg:inset-auto z-50 lg:z-auto lg:w-[440px] xl:w-[520px] shrink-0 flex flex-col min-h-0 bg-surface-container-low rounded-2xl overflow-hidden border border-outline-variant/5">
            <div className="relative shrink-0">
              <MediaInfoCard
                fileId={selectedSeries.firstFileId}
                title={selectedSeries.title}
                year={selectedSeries.year}
                isTv={true}
                count={totalEpisodesCount}
              />
              <button
                onClick={() => setDetailOpen(false)}
                className="absolute top-4 right-4 z-10 w-9 h-9 rounded-full bg-black/50 backdrop-blur-md text-white flex items-center justify-center hover:bg-black/70 transition-colors active:scale-90"
                title={t('action.close')}
              >
                <span className="material-symbols-outlined text-lg">close</span>
              </button>
            </div>

            <div className="flex-1 min-h-0 p-6 pt-4 space-y-6 overflow-y-auto custom-scrollbar">
              <div className="flex justify-between items-center gap-3 bg-surface-container/50 p-4 rounded-xl border border-outline-variant/10">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="material-symbols-outlined text-on-surface-variant shrink-0">folder_open</span>
                  <code className="text-sm text-on-surface-variant font-body truncate">{selectedSeries.seriesRootPath}</code>
                </div>
                <button
                  onClick={() => handleAlignSeries(selectedSeries.title)}
                  disabled={isSelectedSeriesAligning}
                  title={t('page.series.alignAllSubtitles')}
                  className={`shrink-0 text-xs px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-2 border uppercase tracking-widest ${
                    isSelectedSeriesAligning
                      ? 'bg-surface-container text-on-surface-variant border-outline-variant/20 cursor-not-allowed'
                      : 'bg-secondary/10 text-secondary border-secondary/20 hover:bg-secondary/20'
                  }`}
                >
                  {isSelectedSeriesAligning ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                  ) : (
                    <AudioWaveform className="w-3.5 h-3.5 shrink-0" />
                  )}
                  {isSelectedSeriesAligning ? t('page.series.aligningSubtitles') : t('page.series.alignAllSubtitles')}
                </button>
              </div>

              <AllowNoSubtitleToggle
                mediaType="tv"
                title={selectedSeries.title}
                allowNoSubtitle={selectedSeries.allowNoSubtitle}
              />

              <div className="flex items-center justify-between border-b border-outline-variant/10 relative">
                <div className="flex gap-6 overflow-x-auto scrollbar-hide">
                  {availableSeasons.map(s => (
                    <button
                      key={s}
                      onClick={() => setSelectedSeason(s)}
                      className={`pb-4 text-sm whitespace-nowrap transition-colors relative ${
                        selectedSeason === s
                          ? 'text-primary font-bold border-b-2 border-primary z-10'
                          : 'text-on-surface-variant font-medium hover:text-on-surface'
                      }`}
                    >
                      {t('page.series.season', { n: s })}
                    </button>
                  ))}
                </div>
                {selectedSeries && (
                  <button
                    onClick={() => handleMatchSeason(selectedSeries.title, selectedSeason)}
                    disabled={isSelectedSeasonMatching}
                    className={`absolute right-0 bottom-3 text-xs px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-2 border uppercase tracking-widest ${
                      isSelectedSeasonMatching
                        ? 'bg-surface-container text-on-surface-variant border-outline-variant/20 cursor-not-allowed'
                        : 'bg-primary/10 text-primary border-primary/20 hover:bg-primary/20 hover:shadow-[0_0_12px_rgba(189,194,255,0.1)]'
                    }`}
                  >
                    {isSelectedSeasonMatching ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
                    ) : (
                      <Search className="w-3.5 h-3.5 shrink-0" />
                    )}
                    {isSelectedSeasonMatching ? t('page.series.smartMatching') : t('page.series.smartMatch')}
                  </button>
                )}
              </div>

              <div className="space-y-6">
                <div className="flex items-center justify-between px-2 w-full">
                  <div className="flex items-center gap-4">
                    <h3 className="text-xl font-bold font-headline text-on-surface">
                      {t('page.movies.localFiles')}
                    </h3>
                    {currentSeasonFiles.some(f => !f.has_subtitle && !f.allow_no_subtitle) && (
                      <div className="flex items-center gap-2 bg-error-dim/10 text-error-dim px-3 py-1 rounded-full border border-error-dim/20">
                        <span className="material-symbols-outlined text-sm">warning</span>
                        <span className="text-[11px] font-bold uppercase tracking-wider">
                          {t('status.missing')}
                        </span>
                      </div>
                    )}
                  </div>
                  <span className="text-sm text-on-surface-variant font-label">
                    {t('page.movies.fileCount', { count: currentSeasonFiles.length })}
                  </span>
                </div>

                <div className="flex flex-col gap-3 w-full">
                  {currentSeasonFiles.map(file => (
                    <MediaItem
                      key={file.id}
                      file={file}
                      status={status}
                      variant="tv"
                      showEpisode={true}
                      onAutoSearch={handleAutoSearch}
                    />
                  ))}
                  {currentSeasonFiles.length === 0 && (
                    <div className="p-8 text-center text-sm font-label text-on-surface-variant opacity-70">
                      {t('page.series.noVideos')}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        </>
      )}

      <ConfirmDialog
        isOpen={alignConfirm !== null}
        message={
          alignConfirm
            ? t(alignConfirm.force ? 'page.series.alignAllForceConfirm' : 'page.series.alignAllConfirm', {
                title: alignConfirm.title,
              })
            : ''
        }
        onCancel={() => setAlignConfirm(null)}
        onConfirm={() => {
          const pending = alignConfirm;
          setAlignConfirm(null);
          if (pending) {
            void triggerAlignSeries(pending.title, pending.force);
          }
        }}
      />
    </div>
  );
}
