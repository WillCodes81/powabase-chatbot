import {
  attachPublicDocument,
  clearPublicSession,
  loadCachedMessages,
  saveCachedMessages,
  sendPublicChatMessage,
  type PublicChatMessage,
} from '../lib/publicShareClient';

function currentScriptConfig(): { shareId: string; apiBase: string } {
  const script = document.currentScript as HTMLScriptElement | null;
  const shareId = script?.dataset.shareId;
  const apiBase = script?.dataset.apiBase;
  if (!shareId || !apiBase) {
    throw new Error('powabase widget: data-share-id and data-api-base are required on the <script> tag');
  }
  return { shareId, apiBase };
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, styles: Partial<CSSStyleDeclaration> = {}): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  Object.assign(node.style, styles);
  return node;
}

function mount() {
  const { shareId, apiBase } = currentScriptConfig();

  const bubble = el('button', {
    position: 'fixed', bottom: '20px', right: '20px', width: '56px', height: '56px',
    borderRadius: '50%', background: '#2563eb', color: 'white', border: 'none',
    fontSize: '24px', cursor: 'pointer', zIndex: '999999', boxShadow: '0 2px 10px rgba(0,0,0,0.3)',
  });
  bubble.textContent = '💬';
  bubble.setAttribute('aria-label', 'Open chat');

  const panel = el('div', {
    position: 'fixed', bottom: '86px', right: '20px', width: '320px', height: '440px',
    background: 'white', border: '1px solid #ddd', borderRadius: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.25)',
    display: 'none', flexDirection: 'column', overflow: 'hidden', zIndex: '999999', fontFamily: 'sans-serif',
  });

  const header = el('div', { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px', borderBottom: '1px solid #eee' });
  const title = el('span');
  title.textContent = 'Chat';
  const newSessionBtn = el('button', { border: 'none', background: 'transparent', cursor: 'pointer', fontSize: '12px' });
  newSessionBtn.textContent = 'New Session';
  header.append(title, newSessionBtn);

  const messagesEl = el('div', { flex: '1', overflowY: 'auto', padding: '8px', display: 'flex', flexDirection: 'column', gap: '6px' });

  const fileInput = el('input');
  fileInput.type = 'file';
  const uploadStatus = el('div', { fontSize: '11px', padding: '0 8px', color: '#666' });

  const inputRow = el('div', { display: 'flex', gap: '4px', padding: '8px', borderTop: '1px solid #eee' });
  const textInput = el('input', { flex: '1' });
  textInput.type = 'text';
  textInput.placeholder = 'Type a message…';
  const sendBtn = el('button');
  sendBtn.textContent = 'Send';
  inputRow.append(textInput, sendBtn);

  panel.append(header, messagesEl, fileInput, uploadStatus, inputRow);
  document.body.append(bubble, panel);

  let messages: PublicChatMessage[] = loadCachedMessages(shareId);

  function render() {
    messagesEl.innerHTML = '';
    for (const m of messages) {
      const bubbleEl = el('div', {
        alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
        background: m.role === 'user' ? '#2563eb' : '#f1f1f1',
        color: m.role === 'user' ? 'white' : 'black',
        padding: '6px 10px', borderRadius: '8px', maxWidth: '85%', fontSize: '13px',
      });
      bubbleEl.textContent = m.content;
      messagesEl.append(bubbleEl);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  render();

  bubble.addEventListener('click', () => {
    panel.style.display = panel.style.display === 'none' ? 'flex' : 'none';
  });

  newSessionBtn.addEventListener('click', () => {
    clearPublicSession(shareId);
    messages = [];
    render();
  });

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    uploadStatus.textContent = 'Uploading…';
    try {
      const result = await attachPublicDocument(apiBase, shareId, file);
      uploadStatus.textContent = `Attached: ${result.filename}`;
    } catch (err) {
      uploadStatus.textContent = err instanceof Error ? err.message : 'Upload failed.';
    } finally {
      fileInput.value = '';
    }
  });

  async function send() {
    const text = textInput.value.trim();
    if (!text) return;
    messages = [...messages, { role: 'user', content: text }];
    saveCachedMessages(shareId, messages);
    textInput.value = '';
    render();
    try {
      const content = await sendPublicChatMessage(apiBase, shareId, text);
      messages = [...messages, { role: 'assistant', content }];
      saveCachedMessages(shareId, messages);
      render();
    } catch (err) {
      messages = [...messages, { role: 'assistant', content: err instanceof Error ? err.message : 'Error.' }];
      render();
    }
  }

  sendBtn.addEventListener('click', send);
  textInput.addEventListener('keydown', (e) => e.key === 'Enter' && send());
}

mount();
