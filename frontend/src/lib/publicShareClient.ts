export type PublicChatMessage = { role: 'user' | 'assistant'; content: string };

function sessionKey(shareId: string) {
  return `powabase-public-session:${shareId}`;
}

function messagesKey(shareId: string) {
  return `powabase-public-messages:${shareId}`;
}

export function getOrCreateAnonSessionId(shareId: string): string {
  const key = sessionKey(shareId);
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const fresh = crypto.randomUUID();
  localStorage.setItem(key, fresh);
  return fresh;
}

export function loadCachedMessages(shareId: string): PublicChatMessage[] {
  const raw = localStorage.getItem(messagesKey(shareId));
  if (!raw) return [];
  try {
    return JSON.parse(raw) as PublicChatMessage[];
  } catch {
    return [];
  }
}

export function saveCachedMessages(shareId: string, messages: PublicChatMessage[]): void {
  localStorage.setItem(messagesKey(shareId), JSON.stringify(messages));
}

export function clearPublicSession(shareId: string): void {
  localStorage.removeItem(sessionKey(shareId));
  localStorage.removeItem(messagesKey(shareId));
}

export async function sendPublicChatMessage(apiBase: string, shareId: string, message: string): Promise<string> {
  const anonSessionId = getOrCreateAnonSessionId(shareId);
  const response = await fetch(`${apiBase}/public/${shareId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, anon_session_id: anonSessionId }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'This assistant is temporarily unavailable.');
  }
  const data = await response.json();
  return data.content as string;
}

export async function attachPublicDocument(apiBase: string, shareId: string, file: File): Promise<{ filename: string }> {
  const anonSessionId = getOrCreateAnonSessionId(shareId);
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${apiBase}/public/${shareId}/sessions/${anonSessionId}/attach-document`, {
    method: 'POST',
    body: formData,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Failed to attach document.');
  }
  return response.json();
}
