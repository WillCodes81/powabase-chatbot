import { api } from './client';
import type { AgentCreated, AgentSummary } from './types';

export function listAgents() {
  return api.get<AgentSummary[]>('/agents');
}

export function createAgent(name: string, systemPrompt?: string, model?: string) {
  return api.post<AgentCreated>('/agents', { name, system_prompt: systemPrompt, model: model || undefined });
}

export function updateAgentName(agentId: string, name: string) {
  return api.patch<AgentCreated>(`/agents/${agentId}`, { name });
}
