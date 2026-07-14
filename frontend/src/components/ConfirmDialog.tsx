import { Modal } from './Modal';

export interface ConfirmDialogProps {
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): JSX.Element {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={
        <>
          <button onClick={onCancel}>{cancelLabel}</button>
          <button className={danger ? 'danger' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <div>{message}</div>
    </Modal>
  );
}
