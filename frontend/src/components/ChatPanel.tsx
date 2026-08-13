import { useState, type FormEvent } from 'react';
import type { ChatResult, SessionMessage } from '../api/types';
import { describeError } from '../lib/errors';
import styles from './ChatPanel.module.css';

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatPanelProps {
  initialMessages?: SessionMessage[];
  initialSessionId?: string | null;
  sendMessage: (message: string, sessionId: string | null) => Promise<ChatResult>;
  onSessionStart?: (sessionId: string) => void;
}

export function ChatPanel({
  initialMessages = [],
  initialSessionId = null,
  sendMessage,
  onSessionStart,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>(
    initialMessages.map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content })),
  );
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setError(null);
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setSending(true);
    try {
      const result = await sendMessage(text, sessionId);
      setMessages((prev) => [...prev, { role: 'assistant', content: result.content }]);
      if (sessionId === null) {
        setSessionId(result.session_id);
        onSessionStart?.(result.session_id);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.messages}>
        {messages.length === 0 && !sending && <p className={styles.empty}>Say something to start the conversation.</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant}>
            {m.content}
          </div>
        ))}
        {sending && (
          <div className={styles.bubbleAssistant}>
            <span className={styles.typing}>Thinking…</span>
          </div>
        )}
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <form className={styles.inputRow} onSubmit={handleSend}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder="Type a message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button className="btn btn-primary" type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
