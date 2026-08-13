import { api } from './client';
import type { AttachDocumentResult, DeleteResult, SessionMessage, SessionSummary } from './types';

export function listSessions(agentId: string) {
  return api.get<SessionSummary[]>(`/agents/${agentId}/sessions`);
}

export function getSessionMessages(agentId: string, sessionId: string) {
  return api.get<{ messages: SessionMessage[] }>(`/agents/${agentId}/sessions/${sessionId}/messages`);
}

export function deleteSession(agentId: string, sessionId: string) {
  return api.del<DeleteResult & { kb_deleted: boolean }>(`/agents/${agentId}/sessions/${sessionId}`);
}

export function attachDocumentToSession(agentId: string, sessionId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return api.postForm<AttachDocumentResult>(`/agents/${agentId}/sessions/${sessionId}/attach-document`, formData);
}
