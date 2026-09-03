import { api } from './client';
import type { PublicShareSessionSummary, PublicShareSessionTranscript } from './types';

export function listPublicShareSessions(agentId: string) {
  return api.get<PublicShareSessionSummary[]>(`/agents/${agentId}/public-share/sessions`);
}

export function getPublicShareSessionTranscript(agentId: string, sessionId: string) {
  return api.get<PublicShareSessionTranscript>(`/agents/${agentId}/public-share/sessions/${sessionId}/transcript`);
}
