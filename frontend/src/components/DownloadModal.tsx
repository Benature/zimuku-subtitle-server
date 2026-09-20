import { useState, useEffect } from 'react';
import { Download, Loader2, ChevronDown, Film, Tv } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import MediaSelector, { type MediaSelection } from './MediaSelector';
import EpisodeSelector from './EpisodeSelector';
import { createDownloadTask, type SearchResult } from '../api';
import { useToast } from '../hooks/useToast';

interface DownloadModalProps {
  isOpen: boolean;
  onClose: () => void;
  subtitle: SearchResult | null;
  onDownload?: () => void;
}

export default function DownloadModal({
  isOpen,
  onClose,
  subtitle,
  onDownload,
}: DownloadModalProps): React.JSX.Element | null {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [selectedLangs, setSelectedLangs] = useState<string[]>([]);
  const [targetMedia, setTargetMedia] = useState<MediaSelection | null>(null);
  const [selectedSeason, setSelectedSeason] = useState<number | undefined>(undefined);
  const [selectedEpisode, setSelectedEpisode] = useState<number | undefined>(undefined);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [customPath, setCustomPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [mediaSelectorType, setMediaSelectorType] = useState<'movie' | 'tv'>('movie');

  useEffect(() => {
    if (subtitle) {
      setSelectedLangs(subtitle.lang || []);
    }
  }, [subtitle]);

  useEffect(() => {
    if (!isOpen) {
      setTargetMedia(null);
      setSelectedSeason(undefined);
      setSelectedEpisode(undefined);
      setShowAdvanced(false);
      setCustomPath('');
    }
  }, [isOpen]);

  const handleMediaSelect = (media: MediaSelection): void => {
    setTargetMedia(media);
    setMediaSelectorType(media.type);
    if (media.type === 'movie') {
      setSelectedSeason(undefined);
      setSelectedEpisode(undefined);
    } else {
      setSelectedEpisode(undefined);
      if (media.season) {
        setSelectedSeason(media.season);
      } else {
        setSelectedSeason(undefined);
      }
    }
  };

  const handleEpisodeSelect = (episode: number): void => {
    setSelectedEpisode(episode);
  };

  const handleLanguageToggle = (language: string): void => {
    setSelectedLangs(prev =>
      prev.includes(language) ? prev.filter(item => item !== language) : [...prev, language]
    );
  };

  const resetEpisodeSelection = (): void => {
    setTargetMedia(null);
    setSelectedSeason(undefined);
    setSelectedEpisode(undefined);
    setMediaSelectorType('tv');
  };

  const customTargetPath = customPath.trim();
  const hasMediaTarget =
    targetMedia !== null &&
    (targetMedia.type === 'movie' ||
      (selectedSeason !== undefined && selectedEpisode !== undefined));
  const canDownload =
    subtitle !== null &&
    selectedLangs.length > 0 &&
    (customTargetPath.length > 0 || hasMediaTarget);

  const handleDownload = async (): Promise<void> => {
    if (!subtitle || (!hasMediaTarget && customTargetPath.length === 0)) {
      return;
    }

    setLoading(true);
    try {
      if (hasMediaTarget) {
        await createDownloadTask(
          subtitle.title,
          subtitle.link,
          targetMedia!.path,
          targetMedia!.type as 'movie' | 'tv',
          selectedSeason,
          selectedEpisode,
          selectedLangs[0]
        );
      } else {
        await createDownloadTask(subtitle.title, subtitle.link, customTargetPath);
      }
      onDownload?.();
      onClose();
      showToast(t('download.downloadAdded'), 'success');
    } catch (err) {
      console.error('Download failed:', err);
      showToast(t('download.downloadFailed'), 'error');
    } finally {
      setLoading(false);
    }
  };

  if (!subtitle) {
    return null;
  }

  const availableLangs = subtitle.lang || [
    t('searchFilter.simplified'),
    t('searchFilter.traditional'),
    t('searchFilter.english'),
    t('searchFilter.bilingual'),
  ];

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('download.associateSubtitle')}>
      <div className="flex flex-col gap-4">
        <div className="space-y-1">
          <div className="space-y-0.5">
            <h3 className="text-xl font-headline font-extrabold text-on-surface leading-tight break-all">
              {subtitle.title}
            </h3>
            <div className="flex items-center gap-2 text-sm font-label text-on-surface-variant font-medium tracking-wide">
              <span>{subtitle.format || 'SRT'}</span>
              <span className="opacity-30">•</span>
              <span>{selectedLangs.join(' & ') || availableLangs[0]}</span>
              {subtitle.fps && (
                <>
                  <span className="opacity-30">•</span>
                  <span>{subtitle.fps} FPS</span>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-label uppercase tracking-widest text-on-surface-variant font-bold opacity-70">
              {t('download.selectLanguage')}
            </label>
            <div className="flex flex-wrap gap-2">
              {availableLangs.map(lang => (
                <button
                  key={lang}
                  onClick={() => handleLanguageToggle(lang)}
                  className={`px-4 py-2 rounded-lg text-sm font-bold transition-all duration-300 border ${
                    selectedLangs.includes(lang)
                      ? 'bg-primary text-on-primary border-primary shadow-[0_0_15px_rgba(189,194,255,0.2)]'
                      : 'bg-surface-container text-on-surface-variant border-outline-variant/10 hover:border-primary/30 hover:text-on-surface'
                  }`}
                >
                  {lang}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-xs font-label uppercase tracking-widest text-on-surface-variant font-bold opacity-70">
              {t('download.selectTargetMedia')}
            </label>

            <div className="bg-surface-container-low rounded-xl p-0.5 border border-outline-variant/5">
              {targetMedia && targetMedia.type === 'tv' && !selectedEpisode ? (
                <EpisodeSelector
                  seriesTitle={targetMedia.title}
                  season={selectedSeason || 1}
                  episodes={targetMedia.episodes || []}
                  onSelect={handleEpisodeSelect}
                  onBack={resetEpisodeSelection}
                />
              ) : (
                <MediaSelector onSelect={handleMediaSelect} defaultType={mediaSelectorType} />
              )}
            </div>

            {targetMedia && (
              <div className="group relative overflow-hidden bg-surface-container-high/40 rounded-xl p-4 border border-outline-variant/5 transition-all duration-500 animate-in fade-in slide-in-from-bottom-1">
                <div className="flex items-center gap-4 relative z-10">
                  <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 text-primary">
                    {targetMedia.type === 'movie' ? (
                      <Film className="w-5 h-5" />
                    ) : (
                      <Tv className="w-5 h-5" />
                    )}
                  </div>
                  <div className="space-y-0.5 min-w-0">
                    <p className="text-[10px] font-label uppercase tracking-widest text-on-surface-variant font-bold opacity-50">
                      {targetMedia.type === 'movie' ? t('movie') : t('tv')}
                    </p>
                    <h4 className="text-sm font-headline font-bold text-on-surface truncate">
                      {targetMedia.title}
                    </h4>
                    {targetMedia.type === 'tv' && selectedSeason && (
                      <p className="text-[11px] font-body text-primary font-semibold">
                        {t('page.series.season', { n: selectedSeason })}
                        {selectedEpisode && ` · ${t('episodeSelector.episode', { n: selectedEpisode.toString().padStart(2, '0') })}`}
                      </p>
                    )}
                    {targetMedia.type === 'movie' && targetMedia.year && (
                      <p className="text-[11px] font-body text-on-surface-variant">
                        {targetMedia.year}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-xs font-label font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-all duration-300 group"
            >
              <div className={`transition-transform duration-300 ${showAdvanced ? 'rotate-180' : ''}`}>
                <ChevronDown className="w-4 h-4" />
              </div>
              {t('download.advancedOptions')}
              <div className="h-px w-8 bg-outline-variant/10 ml-1 group-hover:bg-outline-variant/30 transition-colors" />
            </button>

            {showAdvanced && (
              <div className="space-y-2 animate-in fade-in slide-in-from-top-1 duration-300">
                <div className="relative group">
                  <input
                    type="text"
                    value={customPath}
                    onChange={e => setCustomPath(e.target.value)}
                    placeholder={t('download.customPathPlaceholder')}
                    className="w-full bg-surface-container-low px-4 py-3 text-sm border border-outline-variant/10 rounded-xl outline-none focus:border-primary/50 focus:bg-surface-container transition-all"
                  />
                </div>
                <p className="text-[11px] text-on-surface-variant/50 font-body px-1 leading-relaxed">
                  {t('download.customPathNote')}
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="pt-0">
          <button
            onClick={handleDownload}
            disabled={!canDownload || loading}
            className={`w-full py-4 rounded-xl font-headline font-extrabold text-sm uppercase tracking-widest transition-all duration-500 flex items-center justify-center gap-2 active:scale-[0.98] ${
              canDownload && !loading
                ? 'bg-gradient-to-br from-primary to-primary-container text-on-primary shadow-lg shadow-primary/20 hover:shadow-primary/30 hover:-translate-y-0.5'
                : 'bg-surface-container-highest/20 text-on-surface-variant border border-outline-variant/10 cursor-not-allowed'
            }`}
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                {t('download.adding')}
              </>
            ) : (
              <>
                <Download className="w-5 h-5" />
                {t('download.startDownload')}
              </>
            )}
          </button>
        </div>
      </div>
    </Modal>
  );
}
