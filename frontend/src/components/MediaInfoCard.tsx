import { useTranslation } from 'react-i18next';
import { useMediaMetadata, useMediaPosterUrl } from '../hooks/useMetadata';

interface ErrorStateProps {
  title: string;
  year?: string;
  onRetry: () => void;
}

function getRuntimeText(runtime: string | number | undefined): string | null {
  if (!runtime) {
    return null;
  }

  const runtimeText = String(runtime);
  return runtimeText.includes('min') ? runtimeText : `${runtimeText} min`;
}

function SkeletonLoader(): React.JSX.Element {
  return (
    <div className="h-[260px] relative overflow-hidden flex-shrink-0 animate-pulse bg-surface-container-low">
      <div className="absolute inset-0 bg-gradient-to-t from-surface-container-low via-surface-container-low/60 to-transparent"></div>
      <div className="absolute bottom-8 left-10 right-10 flex justify-between items-end">
        <div className="flex gap-8 items-end w-full">
          <div className="mb-2 w-full">
            <div className="h-4 bg-surface-container-highest rounded w-32 mb-4" />
            <div className="h-12 bg-surface-container-highest rounded w-3/4 max-w-lg mb-6" />
            <div className="flex gap-6">
              <div className="h-6 bg-surface-container-highest rounded w-16" />
              <div className="h-6 bg-surface-container-highest rounded w-16" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ErrorState({ title, year, onRetry }: ErrorStateProps): React.JSX.Element {
  const { t } = useTranslation();
  return (
    <div className="h-[260px] relative overflow-hidden flex-shrink-0 bg-surface-container-low border-b border-outline-variant/10">
      <div className="absolute inset-0 bg-gradient-to-t from-surface-container-low via-surface-container-low/60 to-transparent"></div>
      <div className="absolute bottom-8 left-10 right-10 flex justify-between items-end">
        <div className="flex gap-8 items-end">
          <div className="mb-2">
            <p className="text-sm font-label font-semibold text-error mb-1 uppercase tracking-widest">{t('metadataError')}</p>
            <h2 className="text-5xl font-extrabold font-headline text-on-surface tracking-tight leading-none">{title}</h2>
            <div className="flex items-center gap-6 mt-5">
              <span className="flex items-center gap-2 text-on-surface-variant font-medium">
                <span className="material-symbols-outlined text-lg">calendar_today</span>
                {year || t('year.unknown')}
              </span>
            </div>
          </div>
        </div>
        <div className="flex gap-3">
          <button onClick={onRetry} className="bg-surface-container text-on-surface px-6 py-3 rounded-xl font-headline font-bold hover:bg-surface-container-highest transition-colors flex items-center gap-2 text-sm">
            <span className="material-symbols-outlined text-xl">refresh</span>
            {t('metadataRetry')}
          </button>
        </div>
      </div>
    </div>
  );
}

interface MediaInfoCardProps {
  fileId: number;
  title: string;
  year?: string;
  isTv?: boolean;
  count?: number;
}

// ...

export function MediaInfoCard({
  fileId,
  title,
  year,
  isTv,
  count,
}: MediaInfoCardProps): React.JSX.Element {
  const { t } = useTranslation();
  const { data: metadata, isLoading, error, refetch } = useMediaMetadata(fileId);
  const bannerUrl = useMediaPosterUrl(metadata?.fanart_path ?? metadata?.poster_path ?? null);

  const displayTitle = metadata?.nfo_data?.title || title;
  const displayYear = metadata?.nfo_data?.year || year;
  const rating = metadata?.nfo_data?.rating;
  const runtimeText = getRuntimeText(metadata?.nfo_data?.runtime);
  const originalLanguage =
    metadata?.nfo_data?.original_language ?? metadata?.nfo_data?.country?.join(' / ') ?? null;

  if (isLoading) {
    return <SkeletonLoader />;
  }

  if (error) {
    return <ErrorState title={title} year={year} onRetry={() => refetch()} />;
  }

  return (
    <div className="h-[260px] relative overflow-hidden flex-shrink-0 border-b border-outline-variant/10">
      {bannerUrl ? (
        <img alt={displayTitle} className="w-full h-full object-cover opacity-30 blur-sm scale-105" src={bannerUrl} />
      ) : (
        <div className="absolute w-full h-full bg-surface-container-lowest"></div>
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-surface-container-low via-surface-container-low/60 to-transparent"></div>
      <div className="absolute bottom-8 left-10 right-10 flex justify-between items-end">
        <div className="flex gap-8 items-end">
          <div className="mb-2">
            <h2 className="text-5xl font-extrabold font-headline text-on-surface tracking-tight leading-none truncate max-w-3xl hover:text-wrap">{displayTitle}</h2>
            <div className="flex items-center gap-6 mt-5 text-on-surface-variant font-medium">
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-lg">calendar_today</span>
                {displayYear || t('year.unknown')}
              </span>
              <span className="flex items-center gap-2">
                <span className="material-symbols-outlined text-lg text-tertiary" style={{ fontVariationSettings: "'FILL' 1" }}>star</span>
                {rating || '0.0'}
              </span>
              {originalLanguage && (
                <span className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">language</span>
                  {originalLanguage}
                </span>
              )}
              {isTv && count !== undefined && (
                <span className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg text-primary">layers</span>
                  {t('page.series.episodes', { count })}
                </span>
              )}
              {!isTv && runtimeText && (
                <span className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg text-secondary">schedule</span>
                  {runtimeText}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
