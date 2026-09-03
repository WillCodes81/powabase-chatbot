import { api } from './client';

export interface PublicShareCreated {
  share_id: string;
  agent_id: string;
  // Present on the create response (POST /public/agents), absent on the
  // by-source lookup response (GET /agents/by-source/{id}) -- that
  // route never selects a name column. Callers that need the agent's name
  // already have it locally (see Task 9's usage).
  name?: string;
  created_at: string;
}

export function createPublicShare(name: string, sourceAgentId: string) {
  return api.post<PublicShareCreated>('/public/agents', { name, source_agent_id: sourceAgentId });
}

export function getPublicShareBySource(sourceAgentId: string) {
  // Authenticated route, lives on main_app (not /public, which is the
  // permissive-CORS app for anonymous visitors) -- see app/routes/agents.py.
  return api.get<PublicShareCreated>(`/agents/by-source/${sourceAgentId}`);
}
