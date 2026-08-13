export interface AuthUser {
  id: string;
  email: string;
}

export interface AuthResponse {
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  refresh_token?: string;
  user?: AuthUser & Record<string, unknown>;
}

export interface AgentSummary {
  id: string;
  agent_id: string;
  name: string;
  created_at: string;
}

export interface AgentCreated {
  id: string;
  user_id: string;
  agent_id: string;
  kb_id: string;
  name: string;
  chatbot_id: string | null;
  orchestration_entity_id: string | null;
  created_at: string;
}

export interface ChatbotSummary {
  id: string;
  orchestrator_id: string;
  name: string;
  created_at: string;
}

export interface ChatbotSubAgent {
  id: string;
  agent_id: string;
  kb_id: string;
  name: string;
  orchestration_entity_id: string;
  created_at: string;
}

export interface ChatbotDetail extends ChatbotSummary {
  agents: ChatbotSubAgent[];
}

export interface ChatbotCreated {
  chatbot: ChatbotSummary & { user_id: string };
  agent: AgentCreated;
}

export interface SessionSummary {
  id: string;
  session_id: string;
  label: string | null;
  created_at: string;
}

export interface SessionMessage {
  role: string;
  content: string;
}

export interface ChatResult {
  content: string;
  session_id: string;
  usage: Record<string, unknown> | null;
}

export interface DeleteResult {
  deleted: boolean;
  [key: string]: unknown;
}

export interface AttachDocumentResult {
  kb_id: string;
  source_id: string;
  filename: string;
  [key: string]: unknown;
}
