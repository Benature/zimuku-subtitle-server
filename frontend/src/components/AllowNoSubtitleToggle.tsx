import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { setWorkAllowNoSubtitle } from '../api';
import { queryKeys } from '../lib/queryKeys';
import { useToast } from '../hooks/useToast';

interface AllowNoSubtitleToggleProps {
  mediaType: 'movie' | 'tv';
  title: string;
  allowNoSubtitle: boolean;
}

// 「允许无字幕」作品级开关：标记后定时/批量补字幕将跳过该作品，避免重复搜索资源。
export function AllowNoSubtitleToggle({
  mediaType,
  title,
  allowNoSubtitle,
}: AllowNoSubtitleToggleProps): React.JSX.Element {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (allow: boolean) => setWorkAllowNoSubtitle(mediaType, title, allow),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.media.files(mediaType) });
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      showToast(t('mediaConfig.triggerFailed') + ': ' + message, 'error');
    },
  });

  return (
    <div className="flex justify-between items-center gap-4 bg-surface-container/50 p-4 rounded-xl border border-outline-variant/10">
      <div className="flex items-center gap-3 min-w-0">
        <span className="material-symbols-outlined text-on-surface-variant shrink-0">subtitles_off</span>
        <div className="min-w-0">
          <p className="text-sm font-bold text-on-surface">{t('allowNoSubtitle.title')}</p>
          <p className="text-xs text-on-surface-variant">{t('allowNoSubtitle.description')}</p>
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={allowNoSubtitle}
        aria-label={t('allowNoSubtitle.title')}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate(!allowNoSubtitle)}
        className={`relative w-11 h-6 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
          allowNoSubtitle ? 'bg-primary' : 'bg-surface-container-highest'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
            allowNoSubtitle ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}
