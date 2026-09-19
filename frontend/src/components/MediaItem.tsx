import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { autoMatchFile, type ScannedFile, type TaskStatus } from '../api';
import { getMediaTitle } from '../lib/mediaUtils';
import { SubtitleManagerModal } from './SubtitleManagerModal';

interface MediaItemProps {
  file: ScannedFile;
  status: TaskStatus;
  variant?: 'movie' | 'tv';
  showEpisode?: boolean;
  onAutoSearch?: (fileId: number) => Promise<void>;
  setMatchingFileOptimistic?: (fileId: number, isMatching: boolean) => void;
}

interface MediaItemTone {
  backgroundClass: string;
  borderClass: string;
  iconClass: string;
}

function getMediaItemTone(hasSubtitle: boolean, isMatching: boolean): MediaItemTone {
  if (hasSubtitle || isMatching) {
    return {
      backgroundClass: 'bg-surface-container-high',
      borderClass: 'hover:border-primary/20',
      iconClass: 'text-primary',
    };
  }

  return {
    backgroundClass: 'bg-surface-container-high/60',
    borderClass: 'hover:border-error-dim/20',
    iconClass: 'text-error',
  };
}

function getBadgeClass(hasSubtitle: boolean, isMatching: boolean): string {
  if (hasSubtitle || isMatching) {
    return 'bg-primary/10 text-primary border border-primary/20';
  }

  return 'bg-error-dim/10 text-error-dim border-error-dim/20';
}

function getBadgeLabel(
  hasSubtitle: boolean,
  isMatching: boolean,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  if (isMatching) {
    return t('status.searching');
  }

  if (hasSubtitle) {
    return t('status.matched');
  }

  return t('status.missing');
}

export function MediaItem({
  file,
  status,
  variant = 'movie',
  showEpisode = false,
  onAutoSearch,
  setMatchingFileOptimistic,
}: MediaItemProps): React.JSX.Element {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [manageModalOpen, setManageModalOpen] = useState(false);
  const isMatching = status.matching_files.includes(file.id);
  const hasSubtitle = file.has_subtitle;
  const { backgroundClass, borderClass, iconClass } = getMediaItemTone(hasSubtitle, isMatching);
  const badgeClass = getBadgeClass(hasSubtitle, isMatching);
  const badgeLabel = getBadgeLabel(hasSubtitle, isMatching, t);
  const episodeLabel = showEpisode ? `E${file.episode?.toString().padStart(2, '0') || '??'}` : null;

  const handleAutoSearch = async (): Promise<void> => {
    if (setMatchingFileOptimistic) {
      setMatchingFileOptimistic(file.id, true);
      setTimeout(() => setMatchingFileOptimistic(file.id, false), 3000);
    }
    try {
      if (onAutoSearch) {
        await onAutoSearch(file.id);
        return;
      }
      await autoMatchFile(file.id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(t('mediaConfig.triggerFailed') + ': ' + message);
      if (setMatchingFileOptimistic) {
        setMatchingFileOptimistic(file.id, false);
      }
    }
  };

  const handleManualSearch = (): void => {
    navigate(`/search?q=${encodeURIComponent(getMediaTitle(file))}`);
  };

  return (
    <div
      className={`grid xl:grid-cols-12 grid-cols-1 items-center gap-4 ${backgroundClass} p-4 rounded-2xl hover:bg-surface-bright/40 transition-colors border border-transparent ${borderClass} group`}
    >
      <div className="xl:col-span-8 flex items-center gap-5 w-full overflow-hidden">
        <div
          className={`w-12 h-12 rounded-xl bg-surface-container flex items-center justify-center ${iconClass} shadow-sm shrink-0 ${!hasSubtitle && !isMatching ? 'opacity-80' : ''}`}
        >
          {isMatching ? (
            <span className="material-symbols-outlined text-2xl animate-spin">sync</span>
          ) : (
            <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              {variant === 'tv' ? 'tv' : 'movie'}
            </span>
          )}
        </div>
        <div className="min-w-0 pr-2 overflow-hidden flex-1">
          <div className="flex items-center gap-3">
            {episodeLabel && (
              <span className="w-10 text-sm font-bold text-outline-variant shrink-0">{episodeLabel}</span>
            )}
            <p className="font-bold text-on-surface truncate" title={file.filename}>
              {file.filename}
            </p>
          </div>
        </div>
      </div>

      <div className="xl:col-span-4 flex items-center justify-start xl:justify-end gap-4 mt-2 xl:mt-0">
        <div className="flex items-center bg-surface-container rounded-lg p-0.5 border border-outline-variant/10">
          <button
            onClick={handleManualSearch}
            className="w-10 h-10 flex items-center justify-center rounded-md hover:bg-surface-container-highest text-on-surface-variant hover:text-primary transition-colors tooltip"
            title={t('page.search.title')}
          >
            <span className="material-symbols-outlined text-xl">search</span>
          </button>
          {hasSubtitle && (
            <button
              onClick={() => setManageModalOpen(true)}
              className="w-10 h-10 flex items-center justify-center rounded-md hover:bg-surface-container-highest text-on-surface-variant hover:text-primary transition-colors tooltip"
              title={t('subtitles.manageTitle')}
            >
              <span className="material-symbols-outlined text-xl">graphic_eq</span>
            </button>
          )}
          {!hasSubtitle && !isMatching && (
            <button
              onClick={handleAutoSearch}
              className="w-10 h-10 flex items-center justify-center rounded-md hover:bg-surface-container-highest text-on-surface-variant hover:text-primary transition-colors tooltip"
              title={t('action.autoSearch')}
            >
              <span className="material-symbols-outlined text-xl">download</span>
            </button>
          )}
        </div>

        <span className={`min-w-[84px] text-center px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest ${badgeClass}`}>
          {badgeLabel}
        </span>
      </div>

      <SubtitleManagerModal
        isOpen={manageModalOpen}
        onClose={() => setManageModalOpen(false)}
        file={file}
      />
    </div>
  );
}

interface MediaListProps {
  files: ScannedFile[];
  status: TaskStatus;
  onAutoSearch?: (fileId: number) => Promise<void>;
  setMatchingFileOptimistic?: (fileId: number, isMatching: boolean) => void;
}

export function MediaList({
  files,
  status,
  onAutoSearch,
  setMatchingFileOptimistic,
}: MediaListProps): React.JSX.Element {
  return (
    <div className="flex flex-col gap-3 w-full">
      {files.map(file => (
        <MediaItem
          key={file.id}
          file={file}
          status={status}
          variant="movie"
          onAutoSearch={onAutoSearch}
          setMatchingFileOptimistic={setMatchingFileOptimistic}
        />
      ))}
    </div>
  );
}
