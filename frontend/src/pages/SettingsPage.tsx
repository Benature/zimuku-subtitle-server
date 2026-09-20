import { useState } from 'react';
import { Languages, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { changeLanguage } from '../i18n';
import { supportedLanguages } from '../i18n/config';
import { useMediaPolling } from '../hooks/useMediaPolling';
import { useToast } from '../hooks/useToast';
import {
  useAddMediaPathMutation,
  useDeleteMediaPathMutation,
  useFeishuTestMutation,
  useMediaServerTestMutation,
  useRunScheduleNowMutation,
  useScheduleStatusQuery,
  useSettingsQuery,
  useSubtitleLanguagesQuery,
  useTriggerMediaMatchMutation,
  useUpdateSettingMutation,
} from '../hooks/queries';

// 已有专属卡片/开关的设置 key，不再在「系统属性」通用列表中重复展示
const DEDICATED_SETTING_KEYS = new Set([
  'auto_align_after_download',
  'schedule_enabled',
  'schedule_cron',
  'schedule_max_works_per_run',
  'feishu_notify_enabled',
  'feishu_webhook_url',
  'feishu_webhook_secret',
  'media_server_enabled',
  'media_server_type',
  'media_server_base_url',
  'media_server_api_key',
  'media_server_user_id',
]);

const MEDIA_SERVER_TYPES = ['jellyfin', 'emby', 'plex'] as const;

export default function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
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
  const genericSettings = settings.filter(s => !DEDICATED_SETTING_KEYS.has(s.key));
  const autoAlignSetting = settings.find(s => s.key === 'auto_align_after_download');
  const autoAlignEnabled = (autoAlignSetting?.value ?? 'true') === 'true';

  const scheduleStatusQuery = useScheduleStatusQuery();
  const runScheduleNowMutation = useRunScheduleNowMutation();
  const feishuTestMutation = useFeishuTestMutation();
  const scheduleStatus = scheduleStatusQuery.data;
  const scheduleEnabled = (settings.find(s => s.key === 'schedule_enabled')?.value ?? 'false') === 'true';
  const scheduleCron = settings.find(s => s.key === 'schedule_cron')?.value ?? '0 3 * * *';
  const scheduleMaxWorks = settings.find(s => s.key === 'schedule_max_works_per_run')?.value ?? '1';
  const feishuEnabled = (settings.find(s => s.key === 'feishu_notify_enabled')?.value ?? 'false') === 'true';
  const feishuWebhook = settings.find(s => s.key === 'feishu_webhook_url')?.value ?? '';
  const feishuSecret = settings.find(s => s.key === 'feishu_webhook_secret')?.value ?? '';
  const mediaServerTestMutation = useMediaServerTestMutation();
  const mediaServerEnabled = (settings.find(s => s.key === 'media_server_enabled')?.value ?? 'false') === 'true';
  const mediaServerType = settings.find(s => s.key === 'media_server_type')?.value ?? 'jellyfin';
  const mediaServerBaseUrl = settings.find(s => s.key === 'media_server_base_url')?.value ?? '';
  const mediaServerApiKey = settings.find(s => s.key === 'media_server_api_key')?.value ?? '';
  const mediaServerUserId = settings.find(s => s.key === 'media_server_user_id')?.value ?? '';
  const effectiveMediaServerType = formValues['media_server_type'] ?? mediaServerType;

  const handleToggleSetting = async (key: string, current: boolean): Promise<void> => {
    try {
      const setting = settings.find(s => s.key === key);
      await updateSettingMutation.mutateAsync({
        key,
        value: current ? 'false' : 'true',
        description: setting?.description,
      });
      await scheduleStatusQuery.refetch();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.saveFailed') + ': ' + message, 'error');
    }
  };

  const handleRunScheduleNow = async (): Promise<void> => {
    try {
      await runScheduleNowMutation.mutateAsync();
      showToast(t('page.settings.scheduleRunStarted'), 'success');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.scheduleRunFailed') + ': ' + message, 'error');
    }
  };

  const handleFeishuTest = async (): Promise<void> => {
    try {
      const result = await feishuTestMutation.mutateAsync();
      showToast(result.message, 'success');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.saveFailed') + ': ' + message, 'error');
    }
  };

  const handleMediaServerTest = async (): Promise<void> => {
    try {
      const result = await mediaServerTestMutation.mutateAsync();
      showToast(result.message, result.connected ? 'success' : 'error');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.saveFailed') + ': ' + message, 'error');
    }
  };

  const handleToggleAutoAlign = async (): Promise<void> => {
    try {
      await updateSettingMutation.mutateAsync({
        key: 'auto_align_after_download',
        value: autoAlignEnabled ? 'false' : 'true',
        description: autoAlignSetting?.description,
      });
      await settingsQuery.refetch();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.saveFailed') + ': ' + message, 'error');
    }
  };

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
      showToast(t('page.settings.saved'), 'success');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('page.settings.saveFailed') + ': ' + message, 'error');
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
      showToast(t('mediaConfig.addFailed') + ': ' + message, 'error');
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
      showToast(t('mediaConfig.triggerFailed') + ': ' + message, 'error');
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

            <div className="flex items-center justify-between gap-4 bg-surface-container-low border border-outline-variant/15 rounded-xl p-4 max-w-md">
              <div className="flex flex-col gap-1 min-w-0">
                <span className="text-sm font-label font-bold text-on-surface flex items-center gap-2">
                  <span className="material-symbols-outlined text-base text-primary">graphic_eq</span>
                  {t('page.settings.autoAlign')}
                </span>
                <span className="text-[11px] text-on-surface-variant leading-relaxed">
                  {t('page.settings.autoAlignDescription')}
                </span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={autoAlignEnabled}
                onClick={handleToggleAutoAlign}
                disabled={updateSettingMutation.isPending}
                className={`shrink-0 w-12 h-7 rounded-full p-1 transition-colors duration-200 disabled:opacity-50 ${
                  autoAlignEnabled ? 'bg-primary' : 'bg-surface-container-highest'
                }`}
              >
                <span
                  className={`block w-5 h-5 rounded-full bg-white shadow transition-transform duration-200 ${
                    autoAlignEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
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
            {genericSettings.length === 0 ? (
              <div className="p-4 text-center text-on-surface-variant opacity-70 text-sm">
                {t('page.settings.noConfig')}
              </div>
            ) : (
              genericSettings.map(setting => (
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

        <section className="md:col-span-12 grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>
                  schedule
                </span>
                <div>
                  <h3 className="font-headline font-bold text-xl text-on-surface">{t('page.settings.scheduleTitle')}</h3>
                  <p className="text-xs text-on-surface-variant mt-1">{t('page.settings.scheduleDescription')}</p>
                </div>
              </div>
              <button
                onClick={() => handleToggleSetting('schedule_enabled', scheduleEnabled)}
                className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${
                  scheduleEnabled ? 'bg-primary' : 'bg-surface-container-highest'
                }`}
                title={t('page.settings.scheduleEnabled')}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    scheduleEnabled ? 'translate-x-5' : ''
                  }`}
                />
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={formValues['schedule_cron'] ?? scheduleCron}
                  onChange={e => setFormValues(prev => ({ ...prev, schedule_cron: e.target.value }))}
                  placeholder={t('page.settings.scheduleCronPlaceholder')}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <button
                  onClick={() => handleSaveSetting('schedule_cron')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={0}
                  value={formValues['schedule_max_works_per_run'] ?? scheduleMaxWorks}
                  onChange={e => setFormValues(prev => ({ ...prev, schedule_max_works_per_run: e.target.value }))}
                  className="w-28 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <span className="flex-1 text-xs text-on-surface-variant">{t('page.settings.scheduleMaxWorks')}</span>
                <button
                  onClick={() => handleSaveSetting('schedule_max_works_per_run')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <div className="text-xs text-on-surface-variant space-y-1">
                <div>
                  {t('page.settings.scheduleNextRun')}：
                  {scheduleStatus?.next_run_time
                    ? new Date(scheduleStatus.next_run_time).toLocaleString()
                    : t('page.settings.scheduleNotScheduled')}
                </div>
                {scheduleStatus?.running && <div className="text-primary">{t('page.settings.scheduleRunning')}</div>}
                {scheduleStatus?.last_run && (
                  <div>
                    {t('page.settings.scheduleLastRun')}（{scheduleStatus.last_run.finished_at}）：
                    {scheduleStatus.last_run.error
                      ? t('page.settings.scheduleLastRunError', { error: scheduleStatus.last_run.error })
                      : t('page.settings.scheduleLastRunSummary', {
                          scanned: scheduleStatus.last_run.stats.scanned_files ?? 0,
                          missing: scheduleStatus.last_run.stats.missing_subtitle ?? 0,
                          matched: scheduleStatus.last_run.stats.matched ?? 0,
                          failed: scheduleStatus.last_run.stats.failed ?? 0,
                        })}
                    {!scheduleStatus.last_run.error && (scheduleStatus.last_run.stats.titles?.length ?? 0) > 0 && (
                      <span>
                        ；
                        {t('page.settings.scheduleLastRunWorks', {
                          titles: (scheduleStatus.last_run.stats.titles ?? []).join('、'),
                          remaining: scheduleStatus.last_run.stats.remaining_works ?? 0,
                        })}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <button
                onClick={handleRunScheduleNow}
                disabled={runScheduleNowMutation.isPending}
                className="bg-primary/10 text-primary hover:bg-primary/20 px-4 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-50"
              >
                {t('page.settings.scheduleRunNow')}
              </button>
            </div>
          </div>

          <div className="bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>
                  notifications
                </span>
                <div>
                  <h3 className="font-headline font-bold text-xl text-on-surface">{t('page.settings.feishuTitle')}</h3>
                  <p className="text-xs text-on-surface-variant mt-1">{t('page.settings.feishuDescription')}</p>
                </div>
              </div>
              <button
                onClick={() => handleToggleSetting('feishu_notify_enabled', feishuEnabled)}
                className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${
                  feishuEnabled ? 'bg-primary' : 'bg-surface-container-highest'
                }`}
                title={t('page.settings.feishuEnabled')}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    feishuEnabled ? 'translate-x-5' : ''
                  }`}
                />
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={formValues['feishu_webhook_url'] ?? feishuWebhook}
                  onChange={e => setFormValues(prev => ({ ...prev, feishu_webhook_url: e.target.value }))}
                  placeholder={t('page.settings.feishuWebhookPlaceholder')}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <button
                  onClick={() => handleSaveSetting('feishu_webhook_url')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={formValues['feishu_webhook_secret'] ?? feishuSecret}
                  onChange={e => setFormValues(prev => ({ ...prev, feishu_webhook_secret: e.target.value }))}
                  placeholder={t('page.settings.feishuSecretPlaceholder')}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <button
                  onClick={() => handleSaveSetting('feishu_webhook_secret')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <button
                onClick={handleFeishuTest}
                disabled={feishuTestMutation.isPending}
                className="bg-primary/10 text-primary hover:bg-primary/20 px-4 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-50"
              >
                {feishuTestMutation.isPending ? t('page.settings.feishuTestSending') : t('page.settings.feishuTest')}
              </button>
            </div>
          </div>

          <div className="bg-surface-container rounded-2xl p-8 transition-all duration-300 hover:bg-surface-container-high border border-outline-variant/10">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <span className="material-symbols-outlined text-primary" style={{ fontVariationSettings: "'FILL' 1" }}>
                  tv
                </span>
                <div>
                  <h3 className="font-headline font-bold text-xl text-on-surface">
                    {t('page.settings.mediaServerTitle')}
                  </h3>
                  <p className="text-xs text-on-surface-variant mt-1">{t('page.settings.mediaServerDescription')}</p>
                </div>
              </div>
              <button
                onClick={() => handleToggleSetting('media_server_enabled', mediaServerEnabled)}
                className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${
                  mediaServerEnabled ? 'bg-primary' : 'bg-surface-container-highest'
                }`}
                title={t('page.settings.mediaServerEnabled')}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                    mediaServerEnabled ? 'translate-x-5' : ''
                  }`}
                />
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <select
                  value={effectiveMediaServerType}
                  onChange={e => setFormValues(prev => ({ ...prev, media_server_type: e.target.value }))}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface focus:ring-1 focus:ring-primary/40 outline-none transition-all cursor-pointer"
                >
                  {MEDIA_SERVER_TYPES.map(type => (
                    <option key={type} value={type}>
                      {t(`page.settings.mediaServerType.${type}`)}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => handleSaveSetting('media_server_type')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={formValues['media_server_base_url'] ?? mediaServerBaseUrl}
                  onChange={e => setFormValues(prev => ({ ...prev, media_server_base_url: e.target.value }))}
                  placeholder={t('page.settings.mediaServerBaseUrlPlaceholder')}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <button
                  onClick={() => handleSaveSetting('media_server_base_url')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={formValues['media_server_api_key'] ?? mediaServerApiKey}
                  onChange={e => setFormValues(prev => ({ ...prev, media_server_api_key: e.target.value }))}
                  placeholder={t('page.settings.mediaServerApiKeyPlaceholder')}
                  className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                />
                <button
                  onClick={() => handleSaveSetting('media_server_api_key')}
                  className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                >
                  {t('page.settings.save')}
                </button>
              </div>

              {effectiveMediaServerType !== 'plex' && (
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={formValues['media_server_user_id'] ?? mediaServerUserId}
                    onChange={e => setFormValues(prev => ({ ...prev, media_server_user_id: e.target.value }))}
                    placeholder={t('page.settings.mediaServerUserIdPlaceholder')}
                    className="flex-1 bg-surface-container-lowest border-none rounded-lg p-2 text-sm text-on-surface font-mono focus:ring-1 focus:ring-primary/40 outline-none transition-all"
                  />
                  <button
                    onClick={() => handleSaveSetting('media_server_user_id')}
                    className="bg-primary/10 text-primary hover:bg-primary/20 px-3 py-2 rounded-lg text-sm font-bold transition-colors"
                  >
                    {t('page.settings.save')}
                  </button>
                </div>
              )}

              <button
                onClick={handleMediaServerTest}
                disabled={mediaServerTestMutation.isPending}
                className="bg-primary/10 text-primary hover:bg-primary/20 px-4 py-2 rounded-lg text-sm font-bold transition-colors disabled:opacity-50"
              >
                {mediaServerTestMutation.isPending
                  ? t('page.settings.mediaServerTesting')
                  : t('page.settings.mediaServerTest')}
              </button>
            </div>
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
