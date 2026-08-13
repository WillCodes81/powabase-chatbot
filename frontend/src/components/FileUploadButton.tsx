import { useRef, useState, type ChangeEvent } from 'react';
import { describeError } from '../lib/errors';
import styles from './FileUploadButton.module.css';

interface FileUploadButtonProps {
  id: string;
  label: string;
  helpText?: string;
  disabled?: boolean;
  disabledText?: string;
  onUpload: (file: File) => Promise<unknown>;
}

export function FileUploadButton({ id, label, helpText, disabled, disabledText, onUpload }: FileUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  async function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setStatus(null);
    setUploading(true);
    try {
      await onUpload(file);
      setStatus({ type: 'success', message: `${file.name} uploaded.` });
    } catch (err) {
      setStatus({ type: 'error', message: describeError(err) });
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div className={styles.wrap}>
      <input
        ref={inputRef}
        id={id}
        type="file"
        className={styles.hiddenInput}
        onChange={handleChange}
        disabled={disabled || uploading}
      />
      <label htmlFor={id} className="btn">
        {uploading ? 'Uploading…' : label}
      </label>
      {!disabled && helpText && <p className={styles.help}>{helpText}</p>}
      {disabled && disabledText && <p className={styles.help}>{disabledText}</p>}
      {status && <p className={status.type === 'error' ? styles.error : styles.success}>{status.message}</p>}
    </div>
  );
}
