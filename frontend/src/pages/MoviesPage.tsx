import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MediaGridToolbar } from '../components/MediaGridToolbar';
import { MediaCard } from '../components/MediaCard';
import { MediaInfoCard } from '../components/MediaInfoCard';
import { MediaList } from '../components/MediaItem';
import { useMediaBrowserController } from '../hooks/useMediaBrowserController';

export default function MoviesPage() {
  const { t } = useTranslation();
  const {
    selectedItem: selectedMovie,
    sidebarItems,
    searchTerm,
    setSearchTerm,
    selectedTitle: selectedMovieTitle,
    setSelectedTitle: setSelectedMovieTitle,
    sortOption,
    sortOrder,
    filterOption,
    handleSortChange,
    setFilterOption,
    handleRefresh,
    status,
    setMatchingFileOptimistic,
  } = useMediaBrowserController({
    type: 'movie',
    unknownLabel: t('page.movies.unknownMovie'),
  });

  // 从仪表盘等页面带 ?title= 跳转进来时，直接展开详情面板。
  const [detailOpen, setDetailOpen] = useState(
    () => new URLSearchParams(window.location.search).has('title')
  );

  const handleSelect = (id: string) => {
    setSelectedMovieTitle(id);
    setDetailOpen(true);
  };

  return (
    <div className="flex gap-6 w-full h-[calc(100vh-120px)] min-h-0 max-w-[1800px]">
      <section className="flex-1 flex flex-col min-w-0 min-h-0 bg-surface-container-low rounded-2xl border border-outline-variant/5 overflow-hidden">
        <MediaGridToolbar
          title={t('movie')}
          searchTerm={searchTerm}
          onSearchTermChange={setSearchTerm}
          searchPlaceholder={t('page.movies.placeholder')}
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
                  selected={detailOpen && selectedMovieTitle === item.id}
                  onSelect={handleSelect}
                />
              ))}
            </div>
          ) : (
            <div className="text-center text-sm text-on-surface-variant font-label py-10 opacity-70">
              {t('page.movies.noMovies')}
            </div>
          )}
        </div>
      </section>

      {selectedMovie && detailOpen && (
        <>
          <div
            className="lg:hidden fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
            onClick={() => setDetailOpen(false)}
          />
          <section className="fixed lg:static inset-y-6 right-4 left-4 sm:left-auto sm:w-[520px] lg:inset-auto z-50 lg:z-auto lg:w-[440px] xl:w-[520px] shrink-0 flex flex-col min-h-0 bg-surface-container-low rounded-2xl overflow-hidden border border-outline-variant/5">
            <div className="relative shrink-0">
              <MediaInfoCard
                fileId={selectedMovie.files[0]?.id}
                title={selectedMovie.title}
                year={selectedMovie.year}
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
              <div className="flex justify-between items-center bg-surface-container/50 p-4 rounded-xl border border-outline-variant/10">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="material-symbols-outlined text-on-surface-variant shrink-0">folder_open</span>
                  <code className="text-sm text-on-surface-variant font-body truncate">
                    {selectedMovie.files[0]?.file_path?.split('/').slice(0, -1).join('/') ||
                      selectedMovie.files[0]?.file_path?.split('\\').slice(0, -1).join('\\')}
                  </code>
                </div>
              </div>

              <div className="space-y-6">
                <div className="flex items-center justify-between px-2 w-full">
                  <h3 className="text-xl font-bold font-headline text-on-surface">{t('page.movies.localFiles')}</h3>
                  <span className="text-sm text-on-surface-variant font-label">
                    {t('page.movies.fileCount', { count: selectedMovie.files.length })}
                  </span>
                </div>
                <div className="w-full">
                  <MediaList
                    files={selectedMovie.files}
                    status={status}
                    setMatchingFileOptimistic={setMatchingFileOptimistic}
                  />
                </div>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
