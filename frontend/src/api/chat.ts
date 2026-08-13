import { api } from './client';
import type { ChatResult } from './types';

export function chatWithAgent(agentId: string, message: string, sessionId?: string | null, label?: string) {
  return api.post<ChatResult>('/chat', {
    agent_id: agentId,
    message,
    session_id: sessionId ?? undefined,
    label,
  });
}
