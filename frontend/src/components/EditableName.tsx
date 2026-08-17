import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import styles from './EditableName.module.css';

interface EditableNameProps {
  value: string;
  onSave: (newValue: string) => Promise<void>;
}

export function EditableName({ value, onSave }: EditableNameProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDraft(value);
    setError(null);
    setEditing(true);
  }

  function cancel(e: MouseEvent | KeyboardEvent) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);
    setEditing(false);
  }

  async function commit() {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(trimmed);
      setEditing(false);
    } catch {
      setError('Rename failed');
    } finally {
      setSaving(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    }
    if (e.key === 'Escape') {
      cancel(e);
    }
  }

  if (editing) {
    return (
      <span className={styles.editing}>
        <input
          className={styles.input}
          autoFocus
          value={draft}
          disabled={saving}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
        />
        <button type="button" className={styles.pencil} disabled={saving} onClick={(e) => { e.preventDefault(); e.stopPropagation(); commit(); }} aria-label="Save">
          ✓
        </button>
        <button type="button" className={styles.pencil} disabled={saving} onClick={cancel} aria-label="Cancel">
          ✕
        </button>
        {error && <span className={styles.error}>{error}</span>}
      </span>
    );
  }

  return (
    <span className={styles.view}>
      {value}
      <button type="button" className={styles.pencil} aria-label="Rename" onClick={startEdit}>
        ✎
      </button>
    </span>
  );
}
