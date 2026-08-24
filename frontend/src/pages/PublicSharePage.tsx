import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  attachPublicDocument,
  clearPublicSession,
  loadCachedMessages,
  saveCachedMessages,
  sendPublicChatMessage,
  type PublicChatMessage,
} from '../lib/publicShareClient';
import styles from './PublicSharePage.module.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export function PublicSharePage() {
  const { shareId } = useParams<{ shareId: string }>();
  const [messages, setMessages] = useState<PublicChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    setUploadStatus(null);
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !shareId) return;
    setUploadStatus('Uploading…');
    try {
      const result = await attachPublicDocument(API_BASE_URL, shareId, file);
      setUploadStatus(`Attached: ${result.filename}`);
    } catch (err) {
      setUploadStatus(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
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

      <div className={styles.messages}>
        {messages.map((m, i) => (
          <div key={i} className={`${styles.message} ${m.role === 'user' ? styles.user : styles.assistant}`}>
            {m.content}
          </div>
        ))}
      </div>

      {error && <p role="alert">{error}</p>}

      <div>
        <input ref={fileInputRef} type="file" onChange={handleFileChange} />
        {uploadStatus && <p>{uploadStatus}</p>}
      </div>

      <div className={styles.inputRow}>
        <input
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
  );
}
