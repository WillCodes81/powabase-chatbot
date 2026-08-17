import { useEffect, useState } from 'react';

interface ConfirmButtonProps {
  label: string;
  confirmLabel?: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
}

export function ConfirmButton({ label, confirmLabel = 'Confirm', variant = 'danger', onConfirm }: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const timer = setTimeout(() => setConfirming(false), 3000);
    return () => clearTimeout(timer);
  }, [confirming]);

  if (confirming) {
    return (
      <button
        type="button"
        className={variant === 'danger' ? 'btn btn-danger' : 'btn'}
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
    );
  }

  return (
    <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
      {label}
    </button>
  );
}
