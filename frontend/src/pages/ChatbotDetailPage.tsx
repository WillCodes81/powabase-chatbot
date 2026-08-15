import { useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getChatbot,
  addChatbotAgent,
  deleteChatbotAgent,
  deleteChatbot,
  chatWithChatbot,
  listChatbotSessions,
  getChatbotSessionMessages,
} from '../api/chatbots';
import { useAsync } from '../hooks/useAsync';
import { useConversation } from '../hooks/useConversation';
import { ChatPanel } from '../components/ChatPanel';
import { SessionHistoryPanel } from '../components/SessionHistoryPanel';
import { ConfirmButton } from '../components/ConfirmButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { describeError } from '../lib/errors';
import type { SessionSummary } from '../api/types';
import styles from './ChatbotDetailPage.module.css';

export function ChatbotDetailPage() {
  const { chatbotId } = useParams<{ chatbotId: string }>();
  const navigate = useNavigate();

  const chatbot = useAsync(() => getChatbot(chatbotId!), [chatbotId]);
  const sessions = useAsync(() => listChatbotSessions(chatbotId!), [chatbotId]);
  const conversation = useConversation((sessionId) => getChatbotSessionMessages(chatbotId!, sessionId));

  const [addAgentOpen, setAddAgentOpen] = useState(false);
  const [agentName, setAgentName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [addAgentError, setAddAgentError] = useState<string | null>(null);
  const [addingAgent, setAddingAgent] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function handleAddAgent(e: FormEvent) {
    e.preventDefault();
    setAddAgentError(null);
    setAddingAgent(true);
    try {
      await addChatbotAgent(chatbotId!, agentName.trim(), roleDescription.trim(), systemPrompt.trim() || undefined);
      setAgentName('');
      setRoleDescription('');
      setSystemPrompt('');
      setAddAgentOpen(false);
      chatbot.reload();
    } catch (err) {
      setAddAgentError(describeError(err));
    } finally {
      setAddingAgent(false);
    }
  }

  async function handleDeleteAgent(agentId: string) {
    try {
      const result = await deleteChatbotAgent(chatbotId!, agentId);
      if (result.chatbot_deleted) {
        navigate('/', { replace: true });
      } else {
        chatbot.reload();
      }
      setActionError(null);
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function handleDeleteChatbot() {
    try {
      await deleteChatbot(chatbotId!);
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

  if (chatbot.loading) return <Spinner />;
  if (chatbot.error) return <ErrorBanner message={chatbot.error} />;
  if (!chatbot.data) return null;

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1>{chatbot.data.name}</h1>
          <p className="mono">{chatbot.data.orchestrator_id}</p>
        </div>
        <ConfirmButton label="Delete chatbot" confirmLabel="Confirm delete" onConfirm={handleDeleteChatbot} />
      </div>

      {actionError && <ErrorBanner message={actionError} />}

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Agents</h2>
          <button type="button" className="btn" onClick={() => setAddAgentOpen((v) => !v)}>
            {addAgentOpen ? 'Cancel' : 'Add agent'}
          </button>
        </div>

        {addAgentOpen && (
          <form className={styles.addForm} onSubmit={handleAddAgent}>
            {addAgentError && <ErrorBanner message={addAgentError} />}
            <div className="field">
              <label htmlFor="new-agent-name">Name</label>
              <input
                id="new-agent-name"
                className="input"
                required
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-agent-role">Role description</label>
              <textarea
                id="new-agent-role"
                className="input"
                rows={3}
                required
                value={roleDescription}
                onChange={(e) => setRoleDescription(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-agent-prompt">System prompt (optional)</label>
              <textarea
                id="new-agent-prompt"
                className="input"
                rows={3}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={addingAgent || !agentName.trim() || !roleDescription.trim()}
            >
              {addingAgent ? 'Adding…' : 'Add agent'}
            </button>
          </form>
        )}

        <div className={styles.orchestration}>
          {chatbot.data.agents.map((agent) => (
            <div key={agent.id} className={styles.orchestrationRow}>
              <span className={styles.node} />
              <div className={`card ${styles.agentCard}`}>
                <div>
                  <p className={styles.agentName}>{agent.name}</p>
                  <p className="mono">{agent.agent_id}</p>
                </div>
                <ConfirmButton
                  label="Remove"
                  confirmLabel="Confirm remove"
                  onConfirm={() => handleDeleteAgent(agent.agent_id)}
                />
              </div>
            </div>
          ))}
        </div>
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
        />
      </section>

      {conversation.chatConfig && (
        <section className={styles.section}>
          <h2>Chat</h2>
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithChatbot(chatbotId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
          />
        </section>
      )}
    </div>
  );
}
