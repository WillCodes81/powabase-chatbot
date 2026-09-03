export type PublicChatMessage = { role: 'user' | 'assistant'; content: string };

function sessionKey(shareId: string) {
  return `powabase-public-session:${shareId}`;
}

function messagesKey(shareId: string) {
  return `powabase-public-messages:${shareId}`;
}

// crypto.randomUUID() only exists in secure contexts (HTTPS or localhost) --
// this deployment currently runs plain HTTP, where it's simply not a
// function. crypto.getRandomValues() has no such restriction, so build a
// v4-shaped id from that instead; Math.random() is a last resort for the
// rare case crypto itself isn't present at all.
function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

export function getOrCreateAnonSessionId(shareId: string): string {
  const key = sessionKey(shareId);
  const existing = localStorage.getItem(key);
  if (existing) return existing;

  const fresh = randomId();
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
