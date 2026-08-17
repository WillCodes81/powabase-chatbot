import { api } from './client';
import type {
  ChatbotCreated,
  ChatbotDetail,
  ChatbotSubAgent,
  ChatbotSummary,
  ChatResult,
  DeleteResult,
  SessionMessage,
  SessionSummary,
} from './types';

export function listChatbots() {
  return api.get<ChatbotSummary[]>('/chatbots');
}

export function getChatbot(chatbotId: string) {
  return api.get<ChatbotDetail>(`/chatbots/${chatbotId}`);
}

export function createChatbot(name: string, agentName: string, roleDescription: string, systemPrompt?: string, model?: string) {
  return api.post<ChatbotCreated>('/chatbots', {
    name,
    agent_name: agentName,
    role_description: roleDescription,
    system_prompt: systemPrompt,
    model: model || undefined,
  });
}

export function addChatbotAgent(chatbotId: string, name: string, roleDescription: string, systemPrompt?: string) {
  return api.post<ChatbotSubAgent>(`/chatbots/${chatbotId}/agents`, {
    name,
    role_description: roleDescription,
    system_prompt: systemPrompt,
  });
}

export function deleteChatbotAgent(chatbotId: string, agentId: string) {
  return api.del<DeleteResult & { chatbot_deleted: boolean }>(`/chatbots/${chatbotId}/agents/${agentId}`);
}

export function deleteChatbot(chatbotId: string) {
  return api.del<DeleteResult & { agents_deleted: number }>(`/chatbots/${chatbotId}`);
}

export function chatWithChatbot(chatbotId: string, message: string, sessionId?: string | null, label?: string) {
  return api.post<ChatResult>(`/chatbots/${chatbotId}/chat`, {
    message,
    session_id: sessionId ?? undefined,
    label,
  });
}

export function listChatbotSessions(chatbotId: string) {
  return api.get<SessionSummary[]>(`/chatbots/${chatbotId}/sessions`);
}

export function getChatbotSessionMessages(chatbotId: string, sessionId: string) {
  return api.get<{ messages: SessionMessage[] }>(`/chatbots/${chatbotId}/sessions/${sessionId}/messages`);
}

export function updateChatbotName(chatbotId: string, name: string) {
  return api.patch<ChatbotSummary & { user_id: string }>(`/chatbots/${chatbotId}`, { name });
}

export function updateChatbotSessionLabel(chatbotId: string, sessionId: string, label: string) {
  return api.patch<{ id: string; label: string | null; created_at: string }>(
    `/chatbots/${chatbotId}/sessions/${sessionId}`,
    { label },
  );
}
