import { useState } from 'react';
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
// 点击后立即乐观翻转开关，请求失败时回滚并提示，避免「点击无反应」的体感。
export function AllowNoSubtitleToggle({
  mediaType,
  title,
  allowNoSubtitle,
}: AllowNoSubtitleToggleProps): React.JSX.Element {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  // 乐观状态：记录发起请求时的服务端基准值与目标值；服务端数据刷新（基准值变化）后自动失效
  const [optimistic, setOptimistic] = useState<{ base: boolean; value: boolean } | null>(null);

  const displayedValue =
    optimistic !== null && optimistic.base === allowNoSubtitle ? optimistic.value : allowNoSubtitle;

  const mutation = useMutation({
    mutationFn: (allow: boolean) => setWorkAllowNoSubtitle(mediaType, title, allow),
    onMutate: (allow: boolean) => {
      setOptimistic({ base: displayedValue, value: allow });
    },
    onSuccess: async (_data, allow) => {
      showToast(
        allow ? t('allowNoSubtitle.marked') : t('allowNoSubtitle.unmarked'),
        'success',
      );
      await queryClient.invalidateQueries({ queryKey: queryKeys.media.files(mediaType) });
    },
    onError: (err: unknown) => {
      setOptimistic(null);
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
        aria-checked={displayedValue}
        aria-label={t('allowNoSubtitle.title')}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate(!displayedValue)}
        className={`relative w-11 h-6 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
          displayedValue ? 'bg-primary' : 'bg-surface-container-highest'
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${
            displayedValue ? 'translate-x-5' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  );
}
