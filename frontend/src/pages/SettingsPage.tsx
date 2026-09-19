import { useState } from 'react';
import { Languages, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { changeLanguage } from '../i18n';
import { supportedLanguages } from '../i18n/config';
import { useMediaPolling } from '../hooks/useMediaPolling';
import {
  useAddMediaPathMutation,
  useDeleteMediaPathMutation,
  useSettingsQuery,
  useSubtitleLanguagesQuery,
  useTriggerMediaMatchMutation,
  useUpdateSettingMutation,
} from '../hooks/queries';

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  const { paths: moviePaths, fetchData: fetchMoviePaths, status, setIsScanningOptimistic } =
    useMediaPolling('movie');
  const { paths: tvPaths, fetchData: fetchTvPaths } = useMediaPolling('tv');

  const [newMoviePath, setNewMoviePath] = useState('');
  const [newTvPath, setNewTvPath] = useState('');
  const settingsQuery = useSettingsQuery();
  const subtitleLanguagesQuery = useSubtitleLanguagesQuery();
  const updateSettingMutation = useUpdateSettingMutation();
  const addMediaPathMutation = useAddMediaPathMutation();
  const deleteMediaPathMutation = useDeleteMediaPathMutation();
  const triggerMediaMatchMutation = useTriggerMediaMatchMutation();
  const settings = settingsQuery.data ?? [];

  const pathInputs = {
    movie: newMoviePath,
    tv: newTvPath,
  } as const;

  const refreshMediaPaths = async (type: 'movie' | 'tv'): Promise<void> => {
    if (type === 'movie') {
      await fetchMoviePaths();
      return;
    }

    await fetchTvPaths();
  };

  const handleSaveSetting = async (key: string): Promise<void> => {
    try {
      const setting = settings.find(s => s.key === key);
      const newValue = formValues[key] ?? setting?.value ?? '';
      await updateSettingMutation.mutateAsync({
        key,
        value: newValue,
        description: setting?.description,
      });
      alert(t('page.settings.saved'));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(t('page.settings.saveFailed') + ': ' + message);
    }
  };

  const handleLanguageChange = (lang: string): void => {
    changeLanguage(lang);
  };

  const handleAddPath = async (type: 'movie' | 'tv', path: string): Promise<void> => {
    if (!path) return;
    try {
      await addMediaPathMutation.mutateAsync({ path, pathType: type });
      if (type === 'movie') {
        setNewMoviePath('');
      } else {
        setNewTvPath('');
      }

      await refreshMediaPaths(type);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(t('mediaConfig.addFailed') + ': ' + message);
    }
  };

  const handleDeletePath = async (id: number, type: 'movie' | 'tv'): Promise<void> => {
    if (!window.confirm(t('confirm.deletePath'))) return;
    await deleteMediaPathMutation.mutateAsync({ id, pathType: type });
    await refreshMediaPaths(type);
  };

  const handleRefreshLibrary = async (type: 'movie' | 'tv'): Promise<void> => {
    try {
      setIsScanningOptimistic(true);
      setTimeout(() => setIsScanningOptimistic(false), 3000);
      await triggerMediaMatchMutation.mutateAsync(type);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert(t('mediaConfig.triggerFailed') + ': ' + message);
    }
  };

  return (
    <div className="flex-1 w-full h-full max-w-[1400px] mx-auto overflow-y-auto custom-scrollbar px-8 py-10">
      <header className="flex items-center justify-between pb-10">
        <div className="flex flex-col gap-3">
          <h1 className="text-4xl font-headline font-extrabold tracking-tight text-on-surface leading-none">
            {t('page.settings.title')}
          </h1>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-8 pb-12">
        <section className="md:col-span-7 bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high relative overflow-hidden group border border-outline-variant/10">
          <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
            <span className="material-symbols-outlined text-8xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              tune
            </span>
          </div>
          <div className="flex items-center gap-3 mb-8 relative z-10">
            <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>
              language
            </span>
            <h3 className="font-headline font-bold text-xl text-on-surface">{t('page.settings.general')}</h3>
          </div>
          <div className="space-y-8 relative z-10">
            <div className="flex flex-col gap-3">
              <label className="text-sm font-label text-on-surface-variant font-bold uppercase tracking-wider">
                {t('page.settings.language')}
              </label>
              <select
                value={i18n.language}
                onChange={e => handleLanguageChange(e.target.value)}
                className="bg-surface-container-low border border-outline-variant/20 rounded-xl p-3 text-on-surface font-body w-full max-w-sm focus:ring-1 focus:ring-primary/50 outline-none transition-all cursor-pointer"
              >
                {supportedLanguages.map(lang => (
                  <option key={lang.code} value={lang.code}>
                    {lang.nativeLabel}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        <section className="md:col-span-5 bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
          <div className="flex items-center gap-3 mb-8">
            <span className="material-symbols-outlined text-tertiary" style={{ fontVariationSettings: "'FILL' 1" }}>
              robot_2
            </span>
            <h3 className="font-headline font-bold text-xl text-on-surface">{t('page.settings.systemProperties')}</h3>
          </div>
          <div className="space-y-4 max-h-[400px] overflow-y-auto custom-scrollbar pr-2">
            {settings.length === 0 ? (
              <div className="p-4 text-center text-on-surface-variant opacity-70 text-sm">
                {t('page.settings.noConfig')}
              </div>
            ) : (
              settings.map(setting => (
                <div
                  key={setting.id}
                  className="p-4 rounded-xl border border-outline-variant/15 hover:bg-surface-container-highest transition-colors flex flex-col gap-3"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-sm font-label font-bold text-on-surface">{setting.key}</span>
                      {setting.description && (
                        <p className="text-[10px] text-on-surface-variant mt-0.5">{setting.description}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      // 未编辑时直接回退到服务端值，避免为了同步 query 结果再额外维护 effect。
                      value={formValues[setting.key] ?? setting.value ?? ''}
                      onChange={e => setFormValues(prev => ({ ...prev, [setting.key]: e.target.value }))}
                      className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                    />
                    <button
                      onClick={() => handleSaveSetting(setting.key)}
                      className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                    >
                      {t('page.settings.save')}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="md:col-span-12 bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
          <div className="flex items-center gap-3 mb-6">
            <Languages className="w-5 h-5 text-primary" aria-hidden="true" />
            <div>
              <h3 className="font-headline font-bold text-xl text-on-surface">
                {t('page.settings.subtitleLanguages')}
              </h3>
              <p className="text-xs text-on-surface-variant mt-1">
                {t('page.settings.subtitleLanguagesDescription')}
              </p>
            </div>
          </div>

          {subtitleLanguagesQuery.isPending ? (
            <div className="py-6 text-sm text-on-surface-variant" role="status">
              {t('page.settings.subtitleLanguagesLoading')}
            </div>
          ) : subtitleLanguagesQuery.isError ? (
            <div className="flex items-center justify-between gap-4 py-4 border-t border-outline-variant/10">
              <span className="text-sm text-error">{t('page.settings.subtitleLanguagesError')}</span>
              <button
                type="button"
                onClick={() => subtitleLanguagesQuery.refetch()}
                className="w-9 h-9 shrink-0 inline-flex items-center justify-center rounded-lg text-primary hover:bg-primary/10 transition-colors"
                title={t('action.retry')}
                aria-label={t('action.retry')}
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto border-t border-outline-variant/10">
              <table className="w-full text-left">
                <thead>
                  <tr className="text-xs text-on-surface-variant">
                    <th className="py-3 pr-4 font-label font-bold">{t('page.settings.languageName')}</th>
                    <th className="py-3 px-4 font-label font-bold">{t('page.settings.languageCode')}</th>
                    <th className="py-3 pl-4 font-label font-bold">{t('page.settings.filenameTag')}</th>
                  </tr>
                </thead>
                <tbody>
                  {(subtitleLanguagesQuery.data ?? []).map(language => (
                    <tr key={language.code} className="border-t border-outline-variant/10 text-sm">
                      <td className="py-3 pr-4 text-on-surface font-medium">{language.display_name}</td>
                      <td className="py-3 px-4 text-on-surface-variant font-mono">{language.code}</td>
                      <td className="py-3 pl-4 text-on-surface-variant font-mono">{language.filename_tag}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="md:col-span-12 bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
          <div className="flex items-center justify-between mb-8">
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-primary-dim" style={{ fontVariationSettings: "'FILL' 1" }}>
                folder_managed
              </span>
              <h3 className="font-headline font-bold text-xl text-on-surface">{t('page.settings.digitalLibraries')}</h3>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-4 bg-surface-container-low p-6 rounded-2xl border border-outline-variant/5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex flex-col">
                  <span className="font-bold text-lg text-on-surface">{t('page.settings.moviesDirectory')}</span>
                  <span className="text-xs text-on-surface-variant">{t('page.settings.moviesSub')}</span>
                </div>
                <button
                  onClick={() => handleRefreshLibrary('movie')}
                  className="w-8 h-8 rounded-full bg-surface-container flex items-center justify-center text-primary hover:bg-primary hover:text-surface-container transition-colors"
                  title={t('mediaConfig.refreshMovie')}
                >
                  <span className={`material-symbols-outlined text-sm ${status.is_scanning ? 'animate-spin' : ''}`}>
                    sync
                  </span>
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder={t('mediaConfig.inputPathPlaceholder')}
                  value={newMoviePath}
                  onChange={e => setNewMoviePath(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddPath('movie', pathInputs.movie)}
                  className="flex-1 bg-surface-container border border-outline-variant/10 rounded-lg p-2.5 text-sm text-on-surface outline-none focus:border-primary/50 transition-colors"
                />
                <button
                  onClick={() => handleAddPath('movie', pathInputs.movie)}
                  className="bg-primary/10 hover:bg-primary/20 text-primary px-4 py-2.5 rounded-lg text-sm font-bold transition-all"
                >
                  {t('page.settings.add')}
                </button>
              </div>
              <div className="flex flex-col gap-2 mt-4 max-h-64 overflow-y-auto custom-scrollbar pr-1">
                {moviePaths.length === 0 ? (
                  <div className="text-center text-xs text-on-surface-variant py-4 opacity-50">
                    {t('page.settings.noDirectories')}
                  </div>
                ) : (
                  moviePaths.map(path => (
                    <div
                      key={path.id}
                      className="p-3 bg-surface-container rounded-lg flex items-center justify-between group"
                    >
                      <div className="flex items-center gap-3 overflow-hidden">
                        <span className="material-symbols-outlined text-outline text-sm shrink-0">movie</span>
                        <span className="text-xs font-mono text-on-surface-variant truncate">{path.path}</span>
                      </div>
                      <button
                        onClick={() => handleDeletePath(path.id, 'movie')}
                        className="opacity-0 group-hover:opacity-100 text-error hover:bg-error/10 p-1.5 rounded transition-all"
                      >
                        <span className="material-symbols-outlined text-sm">delete</span>
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="space-y-4 bg-surface-container-low p-6 rounded-2xl border border-outline-variant/5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex flex-col">
                  <span className="font-bold text-lg text-on-surface">{t('page.settings.tvDirectory')}</span>
                  <span className="text-xs text-on-surface-variant">{t('page.settings.tvSub')}</span>
                </div>
                <button
                  onClick={() => handleRefreshLibrary('tv')}
                  className="w-8 h-8 rounded-full bg-surface-container flex items-center justify-center text-primary hover:bg-primary hover:text-surface-container transition-colors"
                  title={t('mediaConfig.refreshTv')}
                >
                  <span className={`material-symbols-outlined text-sm ${status.is_scanning ? 'animate-spin' : ''}`}>
                    sync
                  </span>
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder={t('mediaConfig.inputTvPathPlaceholder')}
                  value={newTvPath}
                  onChange={e => setNewTvPath(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleAddPath('tv', pathInputs.tv)}
                  className="flex-1 bg-surface-container border border-outline-variant/10 rounded-lg p-2.5 text-sm text-on-surface outline-none focus:border-primary/50 transition-colors"
                />
                <button
                  onClick={() => handleAddPath('tv', pathInputs.tv)}
                  className="bg-primary/10 hover:bg-primary/20 text-primary px-4 py-2.5 rounded-lg text-sm font-bold transition-all"
                >
                  {t('page.settings.add')}
                </button>
              </div>
              <div className="flex flex-col gap-2 mt-4 max-h-64 overflow-y-auto custom-scrollbar pr-1">
                {tvPaths.length === 0 ? (
                  <div className="text-center text-xs text-on-surface-variant py-4 opacity-50">
                    {t('page.settings.noDirectories')}
                  </div>
                ) : (
                  tvPaths.map(path => (
                    <div
                      key={path.id}
                      className="p-3 bg-surface-container rounded-lg flex items-center justify-between group"
                    >
                      <div className="flex items-center gap-3 overflow-hidden">
                        <span className="material-symbols-outlined text-outline text-sm shrink-0">tv</span>
                        <span className="text-xs font-mono text-on-surface-variant truncate">{path.path}</span>
                      </div>
                      <button
                        onClick={() => handleDeletePath(path.id, 'tv')}
                        className="opacity-0 group-hover:opacity-100 text-error hover:bg-error/10 p-1.5 rounded transition-all"
                      >
                        <span className="material-symbols-outlined text-sm">delete</span>
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
