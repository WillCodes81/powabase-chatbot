import { useState } from 'react';
import { getPublicShareSessionTranscript, listPublicShareSessions } from '../api/publicShareSessions';
import { useAsync } from '../hooks/useAsync';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';
import { Spinner } from './Spinner';
import styles from './PublicShareSessionHistory.module.css';

interface PublicShareSessionHistoryProps {
  agentId: string;
}

// Read-only: visitor session history for an agent's public share. Viewing
// and browsing only -- no edit or delete affordances for the transcript,
// deliberately, since these are someone else's words.
export function PublicShareSessionHistory({ agentId }: PublicShareSessionHistoryProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.wrapper}>
      <button type="button" className="btn btn-ghost" onClick={() => setOpen((v) => !v)}>
        {open ? 'Hide session history' : 'Session history'}
      </button>
      {open && <SessionList agentId={agentId} />}
    </div>
  );
}

function SessionList({ agentId }: { agentId: string }) {
  const sessions = useAsync(() => listPublicShareSessions(agentId), [agentId]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (sessions.loading) return <Spinner />;
  if (sessions.error) return <ErrorBanner message={sessions.error} />;
  if (!sessions.data || sessions.data.length === 0) {
    return (
      <EmptyState
        title="No visitor sessions yet"
        description="Sessions appear here once someone uses your public share link or widget."
      />
    );
  }

  return (
    <ul className={styles.list}>
      {sessions.data.map((session) => (
        <li key={session.id} className={styles.row}>
          <button
            type="button"
            className={styles.rowButton}
            onClick={() => setSelectedId(selectedId === session.id ? null : session.id)}
          >
            <span className="mono">{new Date(session.created_at).toLocaleString()}</span>
            <span className={styles.badges}>
              {session.has_document && <span className={styles.badge}>Document</span>}
              <span className={styles.badge}>{session.has_conversation ? 'Conversation' : 'No conversation'}</span>
            </span>
          </button>
          {selectedId === session.id && <SessionTranscript agentId={agentId} sessionId={session.id} />}
        </li>
      ))}
    </ul>
  );
}

function SessionTranscript({ agentId, sessionId }: { agentId: string; sessionId: string }) {
  const transcript = useAsync(() => getPublicShareSessionTranscript(agentId, sessionId), [agentId, sessionId]);

  if (transcript.loading) return <Spinner />;
  if (transcript.error) return <ErrorBanner message={transcript.error} />;
  if (!transcript.data || !transcript.data.has_conversation || transcript.data.messages.length === 0) {
    return <p className={styles.noConversation}>No conversation in this session — only a document was uploaded.</p>;
  }

  return (
    <div className={styles.transcript}>
      {transcript.data.messages.map((m, i) => (
        <div key={i} className={m.role === 'assistant' ? styles.bubbleAssistant : styles.bubbleUser}>
          <span className={styles.role}>{m.role}</span>
          <p>{m.content}</p>
        </div>
      ))}
    </div>
  );
}
