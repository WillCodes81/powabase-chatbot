# React Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working React + TypeScript + Vite frontend in `frontend/`, alongside the existing `app/` FastAPI backend, covering auth, dashboard, standalone-agent and chatbot management, chat, session history (for both standalone agents and chatbots), and document upload.

**Architecture:** A single-page app (React Router, client-side only, no SSR) that talks directly to the FastAPI backend over `fetch`. Auth is a bearer token from Supabase-flavored GoTrue, stored in `localStorage` and attached to every request. No backend framework (Next.js etc.) — Vite's default SPA output is all that's needed since there's exactly one API to call and no server-rendering requirement. State is local `useState`/`useEffect` plus a small `useAsync` hook for loading/error bookkeeping — no Redux/React Query, since the data-fetching needs here are simple list/detail fetches with manual refetch-on-mutation, not caching across routes.

**Tech Stack:** React 19 + TypeScript + Vite (via `npm create vite@latest -- --template react-ts`), `react-router-dom` v6 for routing, plain `fetch` for HTTP (no axios), CSS Modules + a small global token/utility stylesheet for styling (no CSS framework or component library).

**Spec:** This plan folds in two rounds of user instructions given directly in conversation (no separate spec file exists): the original frontend build request (auth, dashboard, agent/chatbot CRUD, chat, standalone-agent session history, document upload) and a follow-up backend change adding chatbot-level session history (`GET /chatbots/{chatbot_id}/sessions` and `GET /chatbots/{chatbot_id}/sessions/{session_id}/messages`), which is folded into item 7 (session history) rather than treated separately.

## Global Constraints

- Frontend lives in `frontend/` at the repo root, alongside `app/`. Do not restructure `app/` beyond the CORS change in Task 1 (already partially done — see below).
- Backend base URL for local dev is `http://127.0.0.1:8000` (run via `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`). Frontend dev server is Vite's default `http://localhost:5173`.
- No local pydantic response models exist on the backend — every endpoint returns a hand-built dict, often a raw pass-through of an upstream Powabase/PostgREST/GoTrue response. TypeScript types in this plan are reconstructed from route code and the `scripts/sanity_check*.py` ground-truth scripts, not from any OpenAPI schema.
- Error responses are always FastAPI's default `{"detail": ...}` shape, but `detail` is sometimes a string and sometimes an object/array (upstream error passthrough). Every error-handling code path must treat `detail` as `string | Record<string, unknown> | unknown[]` — never assume it's always a string.
- Auth: protected routes read a raw `Authorization: Bearer <token>` header via a custom FastAPI dependency (not OAuth2PasswordBearer). There is no refresh-token endpoint on this backend — a stale token just gets a 401, requiring the user to sign in again.
- Two backend changes are part of this plan and already applied directly (not deferred to a task, since they're small, low-risk, and precisely specified — see "Already-applied backend changes" below): CORS middleware, and chatbot session-history routes. Task 1 documents/verifies the CORS piece since it wasn't yet applied when this plan was written; the chatbot-session-history routes are already live and this plan's frontend tasks build against them directly.
- This repo has no automated frontend test framework (no Jest/Vitest/Playwright) and the backend itself has no `pytest` suite — verification throughout this plan is `npx tsc --noEmit` (type check), `npm run build` (production build succeeds), and manual smoke checks against the live local backend (curl for API-shape checks, browser click-through for UI checks), matching this repo's existing convention of manual `scripts/sanity_check*.py` scripts over automated tests.
- Route param identity rule (easy to get backwards — verified directly against backend code): for **standalone agents**, every nested route (`/agents/{agent_id}/...`, `/chat` body's `agent_id`, `/ingest/file`'s `agent_id`) keys on the **Powabase `agent_id` field**, not the `agents_registry` row's own `id`. `GET /agents` returns both `id` and `agent_id` per row — the frontend must route on and pass around `agent_id`, never `id`, for standalone agents. For **chatbots**, `/chatbots/{chatbot_id}` keys on the `chatbots` table's own `id` (not `orchestrator_id`). For a **chatbot's sub-agents**, `/chatbots/{chatbot_id}/agents/{agent_id}` keys on the sub-agent's Powabase `agent_id` (same rule as standalone agents, since sub-agents are also rows in `agents_registry`).

### Already-applied backend changes (context, not a task to execute)

Two backend edits were made directly in this session, ahead of this plan, because they were small, precisely scoped, and needed before frontend work could start meaningfully:

1. **Chatbot session history** — added to `app/powabase_client.py` and `app/routes/chatbots.py`:
   - `list_chatbot_sessions(access_token, chatbot_id)` in `powabase_client.py`, mirroring the existing `list_chat_sessions` but querying the `chatbot_sessions` table.
   - `GET /chatbots/{chatbot_id}/sessions` — ownership-checked via `get_chatbot_entry`, then calls `list_chatbot_sessions`. Returns the same shape as the standalone-agent equivalent: `[{id, session_id, label, created_at}, ...]`.
   - `GET /chatbots/{chatbot_id}/sessions/{session_id}/messages` — ownership-checked via `get_chatbot_entry` + `get_chatbot_session_entry`, then reuses the existing `get_session_messages(session_id)` unchanged. Returns `{"messages": [{"role": ..., "content": ...}, ...]}`, identical shape to the standalone-agent version.
   - There is **no** `DELETE /chatbots/{chatbot_id}/sessions/{session_id}` route — chatbot session history is list + continue only, no delete. (Standalone agents keep their existing delete route.)
   - Verified: `python3 -m py_compile` on both files, and `app.openapi()['paths']` confirmed both new routes register correctly.

2. **CORS middleware is still pending** — this is Task 1 below, not yet applied as of this plan being written.

## File Structure

```
frontend/
├── index.html
├── package.json
├── tsconfig.json / tsconfig.app.json / tsconfig.node.json   (from Vite scaffold)
├── vite.config.ts
├── .env.development                  # VITE_API_BASE_URL=http://127.0.0.1:8000
├── .gitignore                        # from Vite scaffold (node_modules, dist)
└── src/
    ├── main.tsx                      # React root, mounts <App/> wrapped in AuthProvider + BrowserRouter
    ├── App.tsx                       # route table
    ├── index.css                     # design tokens, reset, global button/input/card utility classes
    ├── vite-env.d.ts                 # Vite client types + ImportMetaEnv typing
    ├── api/
    │   ├── client.ts                 # fetch wrapper, ApiError, setAuthToken
    │   ├── types.ts                  # all shared TS interfaces
    │   ├── auth.ts                   # signUp, signIn
    │   ├── agents.ts                 # listAgents, createAgent
    │   ├── chatbots.ts                # listChatbots, getChatbot, createChatbot, addChatbotAgent,
    │   │                              # deleteChatbotAgent, deleteChatbot, chatWithChatbot,
    │   │                              # listChatbotSessions, getChatbotSessionMessages
    │   ├── sessions.ts               # listSessions, getSessionMessages, deleteSession, attachDocumentToSession
    │   ├── chat.ts                   # chatWithAgent
    │   └── ingest.ts                 # ingestFile
    ├── lib/
    │   └── errors.ts                 # describeError(err): string
    ├── hooks/
    │   ├── useAsync.ts               # generic loading/error/data/reload hook
    │   └── useConversation.ts        # shared new-chat/continue-session state machine
    ├── auth/
    │   ├── AuthContext.tsx           # AuthProvider, useAuth
    │   ├── ProtectedRoute.tsx
    │   ├── AuthPage.module.css       # shared by SignIn/SignUp
    │   ├── SignInPage.tsx
    │   └── SignUpPage.tsx
    ├── components/
    │   ├── AppShell.tsx / .module.css        # sidebar + outlet layout for authenticated pages
    │   ├── EmptyState.tsx / .module.css
    │   ├── ErrorBanner.tsx / .module.css
    │   ├── Spinner.tsx / .module.css
    │   ├── ConfirmButton.tsx / .module.css
    │   ├── Card.module.css                   # shared by AgentCard/ChatbotCard
    │   ├── AgentCard.tsx
    │   ├── ChatbotCard.tsx
    │   ├── ChatPanel.tsx / .module.css        # reusable chat UI (agent + chatbot)
    │   ├── SessionHistoryPanel.tsx / .module.css  # reusable session list (agent + chatbot)
    │   └── FileUploadButton.tsx / .module.css
    └── pages/
        ├── DashboardPage.tsx / .module.css
        ├── CreateAgentPage.tsx / .module.css       # .module.css shared with CreateChatbotPage as FormPage.module.css
        ├── CreateChatbotPage.tsx
        ├── AgentDetailPage.tsx / .module.css
        └── ChatbotDetailPage.tsx / .module.css
```

## Design System

Chosen deliberately to avoid the three generic "AI SaaS" defaults (cream+terracotta serif; near-black+neon minimal; broadsheet hairlines). This product's own vernacular — agents, orchestration, sessions, wiring one agent's output into another — is the source of the visual identity: a dark **instrument-panel** feel (flat, hairline borders, small radii, no soft shadows/gradients) with a warm signal-amber accent standing in for an oscilloscope trace, and a signature motif — a thin vertical "orchestration" connector with node dots — used on chatbot sub-agent lists, where it's not decoration but a literal diagram of the supervisor→agents structure the product actually implements.

**Color:**
- `--color-canvas: #14171C` — page background, dark slate (not pure black — has a cool undertone, avoids the "near-black" default)
- `--color-surface: #1B1F26` — card/panel background
- `--color-surface-raised: #232832` — nested surfaces (assistant chat bubbles, hovered rows)
- `--color-border: #2B303B` — hairline borders throughout
- `--color-text: #ECE9E4` — primary text, warm off-white
- `--color-text-muted: #8D93A1` — secondary text, timestamps
- `--color-accent: #F2A93B` — signal amber; primary actions, focus rings, status dots, connector lines
- `--color-positive: #4FD1C5` — teal, reserved for success/positive states
- `--color-danger: #E2574C` — destructive actions/errors

**Type:** `Space Grotesk` (display — headings, brand mark, button labels) paired with `Inter` (body — everything else) and `IBM Plex Mono` (utility — agent/session IDs, timestamps, anything that reads as data rather than prose). Loaded via a single Google Fonts `@import` in `index.css`.

**Layout:** Fixed 240px left sidebar (brand mark, nav, account/sign-out) + main content area. Cards use small radii (6px), 1px hairline borders, no shadows — flat and technical rather than soft. Agent/chatbot cards sit in an auto-fill grid on the dashboard.

**Signature element:** On a chatbot's detail page, its sub-agents are rendered as a vertical stack connected by a thin (2px) left-aligned line with a small filled dot at each agent's connection point — a literal small diagram of the orchestrator→agents relationship the backend actually implements (`strategy: "supervisor"`), not a generic decorative flourish. The same connector-trace idea reappears in a quieter form as the left-edge accent border on every agent/chatbot card (a "trace" that lights up amber on hover), keeping the visual language consistent without overusing the motif.

**Copy:** Active voice, plain language, no filler. Empty states name the action that resolves them ("Create one to get started"). Errors show the backend's own `detail` message directly rather than a generic "Something went wrong" wherever we have one — see `describeError` in Task 3.

---

### Task 1: Backend — add CORS middleware

**Files:**
- Modify: `app/main.py`

**Interfaces:**
- Produces: A running backend at `http://127.0.0.1:8000` that accepts cross-origin requests (with credentials) from `http://localhost:5173`, exposing `Authorization` on preflight responses.

- [ ] **Step 1: Add the CORS middleware**

Edit `app/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.ingest import router as ingest_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(chatbots_router)
    app.include_router(sessions_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    app.include_router(tools_router)
    return app


app = create_app()
```

- [ ] **Step 2: Verify the app still imports cleanly**

Run: `.venv/bin/python -c "from app.main import app; print('ok')"`
Expected: prints `ok`, no traceback.

- [ ] **Step 3: Verify CORS headers on a live preflight request**

Run:
```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
sleep 1
curl -s -i -X OPTIONS http://127.0.0.1:8000/agents \
  -H "Origin: http://localhost:5173" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type" | head -20
kill %1
```
Expected: `200` (or `204`) response including `access-control-allow-origin: http://localhost:5173`, `access-control-allow-credentials: true`, and `access-control-allow-headers` containing `authorization`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: add CORS middleware for local frontend dev server"
```

---

### Task 2: Frontend scaffold

**Files:**
- Create: `frontend/` (entire Vite scaffold)
- Modify: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/vite-env.d.ts`
- Create: `frontend/.env.development`
- Delete: `frontend/src/App.css`, `frontend/src/assets/react.svg`, default template markup in `App.tsx`

**Interfaces:**
- Produces: A running Vite dev server, an `App.tsx` route table wired to placeholder pages, `index.css` design tokens (from the Design System section above) available globally, and `VITE_API_BASE_URL` typed and readable via `import.meta.env`.

- [ ] **Step 1: Scaffold the project**

From the repo root:
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install react-router-dom
```

- [ ] **Step 2: Remove template cruft**

```bash
rm -f src/App.css
rm -rf src/assets
```

- [ ] **Step 3: Write the env file and its types**

Create `frontend/.env.development`:
```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Replace `frontend/src/vite-env.d.ts`:
```typescript
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
```

- [ ] **Step 4: Write the design tokens and global styles**

Replace `frontend/src/index.css`:
```css
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
  --color-canvas: #14171c;
  --color-surface: #1b1f26;
  --color-surface-raised: #232832;
  --color-border: #2b303b;
  --color-text: #ece9e4;
  --color-text-muted: #8d93a1;
  --color-accent: #f2a93b;
  --color-accent-strong: #ffc469;
  --color-positive: #4fd1c5;
  --color-danger: #e2574c;
  --color-danger-strong: #ff7b70;

  --font-display: 'Space Grotesk', system-ui, sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-mono: 'IBM Plex Mono', 'SFMono-Regular', monospace;

  --radius: 6px;
  --sidebar-width: 240px;
}

* {
  box-sizing: border-box;
}

html, body, #root {
  height: 100%;
}

body {
  margin: 0;
  background: var(--color-canvas);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: 15px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3 {
  font-family: var(--font-display);
  font-weight: 600;
  margin: 0;
}

button, input, textarea {
  font-family: inherit;
  font-size: inherit;
  color: inherit;
}

button {
  cursor: pointer;
}

a {
  color: var(--color-accent);
  text-decoration: none;
}
a:hover {
  text-decoration: underline;
}

:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface-raised);
  color: var(--color-text);
  font-weight: 500;
  transition: border-color 120ms ease, background 120ms ease;
}
.btn:hover {
  border-color: var(--color-accent);
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--color-accent);
  border-color: var(--color-accent);
  color: #1a1300;
}
.btn-primary:hover {
  background: var(--color-accent-strong);
  border-color: var(--color-accent-strong);
}

.btn-danger {
  border-color: var(--color-danger);
  color: var(--color-danger-strong);
  background: transparent;
}
.btn-danger:hover {
  background: rgba(226, 87, 76, 0.12);
}

.btn-ghost {
  background: transparent;
  border-color: transparent;
}
.btn-ghost:hover {
  border-color: var(--color-border);
}

.input {
  width: 100%;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text);
}
.input:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 1px;
}

.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}

.mono {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--color-text-muted);
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}
.field label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-muted);
}
```

- [ ] **Step 5: Write placeholder pages and the route table**

Create six placeholder files, each just a named export returning a `<p>` tag, so the route table has something to point at until later tasks fill them in:

`frontend/src/auth/SignInPage.tsx`:
```tsx
export function SignInPage() {
  return <p>Sign in (Task 4)</p>;
}
```

`frontend/src/auth/SignUpPage.tsx`:
```tsx
export function SignUpPage() {
  return <p>Sign up (Task 4)</p>;
}
```

`frontend/src/pages/DashboardPage.tsx`:
```tsx
export function DashboardPage() {
  return <p>Dashboard (Task 6)</p>;
}
```

`frontend/src/pages/CreateAgentPage.tsx`:
```tsx
export function CreateAgentPage() {
  return <p>Create agent (Task 7)</p>;
}
```

`frontend/src/pages/CreateChatbotPage.tsx`:
```tsx
export function CreateChatbotPage() {
  return <p>Create chatbot (Task 7)</p>;
}
```

`frontend/src/pages/AgentDetailPage.tsx`:
```tsx
export function AgentDetailPage() {
  return <p>Agent detail (Task 9)</p>;
}
```

`frontend/src/pages/ChatbotDetailPage.tsx`:
```tsx
export function ChatbotDetailPage() {
  return <p>Chatbot detail (Task 10)</p>;
}
```

Replace `frontend/src/App.tsx`:
```tsx
import { Navigate, Route, Routes } from 'react-router-dom';
import { SignInPage } from './auth/SignInPage';
import { SignUpPage } from './auth/SignUpPage';
import { DashboardPage } from './pages/DashboardPage';
import { CreateAgentPage } from './pages/CreateAgentPage';
import { CreateChatbotPage } from './pages/CreateChatbotPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { ChatbotDetailPage } from './pages/ChatbotDetailPage';

export function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/" element={<DashboardPage />} />
      <Route path="/agents/new" element={<CreateAgentPage />} />
      <Route path="/agents/:agentId" element={<AgentDetailPage />} />
      <Route path="/chatbots/new" element={<CreateChatbotPage />} />
      <Route path="/chatbots/:chatbotId" element={<ChatbotDetailPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

Replace `frontend/src/main.tsx`:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
```

(`AuthProvider` and route protection are added around this tree in Task 4 — this task only needs routing to work end-to-end.)

- [ ] **Step 6: Verify the scaffold builds and type-checks**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: both succeed with no errors.

- [ ] **Step 7: Verify the dev server boots and routes render**

Run: `cd frontend && npm run dev &` then `sleep 2 && curl -s http://localhost:5173/ | grep -o '<title>[^<]*</title>'`, then kill the dev server.
Expected: the dev server responds on port 5173 (title tag present — exact text doesn't matter yet).

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat: scaffold Vite + React + TypeScript frontend with design tokens and route table"
```

---

### Task 3: API client layer

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/agents.ts`
- Create: `frontend/src/api/chatbots.ts`
- Create: `frontend/src/api/sessions.ts`
- Create: `frontend/src/api/chat.ts`
- Create: `frontend/src/api/ingest.ts`
- Create: `frontend/src/lib/errors.ts`

**Interfaces:**
- Consumes: `import.meta.env.VITE_API_BASE_URL` (Task 2).
- Produces: `api.get/post/postForm/del` low-level helpers; `ApiError` class; `setAuthToken(token: string | null)`; one typed function per backend endpoint the frontend calls; `describeError(err: unknown): string`. Every later task's data fetching goes through these functions — their names and signatures below are final and used verbatim in Tasks 4–11.

- [ ] **Step 1: Write shared types**

Create `frontend/src/api/types.ts`:
```typescript
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
```

- [ ] **Step 2: Write the fetch wrapper and ApiError**

Create `frontend/src/api/client.ts`:
```typescript
export class ApiError extends Error {
  status: number;
  detail: string | Record<string, unknown> | unknown[];

  constructor(status: number, detail: string | Record<string, unknown> | unknown[]) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  isFormData?: boolean;
  query?: Record<string, string | undefined>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, isFormData = false, query } = options;

  let url = `${API_BASE_URL}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) params.set(key, value);
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  const headers: Record<string, string> = {};
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  if (!isFormData && body !== undefined) headers['Content-Type'] = 'application/json';

  const response = await fetch(url, {
    method,
    headers,
    body: isFormData ? (body as FormData) : body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail: string | Record<string, unknown> | unknown[] = response.statusText;
    try {
      const data = await response.json();
      detail = data?.detail ?? data;
    } catch {
      // no JSON body on this error response — keep statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T,>(path: string, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'GET', query }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  postForm: <T,>(path: string, formData: FormData, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'POST', body: formData, isFormData: true, query }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
};
```

- [ ] **Step 3: Write the error-formatting helper**

Create `frontend/src/lib/errors.ts`:
```typescript
import { ApiError } from '../api/client';

export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === 'string') return err.detail;
    return JSON.stringify(err.detail);
  }
  if (err instanceof Error) return err.message;
  return 'Something went wrong.';
}
```

- [ ] **Step 4: Write per-resource API functions**

Create `frontend/src/api/auth.ts`:
```typescript
import { api } from './client';
import type { AuthResponse } from './types';

export function signUp(email: string, password: string) {
  return api.post<AuthResponse>('/auth/signup', { email, password });
}

export function signIn(email: string, password: string) {
  return api.post<AuthResponse>('/auth/signin', { email, password });
}
```

Create `frontend/src/api/agents.ts`:
```typescript
import { api } from './client';
import type { AgentCreated, AgentSummary } from './types';

export function listAgents() {
  return api.get<AgentSummary[]>('/agents');
}

export function createAgent(name: string, systemPrompt?: string) {
  return api.post<AgentCreated>('/agents', { name, system_prompt: systemPrompt });
}
```

Create `frontend/src/api/chatbots.ts`:
```typescript
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

export function createChatbot(name: string, agentName: string, roleDescription: string, systemPrompt?: string) {
  return api.post<ChatbotCreated>('/chatbots', {
    name,
    agent_name: agentName,
    role_description: roleDescription,
    system_prompt: systemPrompt,
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
```

Create `frontend/src/api/sessions.ts`:
```typescript
import { api } from './client';
import type { AttachDocumentResult, DeleteResult, SessionMessage, SessionSummary } from './types';

export function listSessions(agentId: string) {
  return api.get<SessionSummary[]>(`/agents/${agentId}/sessions`);
}

export function getSessionMessages(agentId: string, sessionId: string) {
  return api.get<{ messages: SessionMessage[] }>(`/agents/${agentId}/sessions/${sessionId}/messages`);
}

export function deleteSession(agentId: string, sessionId: string) {
  return api.del<DeleteResult & { kb_deleted: boolean }>(`/agents/${agentId}/sessions/${sessionId}`);
}

export function attachDocumentToSession(agentId: string, sessionId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return api.postForm<AttachDocumentResult>(`/agents/${agentId}/sessions/${sessionId}/attach-document`, formData);
}
```

Create `frontend/src/api/chat.ts`:
```typescript
import { api } from './client';
import type { ChatResult } from './types';

export function chatWithAgent(agentId: string, message: string, sessionId?: string | null, label?: string) {
  return api.post<ChatResult>('/chat', {
    agent_id: agentId,
    message,
    session_id: sessionId ?? undefined,
    label,
  });
}
```

Create `frontend/src/api/ingest.ts`:
```typescript
import { api } from './client';
import type { AttachDocumentResult } from './types';

export function ingestFile(agentId: string, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  return api.postForm<AttachDocumentResult>('/ingest/file', formData, { agent_id: agentId });
}
```

- [ ] **Step 5: Verify types and build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors (nothing imports these modules yet, but they must type-check standalone).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api frontend/src/lib
git commit -m "feat: add typed API client layer for the backend"
```

---

### Task 4: Auth (context, protected routes, sign in/up pages)

**Files:**
- Create: `frontend/src/auth/AuthContext.tsx`
- Create: `frontend/src/auth/ProtectedRoute.tsx`
- Modify: `frontend/src/auth/SignInPage.tsx`
- Modify: `frontend/src/auth/SignUpPage.tsx`
- Create: `frontend/src/auth/AuthPage.module.css`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: `signIn`/`signUp` from `api/auth.ts`, `setAuthToken` from `api/client.ts`, `describeError` from `lib/errors.ts` (Task 3).
- Produces: `AuthProvider`, `useAuth(): { token: string | null; userEmail: string | null; signIn; signUp; signOut }`, `ProtectedRoute`. `signUp` returns `Promise<{ loggedIn: boolean }>` — `loggedIn` is `false` when GoTrue's signup response has no `access_token` (email confirmation required), which later steps in this task handle explicitly rather than assuming signup always logs a user in.

- [ ] **Step 1: Write the auth context**

Create `frontend/src/auth/AuthContext.tsx`:
```tsx
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { signIn as signInApi, signUp as signUpApi } from '../api/auth';
import { setAuthToken } from '../api/client';

interface AuthContextValue {
  token: string | null;
  userEmail: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<{ loggedIn: boolean }>;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const STORAGE_KEY = 'powabase_auth';

interface StoredAuth {
  token: string;
  email: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const stored: StoredAuth = JSON.parse(raw);
      setAuthToken(stored.token);
      setToken(stored.token);
      setUserEmail(stored.email);
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  function persist(newToken: string, email: string) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: newToken, email }));
    setAuthToken(newToken);
    setToken(newToken);
    setUserEmail(email);
  }

  async function signIn(email: string, password: string) {
    const res = await signInApi(email, password);
    if (!res.access_token) throw new Error('Sign in did not return an access token.');
    persist(res.access_token, res.user?.email ?? email);
  }

  async function signUp(email: string, password: string): Promise<{ loggedIn: boolean }> {
    const res = await signUpApi(email, password);
    if (res.access_token) {
      persist(res.access_token, res.user?.email ?? email);
      return { loggedIn: true };
    }
    return { loggedIn: false };
  }

  function signOut() {
    localStorage.removeItem(STORAGE_KEY);
    setAuthToken(null);
    setToken(null);
    setUserEmail(null);
  }

  return (
    <AuthContext.Provider value={{ token, userEmail, signIn, signUp, signOut }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
```

- [ ] **Step 2: Write the protected route wrapper**

Create `frontend/src/auth/ProtectedRoute.tsx`:
```tsx
import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/signin" replace />;
  return <>{children}</>;
}
```

- [ ] **Step 3: Write the shared auth page stylesheet**

Create `frontend/src/auth/AuthPage.module.css`:
```css
.page {
  min-height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.card {
  width: 100%;
  max-width: 380px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 32px;
}

.title {
  font-size: 24px;
  margin-bottom: 4px;
}

.subtitle {
  color: var(--color-text-muted);
  margin: 0 0 24px;
  font-size: 14px;
}

.error, .notice {
  padding: 10px 12px;
  border-radius: var(--radius);
  font-size: 13px;
  margin-bottom: 16px;
}

.error {
  background: rgba(226, 87, 76, 0.12);
  color: var(--color-danger-strong);
}

.notice {
  background: rgba(79, 209, 197, 0.12);
  color: var(--color-positive);
}

.switch {
  margin: 16px 0 0;
  font-size: 13px;
  color: var(--color-text-muted);
}
```

- [ ] **Step 4: Write the sign-in page**

Replace `frontend/src/auth/SignInPage.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { describeError } from '../lib/errors';
import styles from './AuthPage.module.css';

export function SignInPage() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email, password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(describeError(err));
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <form className={styles.card} onSubmit={handleSubmit}>
        <h1 className={styles.title}>Sign in</h1>
        <p className={styles.subtitle}>Access your agents and chatbots.</p>
        {error && <div className={styles.error}>{error}</div>}
        <div className="field">
          <label htmlFor="signin-email">Email</label>
          <input
            id="signin-email"
            className="input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="signin-password">Password</label>
          <input
            id="signin-password"
            className="input"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
        <p className={styles.switch}>
          No account yet? <Link to="/signup">Create one</Link>
        </p>
      </form>
    </div>
  );
}
```

- [ ] **Step 5: Write the sign-up page**

Replace `frontend/src/auth/SignUpPage.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { describeError } from '../lib/errors';
import styles from './AuthPage.module.css';

export function SignUpPage() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const { loggedIn } = await signUp(email, password);
      if (loggedIn) {
        navigate('/', { replace: true });
        return;
      }
      setNotice('Account created. Check your email to confirm it, then sign in.');
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <form className={styles.card} onSubmit={handleSubmit}>
        <h1 className={styles.title}>Create an account</h1>
        <p className={styles.subtitle}>Build agents and chatbots on Powabase.</p>
        {error && <div className={styles.error}>{error}</div>}
        {notice && <div className={styles.notice}>{notice}</div>}
        <div className="field">
          <label htmlFor="signup-email">Email</label>
          <input
            id="signup-email"
            className="input"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="signup-password">Password</label>
          <input
            id="signup-password"
            className="input"
            type="password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
        <p className={styles.switch}>
          Already have an account? <Link to="/signin">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
```

- [ ] **Step 6: Wrap the app in AuthProvider and gate protected routes**

Replace `frontend/src/main.tsx`:
```tsx
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { AuthProvider } from './auth/AuthContext';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
```

Update `frontend/src/App.tsx` to gate the dashboard/create/detail routes behind `ProtectedRoute` (the `AppShell` wrapper referenced here is built in Task 5 — for this task, gate the routes directly with a plain `<Outlet/>`-free approach so the app still compiles: wrap each protected `element` individually):
```tsx
import { Navigate, Route, Routes } from 'react-router-dom';
import { SignInPage } from './auth/SignInPage';
import { SignUpPage } from './auth/SignUpPage';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { DashboardPage } from './pages/DashboardPage';
import { CreateAgentPage } from './pages/CreateAgentPage';
import { CreateChatbotPage } from './pages/CreateChatbotPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { ChatbotDetailPage } from './pages/ChatbotDetailPage';

export function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/agents/new" element={<ProtectedRoute><CreateAgentPage /></ProtectedRoute>} />
      <Route path="/agents/:agentId" element={<ProtectedRoute><AgentDetailPage /></ProtectedRoute>} />
      <Route path="/chatbots/new" element={<ProtectedRoute><CreateChatbotPage /></ProtectedRoute>} />
      <Route path="/chatbots/:chatbotId" element={<ProtectedRoute><ChatbotDetailPage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```
(Task 5 replaces this again to nest routes under `AppShell` via a layout route — noted there so this task's version isn't mistaken for final.)

- [ ] **Step 7: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 8: Manual smoke check against the live backend**

Start the backend (`.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`) and frontend (`cd frontend && npm run dev`). In a browser at `http://localhost:5173/signup`, sign up with a fresh test email/password. Expected: either redirected to `/` (dashboard placeholder text) if auto-confirmed, or shown the "check your email" notice. Then visit `/signin` and sign in with the same credentials — expected: redirected to `/`. Visiting `/` while signed out (clear localStorage) should redirect to `/signin`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/auth frontend/src/main.tsx frontend/src/App.tsx
git commit -m "feat: add auth context, protected routes, and sign in/up pages"
```

---

### Task 5: Shared UI primitives

**Files:**
- Create: `frontend/src/hooks/useAsync.ts`
- Create: `frontend/src/components/AppShell.tsx`, `frontend/src/components/AppShell.module.css`
- Create: `frontend/src/components/EmptyState.tsx`, `frontend/src/components/EmptyState.module.css`
- Create: `frontend/src/components/ErrorBanner.tsx`, `frontend/src/components/ErrorBanner.module.css`
- Create: `frontend/src/components/Spinner.tsx`, `frontend/src/components/Spinner.module.css`
- Create: `frontend/src/components/ConfirmButton.tsx`
- Modify: `frontend/src/App.tsx` (nest protected routes under `AppShell`)

**Interfaces:**
- Consumes: `useAuth` (Task 4), `describeError` (Task 3).
- Produces: `useAsync<T>(fn, deps): { data: T | null; loading: boolean; error: string | null; reload: () => void }`; `<AppShell/>` (a layout route rendering `<Outlet/>`); `<EmptyState title description/>`; `<ErrorBanner message/>`; `<Spinner/>`; `<ConfirmButton label confirmLabel? variant? onConfirm/>`. All of Tasks 6–11 build their loading/error/empty states and destructive actions out of these.

- [ ] **Step 1: Write the async data-fetching hook**

Create `frontend/src/hooks/useAsync.ts`:
```typescript
import { useEffect, useState, type DependencyList } from 'react';
import { describeError } from '../lib/errors';

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useAsync<T>(fn: () => Promise<T>, deps: DependencyList): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey]);

  return { data, loading, error, reload: () => setReloadKey((k) => k + 1) };
}
```

- [ ] **Step 2: Write EmptyState, ErrorBanner, Spinner**

Create `frontend/src/components/EmptyState.module.css`:
```css
.empty {
  padding: 32px 20px;
  text-align: center;
  border: 1px dashed var(--color-border);
  border-radius: var(--radius);
  color: var(--color-text-muted);
}
.title {
  color: var(--color-text);
  font-family: var(--font-display);
  font-weight: 600;
  margin: 0 0 4px;
}
.description {
  margin: 0;
  font-size: 14px;
}
```

Create `frontend/src/components/EmptyState.tsx`:
```tsx
import styles from './EmptyState.module.css';

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className={styles.empty}>
      <p className={styles.title}>{title}</p>
      <p className={styles.description}>{description}</p>
    </div>
  );
}
```

Create `frontend/src/components/ErrorBanner.module.css`:
```css
.banner {
  padding: 10px 12px;
  border-radius: var(--radius);
  background: rgba(226, 87, 76, 0.12);
  color: var(--color-danger-strong);
  font-size: 13px;
}
```

Create `frontend/src/components/ErrorBanner.tsx`:
```tsx
import styles from './ErrorBanner.module.css';

export function ErrorBanner({ message }: { message: string }) {
  return <div className={styles.banner}>{message}</div>;
}
```

Create `frontend/src/components/Spinner.module.css`:
```css
.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid var(--color-border);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: spin 700ms linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
```

Create `frontend/src/components/Spinner.tsx`:
```tsx
import styles from './Spinner.module.css';

export function Spinner() {
  return <div className={styles.spinner} role="status" aria-label="Loading" />;
}
```

- [ ] **Step 3: Write ConfirmButton**

Create `frontend/src/components/ConfirmButton.tsx`:
```tsx
import { useEffect, useState } from 'react';

interface ConfirmButtonProps {
  label: string;
  confirmLabel?: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
}

export function ConfirmButton({ label, confirmLabel = 'Confirm', variant = 'danger', onConfirm }: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!confirming) return;
    const timer = setTimeout(() => setConfirming(false), 3000);
    return () => clearTimeout(timer);
  }, [confirming]);

  if (confirming) {
    return (
      <button
        type="button"
        className={variant === 'danger' ? 'btn btn-danger' : 'btn'}
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
    );
  }

  return (
    <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)}>
      {label}
    </button>
  );
}
```

- [ ] **Step 4: Write AppShell**

Create `frontend/src/components/AppShell.module.css`:
```css
.shell {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  padding: 20px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 32px;
}

.brandMark {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-accent);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.navLink, .navLinkActive {
  padding: 8px 10px;
  border-radius: var(--radius);
  color: var(--color-text-muted);
  font-size: 14px;
}
.navLink:hover {
  color: var(--color-text);
  text-decoration: none;
}
.navLinkActive {
  background: var(--color-surface-raised);
  color: var(--color-text);
  border: 1px solid var(--color-border);
}

.account {
  border-top: 1px solid var(--color-border);
  padding-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.email {
  font-size: 12px;
  color: var(--color-text-muted);
  word-break: break-all;
}

.main {
  flex: 1;
  padding: 32px;
  min-width: 0;
}
```

Create `frontend/src/components/AppShell.tsx`:
```tsx
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import styles from './AppShell.module.css';

export function AppShell() {
  const { userEmail, signOut } = useAuth();

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark} />
          Powabase
        </div>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.navLinkActive : styles.navLink)}>
            Dashboard
          </NavLink>
        </nav>
        <div className={styles.account}>
          {userEmail && <span className={styles.email}>{userEmail}</span>}
          <button type="button" className="btn btn-ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Nest protected routes under AppShell**

Replace `frontend/src/App.tsx`:
```tsx
import { Navigate, Route, Routes } from 'react-router-dom';
import { SignInPage } from './auth/SignInPage';
import { SignUpPage } from './auth/SignUpPage';
import { ProtectedRoute } from './auth/ProtectedRoute';
import { AppShell } from './components/AppShell';
import { DashboardPage } from './pages/DashboardPage';
import { CreateAgentPage } from './pages/CreateAgentPage';
import { CreateChatbotPage } from './pages/CreateChatbotPage';
import { AgentDetailPage } from './pages/AgentDetailPage';
import { ChatbotDetailPage } from './pages/ChatbotDetailPage';

export function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignInPage />} />
      <Route path="/signup" element={<SignUpPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/agents/new" element={<CreateAgentPage />} />
        <Route path="/agents/:agentId" element={<AgentDetailPage />} />
        <Route path="/chatbots/new" element={<CreateChatbotPage />} />
        <Route path="/chatbots/:chatbotId" element={<ChatbotDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
```

- [ ] **Step 6: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 7: Manual check**

With both servers running and a signed-in session, visit `http://localhost:5173/`. Expected: sidebar with "Powabase" brand, "Dashboard" nav link, your email, and a "Sign out" button that returns you to `/signin` and clears `localStorage`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/hooks frontend/src/components frontend/src/App.tsx
git commit -m "feat: add app shell layout and shared loading/error/empty/confirm primitives"
```

---

### Task 6: Dashboard page

**Files:**
- Create: `frontend/src/components/Card.module.css`
- Create: `frontend/src/components/AgentCard.tsx`
- Create: `frontend/src/components/ChatbotCard.tsx`
- Modify: `frontend/src/pages/DashboardPage.tsx`
- Create: `frontend/src/pages/DashboardPage.module.css`

**Interfaces:**
- Consumes: `listAgents`, `listChatbots` (Task 3); `useAsync` (Task 5); `EmptyState`, `ErrorBanner`, `Spinner` (Task 5).
- Produces: the `/` route showing "My agents" and "My chatbots" sections, each with a "Create new" link.

- [ ] **Step 1: Write the shared card stylesheet**

Create `frontend/src/components/Card.module.css`:
```css
.card {
  position: relative;
  display: block;
  padding: 16px 16px 16px 20px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  text-decoration: none;
  color: var(--color-text);
  transition: border-color 120ms ease, transform 120ms ease;
}
.card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 16px;
  bottom: 16px;
  width: 2px;
  background: var(--color-border);
}
.card:hover {
  border-color: var(--color-accent);
  transform: translateY(-1px);
  text-decoration: none;
}
.card:hover::before {
  background: var(--color-accent);
}

.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-positive);
  margin-right: 6px;
}

.name {
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 16px;
  margin: 0 0 4px;
}

.meta {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--color-text-muted);
}
```

- [ ] **Step 2: Write AgentCard and ChatbotCard**

Create `frontend/src/components/AgentCard.tsx`:
```tsx
import { Link } from 'react-router-dom';
import type { AgentSummary } from '../api/types';
import styles from './Card.module.css';

export function AgentCard({ agent }: { agent: AgentSummary }) {
  return (
    <Link to={`/agents/${agent.agent_id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        {agent.name}
      </p>
      <p className={styles.meta}>{agent.agent_id}</p>
    </Link>
  );
}
```

Create `frontend/src/components/ChatbotCard.tsx`:
```tsx
import { Link } from 'react-router-dom';
import type { ChatbotSummary } from '../api/types';
import styles from './Card.module.css';

export function ChatbotCard({ chatbot }: { chatbot: ChatbotSummary }) {
  return (
    <Link to={`/chatbots/${chatbot.id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        {chatbot.name}
      </p>
      <p className={styles.meta}>{chatbot.orchestrator_id}</p>
    </Link>
  );
}
```

- [ ] **Step 3: Write the Dashboard page**

Create `frontend/src/pages/DashboardPage.module.css`:
```css
.section {
  margin-bottom: 40px;
}
.sectionHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
```

Replace `frontend/src/pages/DashboardPage.tsx`:
```tsx
import { Link } from 'react-router-dom';
import { listAgents } from '../api/agents';
import { listChatbots } from '../api/chatbots';
import { useAsync } from '../hooks/useAsync';
import { AgentCard } from '../components/AgentCard';
import { ChatbotCard } from '../components/ChatbotCard';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import styles from './DashboardPage.module.css';

export function DashboardPage() {
  const agents = useAsync(() => listAgents(), []);
  const chatbots = useAsync(() => listChatbots(), []);

  return (
    <div>
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>My agents</h2>
          <Link className="btn btn-primary" to="/agents/new">
            Create new
          </Link>
        </div>
        {agents.loading && <Spinner />}
        {agents.error && <ErrorBanner message={agents.error} />}
        {!agents.loading && !agents.error && agents.data?.length === 0 && (
          <EmptyState
            title="No agents yet"
            description="Create a standalone agent to start chatting and uploading documents."
          />
        )}
        {!agents.loading && !agents.error && agents.data && agents.data.length > 0 && (
          <div className={styles.grid}>
            {agents.data.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>My chatbots</h2>
          <Link className="btn btn-primary" to="/chatbots/new">
            Create new
          </Link>
        </div>
        {chatbots.loading && <Spinner />}
        {chatbots.error && <ErrorBanner message={chatbots.error} />}
        {!chatbots.loading && !chatbots.error && chatbots.data?.length === 0 && (
          <EmptyState
            title="No chatbots yet"
            description="Create a chatbot to orchestrate multiple agents behind one conversation."
          />
        )}
        {!chatbots.loading && !chatbots.error && chatbots.data && chatbots.data.length > 0 && (
          <div className={styles.grid}>
            {chatbots.data.map((chatbot) => (
              <ChatbotCard key={chatbot.id} chatbot={chatbot} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 5: Manual check**

Sign in, land on `/`. Expected: "No agents yet" / "No chatbots yet" empty states on a fresh account, each section's "Create new" button navigating to `/agents/new` / `/chatbots/new` (still placeholders until Task 7).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Card.module.css frontend/src/components/AgentCard.tsx frontend/src/components/ChatbotCard.tsx frontend/src/pages/DashboardPage.tsx frontend/src/pages/DashboardPage.module.css
git commit -m "feat: add dashboard page listing agents and chatbots"
```

---

### Task 7: Create-agent and create-chatbot pages

**Files:**
- Create: `frontend/src/pages/FormPage.module.css`
- Modify: `frontend/src/pages/CreateAgentPage.tsx`
- Modify: `frontend/src/pages/CreateChatbotPage.tsx`

**Interfaces:**
- Consumes: `createAgent` (Task 3), `createChatbot` (Task 3), `ErrorBanner` (Task 5).
- Produces: `/agents/new` posting to `POST /agents` and redirecting to `/agents/:agentId` (using the created row's `agent_id`, per the route-param identity rule); `/chatbots/new` posting to `POST /chatbots` and redirecting to `/chatbots/:chatbotId` (using `chatbot.id`).

- [ ] **Step 1: Write the shared form-page stylesheet**

Create `frontend/src/pages/FormPage.module.css`:
```css
.page {
  max-width: 480px;
}
.form {
  margin-top: 20px;
}
```

- [ ] **Step 2: Write CreateAgentPage**

Replace `frontend/src/pages/CreateAgentPage.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createAgent } from '../api/agents';
import { describeError } from '../lib/errors';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateAgentPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const agent = await createAgent(name.trim(), systemPrompt.trim() || undefined);
      navigate(`/agents/${agent.agent_id}`, { replace: true });
    } catch (err) {
      setError(describeError(err));
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <h1>Create an agent</h1>
      <form className={styles.form} onSubmit={handleSubmit}>
        {error && <ErrorBanner message={error} />}
        <div className="field">
          <label htmlFor="agent-name">Name</label>
          <input
            id="agent-name"
            className="input"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="agent-prompt">System prompt (optional)</label>
          <textarea
            id="agent-prompt"
            className="input"
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !name.trim()}>
          {submitting ? 'Creating…' : 'Create agent'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Write CreateChatbotPage**

Replace `frontend/src/pages/CreateChatbotPage.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChatbot } from '../api/chatbots';
import { describeError } from '../lib/errors';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateChatbotPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [agentName, setAgentName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await createChatbot(
        name.trim(),
        agentName.trim(),
        roleDescription.trim(),
        systemPrompt.trim() || undefined,
      );
      navigate(`/chatbots/${result.chatbot.id}`, { replace: true });
    } catch (err) {
      setError(describeError(err));
      setSubmitting(false);
    }
  }

  const canSubmit = name.trim() && agentName.trim() && roleDescription.trim();

  return (
    <div className={styles.page}>
      <h1>Create a chatbot</h1>
      <form className={styles.form} onSubmit={handleSubmit}>
        {error && <ErrorBanner message={error} />}
        <div className="field">
          <label htmlFor="chatbot-name">Chatbot name</label>
          <input
            id="chatbot-name"
            className="input"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-agent-name">First agent's name</label>
          <input
            id="chatbot-agent-name"
            className="input"
            required
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-role">Role description</label>
          <textarea
            id="chatbot-role"
            className="input"
            rows={3}
            required
            placeholder="What this agent handles, so the orchestrator knows when to route to it."
            value={roleDescription}
            onChange={(e) => setRoleDescription(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="chatbot-prompt">System prompt (optional)</label>
          <textarea
            id="chatbot-prompt"
            className="input"
            rows={4}
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !canSubmit}>
          {submitting ? 'Creating…' : 'Create chatbot'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 5: Manual check**

From the dashboard, click "Create new" under "My agents", submit a name, expect a redirect to `/agents/<agent_id>` (still a placeholder page). Same for "My chatbots" → `/chatbots/<chatbot_id>`. Submit an empty required field and confirm the button stays disabled; trigger a backend error (e.g., stop the backend mid-submit) and confirm the error banner shows the backend's message.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/FormPage.module.css frontend/src/pages/CreateAgentPage.tsx frontend/src/pages/CreateChatbotPage.tsx
git commit -m "feat: add create-agent and create-chatbot forms"
```

---

### Task 8: Shared conversation building blocks (ChatPanel, SessionHistoryPanel, useConversation, FileUploadButton)

**Files:**
- Create: `frontend/src/components/ChatPanel.tsx`, `frontend/src/components/ChatPanel.module.css`
- Create: `frontend/src/components/SessionHistoryPanel.tsx`, `frontend/src/components/SessionHistoryPanel.module.css`
- Create: `frontend/src/hooks/useConversation.ts`
- Create: `frontend/src/components/FileUploadButton.tsx`, `frontend/src/components/FileUploadButton.module.css`

**Interfaces:**
- Consumes: `SessionMessage`, `SessionSummary`, `ChatResult` types (Task 3); `describeError` (Task 3); `ConfirmButton`, `EmptyState`, `ErrorBanner`, `Spinner` (Task 5).
- Produces:
  - `<ChatPanel initialMessages? initialSessionId? sendMessage onSessionStart? />` — `sendMessage: (message: string, sessionId: string | null) => Promise<ChatResult>` is supplied by the caller, so the same component drives both `POST /chat` (agent) and `POST /chatbots/{id}/chat` (chatbot). Calls `onSessionStart(sessionId)` exactly once, the moment `sessionId` transitions from `null` to a value (i.e. after the first successful response in a brand-new conversation) — never again after that, since the session id doesn't change again for that conversation.
  - `<SessionHistoryPanel loading error sessions onContinue onDelete? />` — `onDelete` omitted entirely hides the delete button (used for chatbot sessions, which have no delete endpoint).
  - `useConversation(loadMessages: (sessionId: string) => Promise<{ messages: SessionMessage[] }>)` returns `{ chatConfig, activeSessionId, startNewChat, continueSession, clear, onSessionStart }`. `chatConfig` is `null` until a conversation is started; its `key` field is used as React's `key` prop on `<ChatPanel/>` so switching between "new chat" and "continue session N" forces a clean remount, while `activeSessionId` updates independently via `onSessionStart` without remounting the panel mid-conversation (a session's id becomes known only after its first response, and remounting at that point would silently discard the panel's in-progress message list).
  - `<FileUploadButton id label helpText? disabled? disabledText? onUpload />` — generic file-picker button with its own upload/success/error state, reused for both the permanent agent-document upload (Task 9) and the attach-to-conversation upload (Task 9).

- [ ] **Step 1: Write the conversation state hook**

Create `frontend/src/hooks/useConversation.ts`:
```typescript
import { useState } from 'react';
import type { SessionMessage, SessionSummary } from '../api/types';

interface ChatConfig {
  key: string;
  initialMessages: SessionMessage[];
  initialSessionId: string | null;
}

export function useConversation(loadMessages: (sessionId: string) => Promise<{ messages: SessionMessage[] }>) {
  const [chatConfig, setChatConfig] = useState<ChatConfig | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  function startNewChat() {
    setChatConfig({ key: `new-${Date.now()}`, initialMessages: [], initialSessionId: null });
    setActiveSessionId(null);
  }

  async function continueSession(session: SessionSummary) {
    const { messages } = await loadMessages(session.session_id);
    setChatConfig({ key: session.session_id, initialMessages: messages, initialSessionId: session.session_id });
    setActiveSessionId(session.session_id);
  }

  function clear() {
    setChatConfig(null);
    setActiveSessionId(null);
  }

  return {
    chatConfig,
    activeSessionId,
    startNewChat,
    continueSession,
    clear,
    onSessionStart: setActiveSessionId,
  };
}
```

- [ ] **Step 2: Write ChatPanel**

Create `frontend/src/components/ChatPanel.module.css`:
```css
.panel {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
  height: 480px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty {
  color: var(--color-text-muted);
  font-size: 14px;
  margin: auto;
}
.bubbleUser, .bubbleAssistant {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubbleUser {
  align-self: flex-end;
  background: var(--color-accent);
  color: #1a1300;
}
.bubbleAssistant {
  align-self: flex-start;
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border);
}
.typing {
  color: var(--color-text-muted);
  font-style: italic;
}
.error {
  margin: 0 16px;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: rgba(226, 87, 76, 0.12);
  color: var(--color-danger-strong);
  font-size: 13px;
}
.inputRow {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--color-border);
}
```

Create `frontend/src/components/ChatPanel.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import type { ChatResult, SessionMessage } from '../api/types';
import { describeError } from '../lib/errors';
import styles from './ChatPanel.module.css';

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface ChatPanelProps {
  initialMessages?: SessionMessage[];
  initialSessionId?: string | null;
  sendMessage: (message: string, sessionId: string | null) => Promise<ChatResult>;
  onSessionStart?: (sessionId: string) => void;
}

export function ChatPanel({
  initialMessages = [],
  initialSessionId = null,
  sendMessage,
  onSessionStart,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>(
    initialMessages.map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content })),
  );
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setError(null);
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setSending(true);
    try {
      const result = await sendMessage(text, sessionId);
      setMessages((prev) => [...prev, { role: 'assistant', content: result.content }]);
      if (sessionId === null) {
        setSessionId(result.session_id);
        onSessionStart?.(result.session_id);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.messages}>
        {messages.length === 0 && !sending && <p className={styles.empty}>Say something to start the conversation.</p>}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant}>
            {m.content}
          </div>
        ))}
        {sending && (
          <div className={styles.bubbleAssistant}>
            <span className={styles.typing}>Thinking…</span>
          </div>
        )}
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <form className={styles.inputRow} onSubmit={handleSend}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder="Type a message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
        />
        <button className="btn btn-primary" type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Write SessionHistoryPanel**

Create `frontend/src/components/SessionHistoryPanel.module.css`:
```css
.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-surface);
}
.label {
  margin: 0 0 2px;
  font-weight: 500;
}
.actions {
  display: flex;
  gap: 8px;
}
```

Create `frontend/src/components/SessionHistoryPanel.tsx`:
```tsx
import type { SessionSummary } from '../api/types';
import { ConfirmButton } from './ConfirmButton';
import { EmptyState } from './EmptyState';
import { ErrorBanner } from './ErrorBanner';
import { Spinner } from './Spinner';
import styles from './SessionHistoryPanel.module.css';

interface SessionHistoryPanelProps {
  loading: boolean;
  error: string | null;
  sessions: SessionSummary[] | null;
  onContinue: (session: SessionSummary) => void;
  onDelete?: (session: SessionSummary) => void;
}

export function SessionHistoryPanel({ loading, error, sessions, onContinue, onDelete }: SessionHistoryPanelProps) {
  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  if (!sessions || sessions.length === 0) {
    return <EmptyState title="No past sessions" description="Start a chat below to create your first session." />;
  }

  return (
    <ul className={styles.list}>
      {sessions.map((session) => (
        <li key={session.id} className={styles.row}>
          <div>
            <p className={styles.label}>{session.label || 'Untitled session'}</p>
            <p className="mono">{new Date(session.created_at).toLocaleString()}</p>
          </div>
          <div className={styles.actions}>
            <button type="button" className="btn btn-ghost" onClick={() => onContinue(session)}>
              Continue
            </button>
            {onDelete && (
              <ConfirmButton label="Delete" confirmLabel="Confirm delete" onConfirm={() => onDelete(session)} />
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Write FileUploadButton**

Create `frontend/src/components/FileUploadButton.module.css`:
```css
.wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.hiddenInput {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
.help {
  margin: 0;
  font-size: 12px;
  color: var(--color-text-muted);
}
.success {
  margin: 0;
  font-size: 12px;
  color: var(--color-positive);
}
.error {
  margin: 0;
  font-size: 12px;
  color: var(--color-danger-strong);
}
```

Create `frontend/src/components/FileUploadButton.tsx`:
```tsx
import { useRef, useState, type ChangeEvent } from 'react';
import { describeError } from '../lib/errors';
import styles from './FileUploadButton.module.css';

interface FileUploadButtonProps {
  id: string;
  label: string;
  helpText?: string;
  disabled?: boolean;
  disabledText?: string;
  onUpload: (file: File) => Promise<unknown>;
}

export function FileUploadButton({ id, label, helpText, disabled, disabledText, onUpload }: FileUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  async function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setStatus(null);
    setUploading(true);
    try {
      await onUpload(file);
      setStatus({ type: 'success', message: `${file.name} uploaded.` });
    } catch (err) {
      setStatus({ type: 'error', message: describeError(err) });
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div className={styles.wrap}>
      <input
        ref={inputRef}
        id={id}
        type="file"
        className={styles.hiddenInput}
        onChange={handleChange}
        disabled={disabled || uploading}
      />
      <label htmlFor={id} className="btn">
        {uploading ? 'Uploading…' : label}
      </label>
      {!disabled && helpText && <p className={styles.help}>{helpText}</p>}
      {disabled && disabledText && <p className={styles.help}>{disabledText}</p>}
      {status && <p className={status.type === 'error' ? styles.error : styles.success}>{status.message}</p>}
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors (nothing consumes these yet outside this task's own files, but they must type-check standalone).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/components/ChatPanel.module.css frontend/src/components/SessionHistoryPanel.tsx frontend/src/components/SessionHistoryPanel.module.css frontend/src/hooks/useConversation.ts frontend/src/components/FileUploadButton.tsx frontend/src/components/FileUploadButton.module.css
git commit -m "feat: add reusable chat panel, session history panel, and file upload components"
```

---

### Task 9: Agent detail page

**Files:**
- Modify: `frontend/src/pages/AgentDetailPage.tsx`
- Create: `frontend/src/pages/AgentDetailPage.module.css`

**Interfaces:**
- Consumes: `listAgents` (Task 3, to resolve the agent's display name — there is no `GET /agents/{id}` endpoint), `listSessions`, `getSessionMessages`, `deleteSession`, `attachDocumentToSession` (Task 3), `ingestFile` (Task 3), `chatWithAgent` (Task 3), `useAsync` (Task 5), `useConversation` (Task 8), `ChatPanel`, `SessionHistoryPanel`, `FileUploadButton` (Task 8), `EmptyState`, `ErrorBanner`, `Spinner` (Task 5).
- Produces: the `/agents/:agentId` route. `agentId` here is the Powabase `agent_id` (per the route-param identity rule) since that's what `AgentCard` links to and what every nested backend route expects.

- [ ] **Step 1: Write the page stylesheet**

Create `frontend/src/pages/AgentDetailPage.module.css`:
```css
.header {
  margin-bottom: 24px;
}
.section {
  margin-bottom: 32px;
}
.sectionHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.uploads {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
```

- [ ] **Step 2: Write AgentDetailPage**

Replace `frontend/src/pages/AgentDetailPage.tsx`:
```tsx
import { useParams } from 'react-router-dom';
import { listAgents } from '../api/agents';
import { listSessions, getSessionMessages, deleteSession, attachDocumentToSession } from '../api/sessions';
import { ingestFile } from '../api/ingest';
import { chatWithAgent } from '../api/chat';
import { useAsync } from '../hooks/useAsync';
import { useConversation } from '../hooks/useConversation';
import { ChatPanel } from '../components/ChatPanel';
import { SessionHistoryPanel } from '../components/SessionHistoryPanel';
import { FileUploadButton } from '../components/FileUploadButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import styles from './AgentDetailPage.module.css';

export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();

  const agentsList = useAsync(() => listAgents(), []);
  const agent = agentsList.data?.find((a) => a.agent_id === agentId);

  const sessions = useAsync(() => listSessions(agentId!), [agentId]);
  const conversation = useConversation((sessionId) => getSessionMessages(agentId!, sessionId));

  async function handleDeleteSession(sessionId: string) {
    await deleteSession(agentId!, sessionId);
    sessions.reload();
    if (conversation.activeSessionId === sessionId) conversation.clear();
  }

  if (agentsList.loading) return <Spinner />;
  if (agentsList.error) return <ErrorBanner message={agentsList.error} />;
  if (!agent) return <ErrorBanner message="Agent not found." />;

  return (
    <div>
      <div className={styles.header}>
        <h1>{agent.name}</h1>
        <p className="mono">{agent.agent_id}</p>
      </div>

      <section className={styles.section}>
        <h2>Documents</h2>
        <div className={styles.uploads}>
          <FileUploadButton
            id="upload-permanent"
            label="Add document to agent"
            helpText="Permanent — available in every conversation with this agent."
            onUpload={(file) => ingestFile(agentId!, file)}
          />
          <FileUploadButton
            id="upload-attach"
            label="Attach file to this conversation"
            disabled={!conversation.activeSessionId}
            disabledText="Send a message below first — this attaches to the active conversation only."
            onUpload={(file) => attachDocumentToSession(agentId!, conversation.activeSessionId!, file)}
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Past sessions</h2>
          <button type="button" className="btn btn-primary" onClick={conversation.startNewChat}>
            New chat
          </button>
        </div>
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={conversation.continueSession}
          onDelete={(session) => handleDeleteSession(session.session_id)}
        />
      </section>

      {conversation.chatConfig && (
        <section className={styles.section}>
          <h2>Chat</h2>
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithAgent(agentId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
          />
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 4: Manual smoke check against the live backend**

With both servers running and signed in: create an agent, land on its detail page. Expected: name + id header, "No past sessions" empty state, disabled "Attach file to this conversation" button with its explanatory text, working "Add document to agent" upload (use `test.pdf` from the repo root) showing a success message. Click "New chat", send a message, expect a "Thinking…" bubble then an assistant reply, and the session-list section to gain an entry after the first exchange (via the `sessions.reload()` triggered from `onSessionStart`) — also confirm "Attach file to this conversation" becomes enabled at that point. Click "Continue" on a past session and confirm its messages replay via `GET .../messages`. Delete a session and confirm it disappears from the list.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentDetailPage.tsx frontend/src/pages/AgentDetailPage.module.css
git commit -m "feat: build agent detail page with sessions, chat, and document upload"
```

---

### Task 10: Chatbot detail page

**Files:**
- Modify: `frontend/src/pages/ChatbotDetailPage.tsx`
- Create: `frontend/src/pages/ChatbotDetailPage.module.css`

**Interfaces:**
- Consumes: `getChatbot`, `addChatbotAgent`, `deleteChatbotAgent`, `deleteChatbot`, `chatWithChatbot`, `listChatbotSessions`, `getChatbotSessionMessages` (Task 3), `useAsync` (Task 5), `useConversation` (Task 8), `ChatPanel`, `SessionHistoryPanel` (Task 8), `ConfirmButton`, `ErrorBanner`, `Spinner` (Task 5).
- Produces: the `/chatbots/:chatbotId` route, including chatbot-level session history (list + continue, no delete — matches the backend, which has no `DELETE /chatbots/{id}/sessions/{id}` route).

- [ ] **Step 1: Write the page stylesheet**

Create `frontend/src/pages/ChatbotDetailPage.module.css`:
```css
.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}
.section {
  margin-bottom: 32px;
}
.sectionHeader {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.addForm {
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
}
.orchestration {
  display: flex;
  flex-direction: column;
}
.orchestrationRow {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  position: relative;
  padding-bottom: 16px;
}
.orchestrationRow:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 16px;
  bottom: -4px;
  width: 2px;
  background: var(--color-border);
}
.node {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent);
  margin-top: 6px;
  flex-shrink: 0;
}
.agentCard {
  flex: 1;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.agentName {
  margin: 0 0 2px;
  font-weight: 500;
}
```

- [ ] **Step 2: Write ChatbotDetailPage**

Replace `frontend/src/pages/ChatbotDetailPage.tsx`:
```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  getChatbot,
  addChatbotAgent,
  deleteChatbotAgent,
  deleteChatbot,
  chatWithChatbot,
  listChatbotSessions,
  getChatbotSessionMessages,
} from '../api/chatbots';
import { useAsync } from '../hooks/useAsync';
import { useConversation } from '../hooks/useConversation';
import { ChatPanel } from '../components/ChatPanel';
import { SessionHistoryPanel } from '../components/SessionHistoryPanel';
import { ConfirmButton } from '../components/ConfirmButton';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { describeError } from '../lib/errors';
import styles from './ChatbotDetailPage.module.css';

export function ChatbotDetailPage() {
  const { chatbotId } = useParams<{ chatbotId: string }>();
  const navigate = useNavigate();

  const chatbot = useAsync(() => getChatbot(chatbotId!), [chatbotId]);
  const sessions = useAsync(() => listChatbotSessions(chatbotId!), [chatbotId]);
  const conversation = useConversation((sessionId) => getChatbotSessionMessages(chatbotId!, sessionId));

  const [addAgentOpen, setAddAgentOpen] = useState(false);
  const [agentName, setAgentName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [addAgentError, setAddAgentError] = useState<string | null>(null);
  const [addingAgent, setAddingAgent] = useState(false);

  async function handleAddAgent(e: FormEvent) {
    e.preventDefault();
    setAddAgentError(null);
    setAddingAgent(true);
    try {
      await addChatbotAgent(chatbotId!, agentName.trim(), roleDescription.trim(), systemPrompt.trim() || undefined);
      setAgentName('');
      setRoleDescription('');
      setSystemPrompt('');
      setAddAgentOpen(false);
      chatbot.reload();
    } catch (err) {
      setAddAgentError(describeError(err));
    } finally {
      setAddingAgent(false);
    }
  }

  async function handleDeleteAgent(agentId: string) {
    const result = await deleteChatbotAgent(chatbotId!, agentId);
    if (result.chatbot_deleted) {
      navigate('/', { replace: true });
    } else {
      chatbot.reload();
    }
  }

  async function handleDeleteChatbot() {
    await deleteChatbot(chatbotId!);
    navigate('/', { replace: true });
  }

  if (chatbot.loading) return <Spinner />;
  if (chatbot.error) return <ErrorBanner message={chatbot.error} />;
  if (!chatbot.data) return null;

  return (
    <div>
      <div className={styles.header}>
        <div>
          <h1>{chatbot.data.name}</h1>
          <p className="mono">{chatbot.data.orchestrator_id}</p>
        </div>
        <ConfirmButton label="Delete chatbot" confirmLabel="Confirm delete" onConfirm={handleDeleteChatbot} />
      </div>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Agents</h2>
          <button type="button" className="btn" onClick={() => setAddAgentOpen((v) => !v)}>
            {addAgentOpen ? 'Cancel' : 'Add agent'}
          </button>
        </div>

        {addAgentOpen && (
          <form className={styles.addForm} onSubmit={handleAddAgent}>
            {addAgentError && <ErrorBanner message={addAgentError} />}
            <div className="field">
              <label htmlFor="new-agent-name">Name</label>
              <input
                id="new-agent-name"
                className="input"
                required
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-agent-role">Role description</label>
              <textarea
                id="new-agent-role"
                className="input"
                rows={3}
                required
                value={roleDescription}
                onChange={(e) => setRoleDescription(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new-agent-prompt">System prompt (optional)</label>
              <textarea
                id="new-agent-prompt"
                className="input"
                rows={3}
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={addingAgent || !agentName.trim() || !roleDescription.trim()}
            >
              {addingAgent ? 'Adding…' : 'Add agent'}
            </button>
          </form>
        )}

        <div className={styles.orchestration}>
          {chatbot.data.agents.map((agent) => (
            <div key={agent.id} className={styles.orchestrationRow}>
              <span className={styles.node} />
              <div className={`card ${styles.agentCard}`}>
                <div>
                  <p className={styles.agentName}>{agent.name}</p>
                  <p className="mono">{agent.agent_id}</p>
                </div>
                <ConfirmButton
                  label="Remove"
                  confirmLabel="Confirm remove"
                  onConfirm={() => handleDeleteAgent(agent.agent_id)}
                />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Past sessions</h2>
          <button type="button" className="btn btn-primary" onClick={conversation.startNewChat}>
            New chat
          </button>
        </div>
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={conversation.continueSession}
        />
      </section>

      {conversation.chatConfig && (
        <section className={styles.section}>
          <h2>Chat</h2>
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithChatbot(chatbotId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
          />
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 4: Manual smoke check against the live backend**

Create a chatbot from the dashboard, land on its detail page. Expected: name + orchestrator id header, one agent shown in the connector-line list, "No past sessions" empty state (no delete button anywhere in that section — chatbots have no session-delete route), a working "Add agent" form that appends a second connected node to the list, a "Remove" button on each agent (removing the only remaining agent should redirect to `/` since the backend cascades to deleting the whole chatbot), and a "Delete chatbot" button that redirects to `/`. Start a new chat, send a message, confirm a reply appears and the past-sessions list gains an entry; click "Continue" on it and confirm the transcript replays via `GET /chatbots/{id}/sessions/{id}/messages`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ChatbotDetailPage.tsx frontend/src/pages/ChatbotDetailPage.module.css
git commit -m "feat: build chatbot detail page with sub-agent orchestration view, sessions, and chat"
```

---

### Task 11: Polish and run instructions

**Files:**
- Modify: `frontend/src/index.css` (final pass only if gaps found — see Step 1)
- Create: `frontend/README.md`

**Interfaces:**
- Produces: a documented way to run backend + frontend together locally, and a final accessibility/responsiveness pass over what was built in Tasks 4–10.

- [ ] **Step 1: Accessibility and responsiveness pass**

Manually click through every page built in Tasks 4–10 (sign in/up, dashboard, create agent/chatbot, agent detail, chatbot detail) at a narrow viewport (375px wide, e.g. browser dev tools device toolbar) and via keyboard only (Tab through every interactive element). Confirm: no horizontal overflow on any page, every button/link/input reachable by Tab shows the `:focus-visible` amber outline from `index.css` (already global — this step is a check, not new code), and the sidebar + main content don't overlap at narrow widths (the `AppShell` flex layout from Task 5 should already wrap acceptably; if it doesn't, add a `@media (max-width: 640px)` rule to `AppShell.module.css` stacking `.shell` into `flex-direction: column` and setting `.sidebar` to `width: 100%`). Only touch CSS if this manual check surfaces an actual problem — don't pre-emptively add breakpoints that weren't needed.

- [ ] **Step 2: Write run instructions**

Create `frontend/README.md`:
```markdown
# Frontend

React + TypeScript + Vite frontend for the Powabase RAG chatbot backend.

## Run locally

1. Backend (from the repo root):
   ```bash
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Frontend (from `frontend/`):
   ```bash
   npm install
   npm run dev
   ```
3. Open `http://localhost:5173`, sign up, and go.

`VITE_API_BASE_URL` (see `.env.development`) points the frontend at `http://127.0.0.1:8000`. Change it if the backend runs elsewhere.

## Build

```bash
npm run build
```
```

- [ ] **Step 3: Full end-to-end smoke check**

With both servers running, walk the entire flow once start to finish in a browser: sign up → dashboard (empty states) → create an agent → upload a permanent document → start a chat → send a message → attach a document to that conversation → continue the session from the session list → delete the session → create a chatbot → add a second sub-agent → chat with the chatbot → continue its session from chatbot session history → remove an agent → delete the chatbot → sign out → confirm redirect to `/signin`.
Expected: every step succeeds with no console errors, and any deliberately triggered failure (e.g., wrong password on sign in) shows the backend's actual error text via `ErrorBanner`, not a generic message.

- [ ] **Step 4: Commit**

```bash
git add frontend/README.md
git commit -m "docs: add frontend run instructions"
```

---

## Self-Review Notes

- **Spec coverage:** Auth (Task 4) · Dashboard (Task 6) · Create agent (Task 7) · Create chatbot (Task 7) · Chatbot detail incl. add/delete sub-agent/delete chatbot (Task 10) · Chat for both agent and chatbot via one shared `ChatPanel` (Task 8 + wired in Tasks 9–10) · Session history for both standalone agents (with delete) and chatbots (without delete, per the backend's actual routes) via one shared `SessionHistoryPanel` (Task 8 + wired in Tasks 9–10) · Permanent vs. this-conversation-only document upload, clearly labeled (Task 9) · CORS (Task 1, backend) · Chatbot session history backend routes (already applied, documented under Global Constraints).
- **Route-param identity:** double-checked directly against `app/powabase_client.py` (`get_agent_registry_entry` filters by `agent_id`, not `id`) — every standalone-agent link and API call in this plan uses `agent.agent_id`, never the registry row's `id`.
- **Type consistency:** `SessionSummary`/`SessionMessage` are reused identically for both standalone-agent and chatbot session history (the backend returns identical shapes for both), avoiding duplicate near-identical types. `ChatResult` is shared by `chatWithAgent` and `chatWithChatbot`. `ChatPanel`'s `sendMessage` signature is identical across both call sites.
