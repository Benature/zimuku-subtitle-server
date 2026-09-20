import { useState } from 'react';
import { RefreshCw, Trash2, CheckCircle2, XCircle, Clock, Save, History, Terminal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { alignTaskSubtitle, type Task } from '../api';
import {
  useClearCompletedTasksMutation,
  useDeleteTaskMutation,
  useRetryTaskMutation,
  useTasksQuery,
} from '../hooks/queries';
import { useToast } from '../hooks/useToast';

function TaskSkeleton(): React.JSX.Element {
  return (
    <div className="bg-surface-container rounded-2xl p-5 flex items-center justify-between border border-outline-variant/5 animate-pulse">
      <div className="flex items-center gap-5 flex-1">
        <div className="w-12 h-12 bg-surface-container-highest rounded-xl" />
        <div className="flex flex-col gap-2 flex-1">
          <div className="h-5 bg-surface-container-highest rounded-lg w-1/3" />
          <div className="h-4 bg-surface-container-highest rounded-lg w-1/4" />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="w-10 h-10 bg-surface-container-highest rounded-lg" />
        <div className="w-10 h-10 bg-surface-container-highest rounded-lg" />
      </div>
    </div>
  );
}

function StatusIcon({ status }: { status: Task['status'] }): React.JSX.Element {
  switch (status) {
    case 'completed':
      return (
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center text-primary-dim shadow-inner">
          <CheckCircle2 className="w-6 h-6" />
        </div>
      );
    case 'failed':
      return (
        <div className="w-12 h-12 rounded-xl bg-error-dim/10 flex items-center justify-center text-error-dim shadow-inner">
          <XCircle className="w-6 h-6" />
        </div>
      );
    case 'downloading':
      return (
        <div className="w-12 h-12 rounded-xl bg-secondary-dim/10 flex items-center justify-center text-secondary-dim shadow-inner">
          <RefreshCw className="w-6 h-6 animate-spin" />
        </div>
      );
    default:
      return (
        <div className="w-12 h-12 rounded-xl bg-surface-container-highest flex items-center justify-center text-on-surface-variant shadow-inner">
          <Clock className="w-6 h-6" />
        </div>
      );
  }
}

function getTaskStatusDotClass(status: Task['status']): string {
  switch (status) {
    case 'completed':
      return 'bg-primary';
    case 'failed':
      return 'bg-error-dim';
    case 'downloading':
      return 'bg-secondary';
    default:
      return 'bg-outline';
  }
}

export default function TasksPage() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const tasksQuery = useTasksQuery({
    refetchInterval: 3000,
  });
  const deleteTaskMutation = useDeleteTaskMutation();
  const retryTaskMutation = useRetryTaskMutation();
  const clearCompletedTasksMutation = useClearCompletedTasksMutation();
  const tasks = tasksQuery.data?.items ?? [];
  const loading = tasksQuery.isLoading;
  const [aligningTaskId, setAligningTaskId] = useState<number | null>(null);

  const handleAlignTask = async (id: number): Promise<void> => {
    setAligningTaskId(id);
    try {
      const res = await alignTaskSubtitle(id);
      showToast(res.message || t('subtitles.alignSuccess'), 'success');
      await tasksQuery.refetch();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      showToast(t('mediaConfig.triggerFailed') + ': ' + msg, 'error');
    } finally {
      setAligningTaskId(null);
    }
  };

  const handleDelete = async (id: number): Promise<void> => {
    if (!window.confirm(t('confirm.deleteTask'))) return;
    await deleteTaskMutation.mutateAsync(id);
  };

  const handleRetry = async (id: number): Promise<void> => {
    await retryTaskMutation.mutateAsync(id);
  };

  const handleClear = async (): Promise<void> => {
    if (!window.confirm(t('confirm.clearCompleted'))) return;
    await clearCompletedTasksMutation.mutateAsync();
  };

  return (
    <div className="flex flex-col gap-10 w-full h-full max-w-[1400px] mx-auto overflow-y-auto custom-scrollbar px-8 py-10 pb-12">
      <div className="flex flex-col gap-3">
         <div className="flex items-center justify-between">
            <h1 className="text-4xl font-headline font-extrabold text-on-surface tracking-tight leading-none">
              {t('page.tasks.title')}
            </h1>
            <button
              onClick={handleClear}
              className="group flex items-center gap-2.5 px-5 py-2.5 rounded-xl text-sm font-label font-bold text-on-surface-variant bg-surface-container border border-outline-variant/10 hover:bg-surface-container-highest hover:text-on-surface hover:border-outline-variant/30 transition-all duration-300"
            >
              <Trash2 className="w-4 h-4 group-hover:text-error transition-colors" />
              {t('page.tasks.clearCompleted')}
            </button>
         </div>
      </div>

      <div className="flex flex-col gap-4">
        {loading && tasks.length === 0 ? (
          <div className="space-y-4">
            <TaskSkeleton />
            <TaskSkeleton />
            <TaskSkeleton />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 px-6 bg-surface-container/30 backdrop-blur-md rounded-3xl border border-outline-variant/5">
            <div className="w-16 h-16 rounded-2xl bg-surface-container-highest flex items-center justify-center text-on-surface-variant opacity-20 mb-4">
               <History className="w-8 h-8" />
            </div>
            <p className="text-on-surface-variant font-medium text-lg italic">
              {t('page.tasks.noTasks')}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {tasks.map(task => (
              <div
                key={task.id}
                className="group relative overflow-hidden bg-surface-container/40 backdrop-blur-md rounded-2xl p-5 flex items-center justify-between border border-outline-variant/5 hover:bg-surface-container hover:border-outline-variant/10 hover:-translate-y-0.5 transition-all duration-300"
              >
                <div className="flex items-center gap-5 flex-1 min-w-0 relative z-10">
                  <StatusIcon status={task.status} />
                  <div className="flex flex-col gap-1.5 flex-1 min-w-0">
                    <h3 className="text-lg font-headline font-extrabold text-on-surface truncate pr-4" title={task.title}>
                      {task.title}
                    </h3>
                    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
                      <div className="flex items-center gap-2">
                        <div className={`w-1.5 h-1.5 rounded-full ${getTaskStatusDotClass(task.status)}`} />
                        <span className="text-[10px] font-label uppercase tracking-[0.15em] font-extrabold text-on-surface-variant">
                          {t(`page.tasks.status.${task.status}`)}
                        </span>
                      </div>
                      <div className="text-[11px] font-medium text-on-surface-variant/50 flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5" />
                        {new Date(task.created_at).toLocaleString()}
                      </div>
                    </div>
                    
                    {task.error_msg && (
                      <div className="mt-2 flex items-start gap-2.5 text-xs text-error-dim bg-error-dim/5 p-3 rounded-xl border border-error-dim/10">
                        <Terminal className="w-4 h-4 mt-0.5 shrink-0" />
                        <span className="leading-relaxed font-medium">{task.error_msg}</span>
                      </div>
                    )}

                    {task.save_path && (
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-on-surface-variant/40 italic">
                        <Save className="w-3.5 h-3.5" />
                        <span className="truncate" title={task.save_path}>
                          {t('page.tasks.saveTo')}: {task.save_path}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-3 relative z-10 ml-6">
                  {task.status === 'completed' && (
                    <button
                      onClick={() => handleAlignTask(task.id)}
                      disabled={aligningTaskId === task.id}
                      className="w-10 h-10 flex items-center justify-center rounded-xl bg-primary/10 text-primary hover:bg-primary hover:text-on-primary transition-all duration-300 shadow-lg shadow-primary/10 disabled:opacity-50"
                      title={t('subtitles.align')}
                    >
                      {aligningTaskId === task.id ? (
                        <RefreshCw className="w-5 h-5 animate-spin" />
                      ) : (
                        <span className="material-symbols-outlined text-xl">graphic_eq</span>
                      )}
                    </button>
                  )}
                  {task.status === 'failed' && (
                    <button
                      onClick={() => handleRetry(task.id)}
                      className="w-10 h-10 flex items-center justify-center rounded-xl bg-primary/10 text-primary hover:bg-primary hover:text-on-primary transition-all duration-300 shadow-lg shadow-primary/10"
                      title={t('page.tasks.retry')}
                    >
                      <RefreshCw className="w-5 h-5" />
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(task.id)}
                    className="w-10 h-10 flex items-center justify-center rounded-xl bg-surface-container-highest text-on-surface-variant hover:bg-error-dim hover:text-on-error transition-all duration-300 border border-outline-variant/10"
                    title={t('page.tasks.delete')}
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                </div>

                {/* Background Decoration */}
                <div className="absolute top-0 right-0 w-48 h-48 bg-primary/5 rounded-full -mr-24 -mt-24 blur-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
