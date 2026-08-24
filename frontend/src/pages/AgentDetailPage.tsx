import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { listAgents, deleteAgent } from '../api/agents';
import { listSessions, getSessionMessages, deleteSession, attachDocumentToSession, updateSessionLabel } from '../api/sessions';
import { ingestFile } from '../api/ingest';
import { chatWithAgent } from '../api/chat';
import { createPublicShare, getPublicShareBySource } from '../api/publicShare';
import { useAsync } from '../hooks/useAsync';
import { useConversation } from '../hooks/useConversation';
import { useCredits } from '../context/CreditsContext';
import { ChatPanel } from '../components/ChatPanel';
import { SessionHistoryPanel } from '../components/SessionHistoryPanel';
import { FileUploadButton } from '../components/FileUploadButton';
import { ConfirmButton } from '../components/ConfirmButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { describeError } from '../lib/errors';
import type { SessionSummary } from '../api/types';
import styles from './AgentDetailPage.module.css';

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const credits = useCredits();

  const agentsList = useAsync(() => listAgents(), []);
  const agent = agentsList.data?.find((a) => a.agent_id === agentId);

  const sessions = useAsync(() => listSessions(agentId!), [agentId]);
  const conversation = useConversation((sessionId) => getSessionMessages(agentId!, sessionId));

  const [actionError, setActionError] = useState<string | null>(null);

  const [shareId, setShareId] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareChecked, setShareChecked] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    getPublicShareBySource(agentId)
      .then((result) => {
        setShareId(result.share_id);
        setShareUrl(`${window.location.origin}/share/${result.share_id}`);
      })
      .catch((err) => {
        // 404 is the normal, expected case -- no public share exists for
        // this agent yet. Anything else (a real 500, a network failure) is
        // a genuine problem and must surface the same way every other
        // error on this page does (shareError -> ErrorBanner), not be
        // silently swallowed and misread as "no share yet."
        if (!(err instanceof ApiError) || err.status !== 404) {
          setShareError(describeError(err));
        }
      })
      .finally(() => setShareChecked(true));
  }, [agentId]);

  async function handleCreateShareableLink() {
    setSharing(true);
    setShareError(null);
    try {
      const result = await createPublicShare(`${agent!.name} (Public)`, agentId!);
      setShareId(result.share_id);
      setShareUrl(`${window.location.origin}/share/${result.share_id}`);
    } catch (err) {
      setShareError(describeError(err));
    } finally {
      setSharing(false);
    }
  }

  async function handleDeleteSession(sessionId: string) {
    try {
      await deleteSession(agentId!, sessionId);
      sessions.reload();
      if (conversation.activeSessionId === sessionId) conversation.clear();
      setActionError(null);
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function handleDeleteAgent() {
    try {
      await deleteAgent(agentId!);
      navigate('/', { replace: true });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function handleContinueSession(session: SessionSummary) {
    try {
      await conversation.continueSession(session);
      setActionError(null);
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function handleRenameSession(session: SessionSummary, newLabel: string) {
    await updateSessionLabel(agentId!, session.session_id, newLabel);
    sessions.reload();
  }

  if (agentsList.loading) return <Spinner />;
  if (agentsList.error) return <ErrorBanner message={agentsList.error} />;
  if (!agent) return <ErrorBanner message="Agent not found." />;

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1>{agent.name}</h1>
          <p className="mono">{agent.agent_id}</p>
        </div>
        <ConfirmButton label="Delete agent" confirmLabel="Confirm delete" onConfirm={handleDeleteAgent} />
      </div>

      {actionError && <ErrorBanner message={actionError} />}

      <section className={styles.section}>
        <h2>Documents</h2>
        <div className={styles.uploads}>
          <div className={`card ${styles.uploadTile}`}>
            <FileUploadButton
              id="upload-permanent"
              label="Add document to agent"
              helpText="Permanent — available in every conversation with this agent."
              onUpload={(file) => ingestFile(agentId!, file)}
            />
          </div>
          <div className={`card ${styles.uploadTile}`}>
            <FileUploadButton
              id="upload-attach"
              label="Attach file to this conversation"
              disabled={!conversation.activeSessionId}
              disabledText="Send a message below first — this attaches to the active conversation only."
              onUpload={(file) => attachDocumentToSession(agentId!, conversation.activeSessionId!, file)}
            />
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <h2>Public sharing</h2>
        <p>
          Creates a brand-new, separate agent with a fixed assistant prompt and its own knowledge
          base — anyone with the link can chat with it, no account required. This is not the same
          agent or knowledge base as the one above.
        </p>
        {shareChecked && !shareUrl && (
          <button type="button" className="btn btn-primary" onClick={handleCreateShareableLink} disabled={sharing}>
            {sharing ? 'Creating…' : 'Get shareable link'}
          </button>
        )}
        {shareError && <ErrorBanner message={shareError} />}
        {shareUrl && shareId && (
          <div className={styles.uploadTile}>
            <p className="mono">{shareUrl}</p>
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Past sessions</h2>
          <button type="button" className="btn btn-primary" onClick={conversation.startNewChat}>
            New chat
          </button>
        </div>
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={handleContinueSession}
          onDelete={(session) => handleDeleteSession(session.session_id)}
          onRename={handleRenameSession}
        />
      </section>

      {conversation.chatConfig && (
        <section className={styles.section}>
          <h2>Chat</h2>
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithAgent(agentId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
            onMessageSent={credits.reload}
          />
        </section>
      )}
    </div>
  );
}
