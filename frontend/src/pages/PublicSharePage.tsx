import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  attachPublicDocument,
  clearPublicSession,
  loadCachedMessages,
  saveCachedMessages,
  sendPublicChatMessage,
  type PublicChatMessage,
} from '../lib/publicShareClient';
import { FileUploadButton } from '../components/FileUploadButton';
import styles from './PublicSharePage.module.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export function PublicSharePage() {
  const { shareId } = useParams<{ shareId: string }>();
  const [messages, setMessages] = useState<PublicChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionKey, setSessionKey] = useState(0);

  useEffect(() => {
    if (!shareId) return;
    setMessages(loadCachedMessages(shareId));
  }, [shareId]);

  async function handleSend() {
    if (!shareId || !input.trim() || sending) return;
    const userMessage: PublicChatMessage = { role: 'user', content: input };
    const next = [...messages, userMessage];
    setMessages(next);
    saveCachedMessages(shareId, next);
    setInput('');
    setSending(true);
    setError(null);
    try {
      const content = await sendPublicChatMessage(API_BASE_URL, shareId, userMessage.content);
      const withReply = [...next, { role: 'assistant', content } as PublicChatMessage];
      setMessages(withReply);
      saveCachedMessages(shareId, withReply);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setSending(false);
    }
  }

  function handleNewSession() {
    if (!shareId) return;
    clearPublicSession(shareId);
    setMessages([]);
    setError(null);
    setSessionKey((k) => k + 1);
  }

  if (!shareId) return null;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1>Chat</h1>
        <button type="button" className="btn" onClick={handleNewSession} disabled={sending}>
          New Session
        </button>
      </div>

      <div className={styles.uploadRow}>
        <FileUploadButton
          key={sessionKey}
          id="public-share-attach"
          label="Attach a document"
          helpText="Available only in this conversation."
          onUpload={(file) => attachPublicDocument(API_BASE_URL, shareId, file)}
        />
      </div>

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
              <span className={styles.empty}>Thinking…</span>
            </div>
          )}
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.inputRow}>
          <input
            className="input"
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder="Type a message…"
            disabled={sending}
          />
          <button type="button" className="btn btn-primary" onClick={handleSend} disabled={sending || !input.trim()}>
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  );
}
