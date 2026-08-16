import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { listAgents } from '../api/agents';
import { listSessions, getSessionMessages, deleteSession, attachDocumentToSession } from '../api/sessions';
import { ingestFile } from '../api/ingest';
import { chatWithAgent } from '../api/chat';
import { useAsync } from '../hooks/useAsync';
import { useConversation } from '../hooks/useConversation';
import { useCredits } from '../context/CreditsContext';
import { ChatPanel } from '../components/ChatPanel';
import { SessionHistoryPanel } from '../components/SessionHistoryPanel';
import { FileUploadButton } from '../components/FileUploadButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { describeError } from '../lib/errors';
import type { SessionSummary } from '../api/types';
import styles from './AgentDetailPage.module.css';

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const credits = useCredits();

  const agentsList = useAsync(() => listAgents(), []);
  const agent = agentsList.data?.find((a) => a.agent_id === agentId);

  const sessions = useAsync(() => listSessions(agentId!), [agentId]);
  const conversation = useConversation((sessionId) => getSessionMessages(agentId!, sessionId));

  const [actionError, setActionError] = useState<string | null>(null);

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

  async function handleContinueSession(session: SessionSummary) {
    try {
      await conversation.continueSession(session);
      setActionError(null);
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  if (agentsList.loading) return <Spinner />;
  if (agentsList.error) return <ErrorBanner message={agentsList.error} />;
  if (!agent) return <ErrorBanner message="Agent not found." />;

  return (
    <div>
      <div className={styles.header}>
        <h1>{agent.name}</h1>
        <p className="mono">{agent.agent_id}</p>
      </div>

      <section className={styles.section}>
        <h2>Documents</h2>
        <div className={styles.uploads}>
          <FileUploadButton
            id="upload-permanent"
            label="Add document to agent"
            helpText="Permanent — available in every conversation with this agent."
            onUpload={(file) => ingestFile(agentId!, file)}
          />
          <FileUploadButton
            id="upload-attach"
            label="Attach file to this conversation"
            disabled={!conversation.activeSessionId}
            disabledText="Send a message below first — this attaches to the active conversation only."
            onUpload={(file) => attachDocumentToSession(agentId!, conversation.activeSessionId!, file)}
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Past sessions</h2>
          <button type="button" className="btn btn-primary" onClick={conversation.startNewChat}>
            New chat
          </button>
        </div>
        {actionError && <ErrorBanner message={actionError} />}
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={handleContinueSession}
          onDelete={(session) => handleDeleteSession(session.session_id)}
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
