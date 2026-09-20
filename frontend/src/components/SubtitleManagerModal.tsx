import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  alignMediaSubtitle,
  fetchAlignerStatus,
  fetchExistingSubtitles,
  restoreMediaSubtitle,
  type AlignerStatus,
  type ExistingSubtitle,
  type ScannedFile,
} from '../api';
import Modal from './Modal';
import ConfirmDialog from './ConfirmDialog';

interface SubtitleManagerModalProps {
  isOpen: boolean;
  onClose: () => void;
  file: ScannedFile;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

interface AlignmentBadgeStyle {
  className: string;
  icon: string;
}

function getAlignmentBadgeStyle(status: ExistingSubtitle['alignment_status']): AlignmentBadgeStyle {
  switch (status) {
    case 'aligned':
      return {
        className: 'bg-primary/10 text-primary border border-primary/20',
        icon: 'check_circle',
      };
    case 'misaligned':
      return {
        className: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
        icon: 'warning',
      };
    default:
      return {
        className: 'bg-surface-container-highest text-on-surface-variant border border-outline-variant/15',
        icon: 'help',
      };
  }
}

function formatShift(ms: number): string {
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(1)}s`;
  }
  return `${Math.round(ms)}ms`;
}

export function SubtitleManagerModal({
  isOpen,
  onClose,
  file,
}: SubtitleManagerModalProps): React.JSX.Element | null {
  const { t } = useTranslation();
  const [subtitles, setSubtitles] = useState<ExistingSubtitle[]>([]);
  const [alignerStatus, setAlignerStatus] = useState<AlignerStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [aligningFile, setAligningFile] = useState<string | null>(null);
  const [restoringFile, setRestoringFile] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  const loadData = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    setNotice(null);
    try {
      const [subs, status] = await Promise.all([
        fetchExistingSubtitles(file.id),
        fetchAlignerStatus().catch(() => null),
      ]);
      setSubtitles(subs);
      setAlignerStatus(status);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ type: 'error', message: msg });
    } finally {
      setLoading(false);
    }
  }, [file.id, isOpen]);

  useEffect(() => {
    if (isOpen) {
      void loadData();
    }
  }, [isOpen, loadData]);

  const handleAlign = async (filename: string) => {
    setAligningFile(filename);
    setNotice(null);
    try {
      const res = await alignMediaSubtitle(file.id, filename);
      setNotice({ type: 'success', message: res.message || t('subtitles.alignSuccess') });
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ type: 'error', message: msg });
    } finally {
      setAligningFile(null);
    }
  };

  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);

  const handleRestore = (filename: string) => {
    setRestoreTarget(filename);
  };

  const confirmRestore = async () => {
    const filename = restoreTarget;
    setRestoreTarget(null);
    if (!filename) return;
    setRestoringFile(filename);
    setNotice(null);
    try {
      const res = await restoreMediaSubtitle(file.id, filename);
      setNotice({ type: 'success', message: res.message || t('subtitles.restoreSuccess') });
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setNotice({ type: 'error', message: msg });
    } finally {
      setRestoringFile(null);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={t('subtitles.manageTitle')}>
      <div className="flex flex-col gap-4">
        {/* 顶部视频信息 */}
        <div className="bg-surface-container/50 p-3 rounded-xl border border-outline-variant/10 text-xs">
          <div className="font-bold text-on-surface truncate" title={file.filename}>
            {file.filename}
          </div>
        </div>

        {/* 对齐组件可用性提示 */}
        {alignerStatus && !alignerStatus.available && (
          <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-amber-300 text-xs flex items-center gap-2">
            <span className="material-symbols-outlined text-base">warning</span>
            <span>{alignerStatus.message || t('subtitles.toolUnavailable')}</span>
          </div>
        )}

        {/* 成功 / 错误提示 */}
        {notice && (
          <div
            className={`p-3 rounded-xl text-xs flex items-center gap-2 ${
              notice.type === 'success'
                ? 'bg-primary/10 border border-primary/20 text-primary'
                : 'bg-error-dim/10 border border-error-dim/20 text-error-dim'
            }`}
          >
            <span className="material-symbols-outlined text-base">
              {notice.type === 'success' ? 'check_circle' : 'error'}
            </span>
            <span className="flex-1">{notice.message}</span>
          </div>
        )}

        {/* 字幕文件列表 */}
        {loading ? (
          <div className="py-8 flex flex-col items-center justify-center text-on-surface-variant gap-2">
            <span className="material-symbols-outlined text-2xl animate-spin">sync</span>
            <span className="text-xs">加载字幕信息...</span>
          </div>
        ) : subtitles.length === 0 ? (
          <div className="py-8 text-center text-on-surface-variant text-xs">
            {t('subtitles.noSubtitles')}
          </div>
        ) : (
          <div className="flex flex-col gap-3 max-h-[50vh] overflow-y-auto custom-scrollbar pr-1">
            {subtitles.map(sub => {
              const isAligning = aligningFile === sub.filename;
              const isRestoring = restoringFile === sub.filename;
              const isBusy = isAligning || isRestoring;
              const canAlign = alignerStatus ? alignerStatus.available : true;

              return (
                <div
                  key={sub.filename}
                  className="bg-surface-container/60 hover:bg-surface-container p-3.5 rounded-xl border border-outline-variant/10 flex flex-col gap-2.5 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-bold text-on-surface truncate" title={sub.filename}>
                        {sub.filename}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5 text-[11px]">
                        <span className="px-1.5 py-0.5 rounded bg-surface-container-highest font-mono uppercase text-on-surface-variant">
                          {sub.format.replace('.', '')}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">
                          {sub.detected_language_name || sub.detected_language}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-surface-container-highest text-on-surface-variant">
                          {sub.encoding}
                        </span>
                        <span className="text-on-surface-variant/80 font-mono">
                          {formatBytes(sub.size_bytes)}
                        </span>
                        {(() => {
                          const badge = getAlignmentBadgeStyle(sub.alignment_status);
                          const shiftText =
                            sub.alignment_status === 'misaligned' && sub.alignment_max_shift_ms != null
                              ? ` (${formatShift(sub.alignment_max_shift_ms)})`
                              : '';
                          return (
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-medium flex items-center gap-1 ${badge.className}`}
                              title={t(`subtitles.alignment.${sub.alignment_status}Description`)}
                            >
                              <span className="material-symbols-outlined text-[12px]">{badge.icon}</span>
                              {t(`subtitles.alignment.${sub.alignment_status}`)}
                              {shiftText}
                            </span>
                          );
                        })()}
                        {sub.has_backup && (
                          <span className="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[10px] font-medium">
                            {t('subtitles.hasBackup')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 底部按钮栏 */}
                  <div className="flex items-center justify-end gap-2 pt-1 border-t border-outline-variant/5">
                    {sub.has_backup && (
                      <button
                        onClick={() => void handleRestore(sub.filename)}
                        disabled={isBusy}
                        className="px-2.5 py-1.5 rounded-lg bg-surface-container-highest/60 hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface text-xs font-bold transition-all flex items-center gap-1.5 disabled:opacity-50"
                        title={t('subtitles.restore')}
                      >
                        {isRestoring ? (
                          <span className="material-symbols-outlined text-sm animate-spin">sync</span>
                        ) : (
                          <span className="material-symbols-outlined text-sm">history</span>
                        )}
                        <span>{isRestoring ? t('subtitles.restoring') : t('subtitles.restore')}</span>
                      </button>
                    )}

                    <button
                      onClick={() => void handleAlign(sub.filename)}
                      disabled={isBusy || !canAlign || sub.is_binary}
                      className="px-3 py-1.5 rounded-lg bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 text-xs font-bold transition-all flex items-center gap-1.5 disabled:opacity-40"
                      title={t('subtitles.align')}
                    >
                      {isAligning ? (
                        <span className="material-symbols-outlined text-sm animate-spin">sync</span>
                      ) : (
                        <span className="material-symbols-outlined text-sm">graphic_eq</span>
                      )}
                      <span>{isAligning ? t('subtitles.aligning') : t('subtitles.align')}</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <ConfirmDialog
        isOpen={restoreTarget !== null}
        message={restoreTarget ? t('subtitles.restoreConfirm', { filename: restoreTarget }) : ''}
        onCancel={() => setRestoreTarget(null)}
        onConfirm={() => void confirmRestore()}
      />
    </Modal>
  );
}
