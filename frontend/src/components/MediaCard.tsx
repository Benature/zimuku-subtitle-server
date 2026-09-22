import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { SidebarItem } from '../types/api';

interface MediaCardProps {
  item: SidebarItem;
  selected: boolean;
  onSelect: (id: string) => void;
}

type PosterStatus = 'loading' | 'loaded' | 'error';

// 海报占位图标：加载中（呼吸动画的 image 图标）与加载失败（broken_image 图标）区分展示
function PosterPlaceholder({ status }: { status: PosterStatus }): React.JSX.Element {
  if (status === 'loading') {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <span className="material-symbols-outlined text-4xl text-outline animate-pulse">image</span>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-1">
      <span className="material-symbols-outlined text-4xl text-outline">broken_image</span>
    </div>
  );
}

// 通过 key={src} 挂载，src 变化时自动重置加载状态
function PosterImage({ src, alt }: { src: string; alt: string }): React.JSX.Element {
  const [status, setStatus] = useState<PosterStatus>('loading');

  return (
    <>
      {status !== 'loaded' && <PosterPlaceholder status={status} />}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onLoad={() => setStatus('loaded')}
        onError={() => setStatus('error')}
        className={`w-full h-full object-cover transition-all duration-300 group-hover:scale-105 ${
          status === 'loaded' ? 'opacity-100' : 'absolute inset-0 opacity-0 pointer-events-none'
        }`}
      />
    </>
  );
}

export function MediaCard({ item, selected, onSelect }: MediaCardProps): React.JSX.Element {
  const { t } = useTranslation();

  const isMatched = item.totalCount > 0 && item.hasSubCount === item.totalCount;

  const getSubtitleStatusText = (): string => {
    if (item.totalCount === 0) {
      return '';
    }

    if (item.allowNoSubtitle) {
      return t('status.noSubtitleNeeded');
    }

    if (isMatched) {
      return t('status.matched');
    }

    if (item.hasSubCount === 0) {
      return t('status.missing');
    }

    return t('status.matchedCount', { has: item.hasSubCount, total: item.totalCount });
  };

  const statusText = getSubtitleStatusText();

  return (
    <div
      onClick={() => onSelect(item.id)}
      className={`group relative flex flex-col rounded-2xl overflow-hidden cursor-pointer transition-all duration-300 hover:-translate-y-1 ${
        selected
          ? 'ring-2 ring-primary shadow-[0_0_20px_rgba(189,194,255,0.25)]'
          : 'ring-1 ring-outline-variant/10 hover:ring-primary/40 hover:shadow-lg'
      } bg-surface-container`}
    >
      <div className="relative aspect-[2/3] w-full bg-surface-container-highest overflow-hidden">
        {item.poster ? (
          <PosterImage key={item.poster} src={item.poster} alt={item.displayTitle} />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <span className="material-symbols-outlined text-4xl text-outline">movie</span>
          </div>
        )}
      </div>

      {statusText && (
        <span
          className={`absolute top-2 right-2 flex items-center px-2 py-0.5 rounded text-[10px] leading-none font-bold tracking-widest uppercase border backdrop-blur-md ${
            item.allowNoSubtitle
              ? 'bg-surface-container-highest/80 text-on-surface-variant border-outline-variant/40'
              : isMatched
                ? 'bg-primary/80 text-on-primary border-primary/40'
                : 'bg-error-dim/80 text-on-surface border-error-dim/40'
          }`}
        >
          {statusText}
        </span>
      )}

      {(item.isAligning || item.alignmentStatus === 'aligned' || item.alignmentStatus === 'misaligned') && (
        <span
          className={`absolute top-2 left-2 flex items-center gap-1 px-2 py-0.5 rounded text-[10px] leading-none font-bold tracking-widest uppercase border backdrop-blur-md ${
            item.isAligning
              ? 'bg-primary/80 text-on-primary border-primary/40'
              : item.alignmentStatus === 'aligned'
                ? 'bg-tertiary/80 text-on-surface border-tertiary/40'
                : 'bg-error/80 text-on-primary border-error/40'
          }`}
        >
          <span
            className={`material-symbols-outlined text-[10px] leading-none ${item.isAligning ? 'animate-spin' : ''}`}
          >
            {item.isAligning ? 'sync' : item.alignmentStatus === 'aligned' ? 'sync' : 'sync_problem'}
          </span>
          {item.isAligning
            ? t('status.aligning')
            : item.alignmentStatus === 'aligned'
              ? t('subtitles.alignment.aligned')
              : t('subtitles.alignment.misaligned')}
        </span>
      )}

      <div className="flex flex-col gap-1 p-3 min-w-0">
        <h3
          className="font-headline font-bold text-sm text-on-surface leading-tight truncate"
          title={item.displayTitle}
        >
          {item.displayTitle}
        </h3>
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-xs font-label text-on-surface-variant shrink-0">{item.year || t('year.unknown')}</p>
          {item.languages && item.languages.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 min-w-0">
              {item.languages.slice(0, 2).map(language => (
                <span
                  key={language}
                  className="px-1.5 py-0.5 rounded bg-surface-container-highest border border-outline-variant/20 text-[9px] font-bold text-primary-fixed tracking-wider whitespace-nowrap"
                >
                  {language}
                </span>
              ))}
              {item.languages.length > 2 && (
                <span className="text-[9px] font-bold text-on-surface-variant">
                  +{item.languages.length - 2}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
