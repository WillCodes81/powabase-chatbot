import { useState } from 'react';
import type { SessionMessage, SessionSummary } from '../api/types';

interface ChatConfig {
  key: string;
  initialMessages: SessionMessage[];
  initialSessionId: string | null;
}

export function useConversation(loadMessages: (sessionId: string) => Promise<{ messages: SessionMessage[] }>) {
  const [chatConfig, setChatConfig] = useState<ChatConfig | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  function startNewChat() {
    setChatConfig({ key: `new-${Date.now()}`, initialMessages: [], initialSessionId: null });
    setActiveSessionId(null);
  }

  async function continueSession(session: SessionSummary) {
    const { messages } = await loadMessages(session.session_id);
    setChatConfig({ key: session.session_id, initialMessages: messages, initialSessionId: session.session_id });
    setActiveSessionId(session.session_id);
  }

  function clear() {
    setChatConfig(null);
    setActiveSessionId(null);
  }

  return {
    chatConfig,
    activeSessionId,
    startNewChat,
    continueSession,
    clear,
    onSessionStart: setActiveSessionId,
  };
}
