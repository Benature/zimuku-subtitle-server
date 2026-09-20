import { useTranslation } from 'react-i18next';
import Modal from './Modal';

interface ConfirmDialogProps {
  isOpen: boolean;
  message: string;
  title?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  isOpen,
  message,
  title,
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): React.JSX.Element | null {
  const { t } = useTranslation();
  return (
    <Modal isOpen={isOpen} onClose={onCancel} title={title ?? t('common.confirm')}>
      <div className="flex flex-col gap-5">
        <p className="text-sm text-on-surface-variant leading-relaxed whitespace-pre-line">{message}</p>
        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-xl bg-surface-container-highest/60 hover:bg-surface-container-highest text-on-surface-variant hover:text-on-surface text-sm font-bold transition-all"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            className={
              danger
                ? 'px-4 py-2 rounded-xl bg-error/10 hover:bg-error/20 text-error border border-error/20 text-sm font-bold transition-all'
                : 'px-4 py-2 rounded-xl bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 text-sm font-bold transition-all'
            }
          >
            {t('common.confirm')}
          </button>
        </div>
      </div>
    </Modal>
  );
}
