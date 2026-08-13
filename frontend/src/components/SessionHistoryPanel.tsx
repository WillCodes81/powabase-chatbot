import type { SessionSummary } from '../api/types';
import { ConfirmButton } from './ConfirmButton';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';
import { Spinner } from './Spinner';
import styles from './SessionHistoryPanel.module.css';

interface SessionHistoryPanelProps {
  loading: boolean;
  error: string | null;
  sessions: SessionSummary[] | null;
  onContinue: (session: SessionSummary) => void;
  onDelete?: (session: SessionSummary) => void;
}

export function SessionHistoryPanel({ loading, error, sessions, onContinue, onDelete }: SessionHistoryPanelProps) {
  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  if (!sessions || sessions.length === 0) {
    return <EmptyState title="No past sessions" description="Start a chat below to create your first session." />;
  }

  return (
    <ul className={styles.list}>
      {sessions.map((session) => (
        <li key={session.id} className={styles.row}>
          <div>
            <p className={styles.label}>{session.label || 'Untitled session'}</p>
            <p className="mono">{new Date(session.created_at).toLocaleString()}</p>
          </div>
          <div className={styles.actions}>
            <button type="button" className="btn btn-ghost" onClick={() => onContinue(session)}>
              Continue
            </button>
            {onDelete && (
              <ConfirmButton label="Delete" confirmLabel="Confirm delete" onConfirm={() => onDelete(session)} />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
