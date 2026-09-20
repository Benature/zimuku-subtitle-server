import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';
import { ToastContext, type ToastItem, type ToastType } from './toastContext.shared';

const TOAST_DURATION = 3500;
// 顶栏最多同时堆叠的通知条数，超出时丢弃最旧的一条。
const MAX_TOASTS = 3;

const TOAST_STYLES: Record<ToastType, { icon: string; iconClass: string }> = {
  success: { icon: 'check_circle', iconClass: 'text-primary' },
  error: { icon: 'error', iconClass: 'text-error' },
  info: { icon: 'info', iconClass: 'text-on-surface-variant' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextIdRef = useRef(0);

  const dismissToast = useCallback((id: number): void => {
    setToasts(prev => prev.filter(toast => toast.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = 'info'): void => {
      nextIdRef.current += 1;
      const id = nextIdRef.current;
      setToasts(prev => [...prev.slice(-(MAX_TOASTS - 1)), { id, type, message }]);
      setTimeout(() => dismissToast(id), TOAST_DURATION);
    },
    [dismissToast],
  );

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[100] flex flex-col items-center gap-2 pointer-events-none">
        {toasts.map(toast => {
          const style = TOAST_STYLES[toast.type];
          return (
            <div
              key={toast.id}
              role="status"
              className="pointer-events-auto flex items-center gap-2 max-w-md px-4 py-2.5 rounded-xl bg-surface-container-high/95 backdrop-blur-xl border border-outline-variant/15 shadow-[0_8px_30px_rgba(0,0,0,0.4)] text-sm text-on-surface"
            >
              <span
                className={`material-symbols-outlined text-lg shrink-0 ${style.iconClass}`}
                style={{ fontVariationSettings: "'FILL' 1" }}
              >
                {style.icon}
              </span>
              <span className="break-words">{toast.message}</span>
              <button
                type="button"
                onClick={() => dismissToast(toast.id)}
                className="shrink-0 ml-1 text-on-surface-variant hover:text-on-surface transition-colors"
                aria-label="close"
              >
                <span className="material-symbols-outlined text-base">close</span>
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
