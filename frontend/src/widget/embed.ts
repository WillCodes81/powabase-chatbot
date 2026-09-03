import {
  attachPublicDocument,
  clearPublicSession,
  loadCachedMessages,
  saveCachedMessages,
  sendPublicChatMessage,
  type PublicChatMessage,
} from '../lib/publicShareClient';

// Mirrors the main app's design tokens (frontend/src/index.css :root) --
// hardcoded rather than shared, since this bundle runs standalone on a
// third-party page with no access to our CSS custom properties. Keep in
// sync with index.css by hand if the palette changes.
const CANVAS = '#0b0a09';
const SURFACE = '#16130f';
const SURFACE_RAISED = '#211c15';
const BORDER = '#322a1e';
const TEXT = '#f1ece2';
const TEXT_MUTED = '#9c9384';
const ACCENT = '#f2a93b';
const ACCENT_STRONG = '#ffc469';
const ACCENT_DEEP = '#b9781f';
const DANGER_STRONG = '#ff7b70';
const GRADIENT_ACCENT = 'linear-gradient(135deg, #f2a93b 0%, #ffc469 55%, #f2a93b 100%)';
const FONT_DISPLAY = "'Space Grotesk', system-ui, sans-serif";
const FONT_BODY = "'Inter', system-ui, sans-serif";
const RADIUS_SM = '8px';
const RADIUS_MD = '14px';
const RADIUS_FULL = '999px';

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

function loadFonts() {
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = 'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600&display=swap';
  document.head.appendChild(link);
}

function chatIconSvg(color: string): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '22');
  svg.setAttribute('height', '22');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', 'M4 4.5h16v12H9l-4.5 4V4.5z');
  path.setAttribute('stroke', color);
  path.setAttribute('stroke-width', '1.8');
  path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path);
  return svg;
}

function mount() {
  loadFonts();
  const { shareId, apiBase } = currentScriptConfig();

  // Black circle with a gold-gradient ring: an outer gradient disc a few
  // pixels larger than an inner near-black disc, so only the ring shows.
  const bubble = el('button', {
    position: 'fixed', bottom: '20px', right: '20px', width: '60px', height: '60px',
    borderRadius: RADIUS_FULL, background: GRADIENT_ACCENT, border: 'none', padding: '3px',
    cursor: 'pointer', zIndex: '999999', boxShadow: `0 0 0 1px rgba(242, 169, 59, 0.3), 0 12px 32px rgba(242, 169, 59, 0.18)`,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  });
  const bubbleInner = el('span', {
    width: '100%', height: '100%', borderRadius: RADIUS_FULL, background: CANVAS,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  });
  bubbleInner.appendChild(chatIconSvg(ACCENT_STRONG));
  bubble.appendChild(bubbleInner);
  bubble.setAttribute('aria-label', 'Open chat');

  const panel = el('div', {
    position: 'fixed', bottom: '90px', right: '20px', width: '340px', height: '460px',
    background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: RADIUS_MD,
    boxShadow: '0 12px 32px rgba(0, 0, 0, 0.6)',
    display: 'none', flexDirection: 'column', overflow: 'hidden', zIndex: '999999', fontFamily: FONT_BODY,
    color: TEXT,
  });

  const header = el('div', {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 16px', borderBottom: `1px solid ${BORDER}`,
  });
  const title = el('span', { fontFamily: FONT_DISPLAY, fontWeight: '700', fontSize: '16px', color: TEXT });
  title.textContent = 'Chat';
  const newSessionBtn = el('button', {
    border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT_MUTED, cursor: 'pointer',
    fontSize: '12px', fontWeight: '600', fontFamily: FONT_BODY, borderRadius: RADIUS_SM, padding: '6px 10px',
  });
  newSessionBtn.textContent = 'New Session';
  header.append(title, newSessionBtn);

  const messagesEl = el('div', {
    flex: '1', overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px',
  });

  const uploadRow = el('div', { padding: '0 16px 12px', display: 'flex', flexDirection: 'column', gap: '4px' });
  const fileInputId = 'powabase-widget-file-input';
  const fileLabel = el('label', {
    display: 'inline-flex', alignSelf: 'flex-start', border: `1px solid ${BORDER}`, background: SURFACE_RAISED,
    color: TEXT, borderRadius: RADIUS_SM, padding: '6px 12px', fontSize: '12px', fontWeight: '600', cursor: 'pointer',
  });
  fileLabel.textContent = 'Attach a document';
  fileLabel.htmlFor = fileInputId;
  const fileInput = el('input', {
    position: 'absolute', width: '1px', height: '1px', overflow: 'hidden', clip: 'rect(0 0 0 0)',
  });
  fileInput.type = 'file';
  fileInput.id = fileInputId;
  const uploadStatus = el('div', { fontSize: '11px', color: TEXT_MUTED });
  uploadRow.append(fileLabel, fileInput, uploadStatus);

  const inputRow = el('div', { display: 'flex', gap: '8px', padding: '12px 16px', borderTop: `1px solid ${BORDER}` });
  const textInput = el('input', {
    flex: '1', minWidth: '0', background: SURFACE, color: TEXT, border: `1px solid ${BORDER}`,
    borderRadius: RADIUS_SM, padding: '9px 12px', fontSize: '13px', fontFamily: FONT_BODY,
  });
  textInput.type = 'text';
  textInput.placeholder = 'Type a message…';
  const sendBtn = el('button', {
    background: GRADIENT_ACCENT, color: '#1a1300', border: 'none', borderRadius: RADIUS_FULL,
    padding: '9px 18px', fontSize: '13px', fontWeight: '700', fontFamily: FONT_BODY, cursor: 'pointer',
    boxShadow: '0 4px 18px rgba(242, 169, 59, 0.22)',
  });
  sendBtn.textContent = 'Send';
  inputRow.append(textInput, sendBtn);

  panel.append(header, messagesEl, uploadRow, inputRow);
  document.body.append(bubble, panel);

  let messages: PublicChatMessage[] = loadCachedMessages(shareId);

  function render() {
    messagesEl.innerHTML = '';
    if (messages.length === 0) {
      const empty = el('p', { color: TEXT_MUTED, fontSize: '13px', margin: 'auto', textAlign: 'center' });
      empty.textContent = 'Say something to start the conversation.';
      messagesEl.append(empty);
    }
    for (const m of messages) {
      const bubbleEl = el('div', {
        alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
        background: m.role === 'user' ? GRADIENT_ACCENT : SURFACE_RAISED,
        color: m.role === 'user' ? '#1a1300' : TEXT,
        border: m.role === 'user' ? 'none' : `1px solid ${BORDER}`,
        fontWeight: m.role === 'user' ? '500' : '400',
        padding: '8px 12px', borderRadius: RADIUS_SM, maxWidth: '85%', fontSize: '13px',
        lineHeight: '1.5', wordBreak: 'break-word', whiteSpace: 'pre-wrap',
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

  // Guards against the same race Task 10's React page had: clicking New
  // Session while a send is still in flight must not let that send's
  // eventual response land on top of (or into) the just-cleared
  // conversation.
  let sending = false;

  newSessionBtn.addEventListener('click', () => {
    if (sending) return;
    clearPublicSession(shareId);
    messages = [];
    uploadStatus.textContent = '';
    render();
  });

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    uploadStatus.textContent = 'Uploading…';
    uploadStatus.style.color = TEXT_MUTED;
    try {
      const result = await attachPublicDocument(apiBase, shareId, file);
      uploadStatus.textContent = `Attached: ${result.filename}`;
      uploadStatus.style.color = ACCENT;
    } catch (err) {
      uploadStatus.textContent = err instanceof Error ? err.message : 'Upload failed.';
      uploadStatus.style.color = DANGER_STRONG;
    } finally {
      fileInput.value = '';
    }
  });

  async function send() {
    const text = textInput.value.trim();
    if (!text || sending) return;
    sending = true;
    newSessionBtn.disabled = true;
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
    } finally {
      sending = false;
      newSessionBtn.disabled = false;
    }
  }

  sendBtn.addEventListener('click', send);
  textInput.addEventListener('keydown', (e) => e.key === 'Enter' && send());
  newSessionBtn.addEventListener('mouseenter', () => { newSessionBtn.style.borderColor = ACCENT_DEEP; });
  newSessionBtn.addEventListener('mouseleave', () => { newSessionBtn.style.borderColor = BORDER; });
}

mount();
