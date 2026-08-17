import { api } from './client';
import type { AgentCreated, AgentSummary } from './types';

export function listAgents() {
  return api.get<AgentSummary[]>('/agents');
}

export function createAgent(name: string, systemPrompt?: string) {
  return api.post<AgentCreated>('/agents', { name, system_prompt: systemPrompt });
}

export function updateAgentName(agentId: string, name: string) {
  return api.patch<AgentCreated>(`/agents/${agentId}`, { name });
}
