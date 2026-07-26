# Chat History & Per-Session Document Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent, resumable chat sessions per agent (list sessions, replay a session's transcript, truly continue a conversation) and let a user attach an ad-hoc document to one specific session so the agent can see its full text for that session only — without touching the agent's permanent knowledge base.

**Architecture:** Two new RLS-protected Postgres tables (`chat_sessions`, `session_documents`), following the exact `agents_registry` pattern from the per-user-isolation work: rows keyed to `auth.uid()`, read/written via PostgREST with the calling user's own access token (never the service-role key), so Postgres RLS enforces per-user scoping as defense in depth on top of the route-level ownership checks. Both features route their actual AI-surface calls (`/api/agents/{id}/run/stream`, `/api/sources/*`) through the service-role key exactly like the existing code.

**Critical verified fact driving the design:** Powabase's `session_id` is a bookkeeping/grouping handle only — passing it to `/run/stream` does **not** automatically feed prior turns into the LLM's prompt. This was verified live on 2026-07-26 against the actual project: a second run in the same session, given only a new one-line message, produced `input_messages` (per `GET /api/agents/runs/{run_id}`) containing **only that one message** — no history — and the model explicitly said it couldn't recall anything from "previous interactions." (The public docs claim automatic reconstruction; the live behavior contradicts that, so this plan trusts the live behavior.) Therefore **our backend reconstructs history itself** on every continuation call: fetch the transcript via `GET /api/sessions/{id}/messages` (which *is* reliably persisted and retrievable — confirmed live) and pass it back in as `context_override` alongside the new message. This is also why we do **not** need our own `chat_messages` table — Powabase already stores the full transcript; we just replay it.

The other verified fact: `context_override` (a raw string, "bypasses all retrieval") was tested live against an agent with a linked, working knowledge base — the agent still successfully called its `knowledge_search` tool on the same run that had `context_override` set, and both the override text and the KB fact came back correctly. So folding conversation history and an attached document's text into `context_override` will not disable the agent's normal knowledge-base retrieval.

**Tech Stack:** FastAPI 0.139, Pydantic 2.13, `requests`, Powabase (GoTrue auth + PostgREST + `/api/*` AI surface). No new dependencies — document text extraction reuses Powabase's own Source-extraction pipeline (`upload_source` → poll → `GET /api/sources/{id}/derivatives/text/download`), the same one `/ingest/file` already uses, just without ever calling `add_source_to_kb`.

## Global Constraints

- Keep the `(data, status_code)` tuple return pattern for every function in `app/powabase_client.py`.
- Every request to `/api/*` (Powabase's AI surface: sources, agents, run/stream, sessions) uses the **Service Role key** for both `apikey` and `Authorization` — matches existing code.
- Every request to `/rest/v1/chat_sessions` or `/rest/v1/session_documents` uses `apikey: <Anon key>` + `Authorization: Bearer <the calling user's own access token>` — **never** the service key — so RLS actually filters rows.
- `get_current_user` (already in `app/deps.py`) is a dependency on every route added by this plan.
- No test framework is installed (no `pytest`, no `tests/` dir). Verification uses direct `requests` calls against a locally running `uvicorn` server, or direct Python function calls against the live Powabase project — same style as the per-user-isolation plan.
- Powabase's own session id is a short opaque string like `sess_3781f42786d7` — **it is not a UUID.** Store it as `text` in Postgres, never `uuid`.
- `session_id` continuation does **not** auto-inject history (verified live 2026-07-26) — every continuation call must rebuild and pass the transcript itself via `context_override`.
- `context_override` is safe to combine with an agent's own linked knowledge base — it does not disable the `knowledge_search` tool (verified live 2026-07-26).
- Document attachment (Feature 2) must never call `add_source_to_kb` — the uploaded Source is extracted but deliberately never linked to any Knowledge Base.
- `MAX_DOCUMENT_TOKENS = 6000` (~24,000 characters at a 4-chars-per-token approximation) is the size cap for `attach-document`; reject with `422` and state the limit in the message.

---

### Task 1: `chat_sessions` + `session_documents` tables with RLS (manual Studio step)

This needs DDL access, which this project's `.env` doesn't have credentials for (no Database URL) — same situation as the original `agents_registry` table. Manual step in the Powabase Studio SQL editor.

**Files:** none (pure database change)

**Interfaces:**
- Produces: `public.chat_sessions` (`id uuid`, `user_id uuid`, `agent_id uuid`, `powabase_session_id text unique`, `label text`, `created_at timestamptz`) and `public.session_documents` (`id uuid`, `user_id uuid`, `agent_id uuid`, `session_id text` — FK to `chat_sessions.powabase_session_id`, `source_id uuid`, `filename text`, `extracted_text text`, `token_estimate integer`, `created_at timestamptz`). Both RLS-enabled with the same 4-policy (`select`/`insert`/`update`/`delete` own) pattern as `agents_registry`. Task 2 onward reads/writes both via `/rest/v1/*`.

- [ ] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run:

```sql
create table public.chat_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users,
  agent_id uuid not null,
  powabase_session_id text not null unique,
  label text,
  created_at timestamptz not null default now()
);

alter table public.chat_sessions enable row level security;

create policy "chat_sessions_select_own" on public.chat_sessions
  for select to authenticated using (user_id = auth.uid());

create policy "chat_sessions_insert_own" on public.chat_sessions
  for insert to authenticated with check (user_id = auth.uid());

create policy "chat_sessions_update_own" on public.chat_sessions
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "chat_sessions_delete_own" on public.chat_sessions
  for delete to authenticated using (user_id = auth.uid());

create table public.session_documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users,
  agent_id uuid not null,
  session_id text not null references public.chat_sessions (powabase_session_id) on delete cascade,
  source_id uuid not null,
  filename text not null,
  extracted_text text not null,
  token_estimate integer not null,
  created_at timestamptz not null default now()
);

alter table public.session_documents enable row level security;

create policy "session_documents_select_own" on public.session_documents
  for select to authenticated using (user_id = auth.uid());

create policy "session_documents_insert_own" on public.session_documents
  for insert to authenticated with check (user_id = auth.uid());

create policy "session_documents_update_own" on public.session_documents
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "session_documents_delete_own" on public.session_documents
  for delete to authenticated using (user_id = auth.uid());

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2.

- [ ] **Step 2: Verify both tables exist, RLS blocks cross-role access, and the FK cascade works**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

fake_session = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "powabase_session_id": "sess_rls_test_001",
    "label": "rls-test-session",
}
r = requests.post(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"}, json=fake_session)
print("insert chat_sessions via service key:", r.status_code)
assert r.status_code in (200, 201), r.text

fake_doc = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "session_id": "sess_rls_test_001",
    "source_id": "00000000-0000-0000-0000-000000000002",
    "filename": "rls-test.txt",
    "extracted_text": "hello",
    "token_estimate": 1,
}
r = requests.post(f"{BASE}/rest/v1/session_documents", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"}, json=fake_doc)
print("insert session_documents via service key (FK to chat_sessions):", r.status_code)
assert r.status_code in (200, 201), r.text

r = requests.get(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"powabase_session_id": "eq.sess_rls_test_001"})
print("read chat_sessions via anon key, no user token (RLS should block, expect 0 rows):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

r = requests.delete(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"powabase_session_id": "eq.sess_rls_test_001"})
print("cleanup chat_sessions (should cascade-delete session_documents):", r.status_code)

r = requests.get(f"{BASE}/rest/v1/session_documents", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"session_id": "eq.sess_rls_test_001"})
print("session_documents after cascade delete (expect 0 rows):", r.status_code, r.json())
assert r.json() == []

print("\nTABLES + RLS + CASCADE VERIFIED")
EOF
```

Expected output ends with `TABLES + RLS + CASCADE VERIFIED`. If the first insert 404s, re-run `notify pgrst, 'reload schema';` and retry.

- [ ] **Step 3: Nothing to commit (pure database change)**

Proceed to Task 2.

---

### Task 2: `powabase_client.py` — session-support functions + `run_agent` continuation

**Files:**
- Modify: `app/powabase_client.py` — add `get_session_messages`, `insert_chat_session_row`, `get_chat_session_entry`, `list_chat_sessions`; modify `run_agent`

**Interfaces:**
- Produces:
  - `get_session_messages(session_id: str) -> tuple[dict, int]` — calls Powabase's `GET /api/sessions/{id}/messages` with the **service key** (this is Powabase's own typed API, project-scoped, not a PostgREST table — no user token involved). Success body: `{"messages": [{"role", "content", "run_id", "timestamp"}, ...], "session_id"}`.
  - `insert_chat_session_row(access_token: str, user_id: str, agent_id: str, powabase_session_id: str, label: str | None) -> tuple[dict, int]` — single dict (unwrapped), same pattern as `insert_agent_registry_row`.
  - `get_chat_session_entry(access_token: str, agent_id: str, session_id: str) -> tuple[list, int]` — 0 or 1 rows; non-empty means "exists and is owned by this user for this agent."
  - `list_chat_sessions(access_token: str, agent_id: str) -> tuple[list, int]` — rows shaped `{"id", "session_id", "label", "created_at"}` (PostgREST column alias `session_id:powabase_session_id`).
  - `run_agent(agent_id: str, message: str, session_id: str | None = None, context_override: str | None = None) -> tuple[dict, int]` — backward compatible; existing 2-arg callers keep working.

- [ ] **Step 1: Modify `run_agent` in `app/powabase_client.py`**

Replace the existing `run_agent` function:

```python
def run_agent(agent_id: str, message: str, session_id: str | None = None, context_override: str | None = None) -> dict:
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    if context_override:
        body["context_override"] = context_override

    with requests.post(
        f"{settings.powabase_url}/api/agents/{agent_id}/run/stream",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json=body,
        stream=True,
    ) as response:
        if response.status_code >= 400:
            return response.json(), response.status_code

        run_session_id = None
        for raw in response.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8")
            if line.startswith(":") or not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            kind = event.get("event")
            if kind == "start":
                run_session_id = event.get("session_id")
            elif kind == "complete":
                return {
                    "content": event["content"],
                    "session_id": run_session_id,
                    "usage": event.get("usage"),
                }, 200
            elif kind == "error":
                return {"error": event.get("message"), "code": event.get("code")}, 502

        return {"error": "stream ended without a complete event"}, 502
```

- [ ] **Step 2: Append the new functions to `app/powabase_client.py`**

```python
def get_session_messages(session_id: str) -> dict:
    response = requests.get(
        f"{settings.powabase_url}/api/sessions/{session_id}/messages",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def insert_chat_session_row(access_token: str, user_id: str, agent_id: str, powabase_session_id: str, label: str | None) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"user_id": user_id, "agent_id": agent_id, "powabase_session_id": powabase_session_id, "label": label},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def get_chat_session_entry(access_token: str, agent_id: str, session_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}", "powabase_session_id": f"eq.{session_id}", "select": "id,label,created_at"},
    )
    return response.json(), response.status_code


def list_chat_sessions(access_token: str, agent_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "agent_id": f"eq.{agent_id}",
            "select": "id,session_id:powabase_session_id,label,created_at",
            "order": "created_at.desc",
        },
    )
    return response.json(), response.status_code
```

- [ ] **Step 3: Verify against the live project (no server needed)**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings
from app.powabase_client import (
    create_agent, create_knowledge_base, link_agent_knowledge_base,
    run_agent, get_session_messages, insert_chat_session_row,
    get_chat_session_entry, list_chat_sessions,
)

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key

creds = {"email": "task2-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]
user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token}"}).json()["id"]

agent_data, sc = create_agent("task2-verify-agent", None)
assert sc < 400, agent_data
agent_id = agent_data["id"]

# Turn 1: fresh session
data, sc = run_agent(agent_id, "Remember this word: MELONWATCH77. Just say OK.")
assert sc == 200, data
session_id = data["session_id"]
assert session_id and session_id.startswith("sess_")
print("turn 1 ok, session_id:", session_id)

# Register the session (mimics what the /chat route will do)
row, sc = insert_chat_session_row(token, user_id, agent_id, session_id, "task2 test session")
assert sc < 400, row
print("registered session row:", row)

# Ownership lookup
rows, sc = get_chat_session_entry(token, agent_id, session_id)
assert sc == 200 and len(rows) == 1, (sc, rows)
print("get_chat_session_entry ok")

rows, sc = list_chat_sessions(token, agent_id)
assert sc == 200 and any(r["session_id"] == session_id for r in rows), rows
print("list_chat_sessions ok:", rows)

# Fetch the transcript from Powabase directly
msgs, sc = get_session_messages(session_id)
assert sc == 200 and len(msgs["messages"]) == 2, msgs
print("get_session_messages ok:", msgs["messages"])

# Turn 2: continue the session WITH manually rebuilt context_override (this is what /chat will do)
transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in msgs["messages"])
context_override = f"[Prior conversation in this session]\n{transcript}"
data2, sc = run_agent(agent_id, "What was the word I told you to remember?", session_id=session_id, context_override=context_override)
assert sc == 200, data2
print("turn 2 content:", data2["content"])
assert "MELONWATCH77" in data2["content"], "history replay failed: " + data2["content"]
print("OK: manual history replay via context_override gives the model real memory")

requests.delete(f"{BASE}/api/agents/{agent_id}", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
EOF
```

Expected output ends with `OK: manual history replay via context_override gives the model real memory`.

- [ ] **Step 4: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add session-support functions and session continuation to run_agent"
```

---

### Task 3: `POST /chat` — accept `session_id`, truly continue a conversation

**Files:**
- Modify: `app/routes/chat.py`

**Interfaces:**
- Consumes: `app.deps.AuthedUser`, `get_current_user`; `app.powabase_client.get_agent_registry_entry`, `get_chat_session_entry`, `get_session_messages`, `insert_chat_session_row`, `run_agent` (Task 2).
- Produces: `_build_context_override(session_id: str) -> str | None` in `app/routes/chat.py` (Task 5 extends this signature — noted there). Response body unchanged shape: `{"content", "session_id", "usage"}`.

- [ ] **Step 1: Rewrite `app/routes/chat.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    insert_chat_session_row,
    run_agent,
)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    agent_id: str
    message: str
    session_id: str | None = None
    label: str | None = None


def _build_context_override(session_id: str) -> str | None:
    messages_data, status_code = get_session_messages(session_id)
    if status_code >= 400:
        return None

    transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages_data.get("messages", []))
    if not transcript:
        return None

    return f"[Prior conversation in this session]\n{transcript}"


@router.post("/chat")
def chat_route(req: ChatRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, req.agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    context_override = None
    if req.session_id:
        session_rows, status_code = get_chat_session_entry(user.access_token, req.agent_id, req.session_id)
        if status_code >= 400 or not session_rows:
            raise HTTPException(status_code=403, detail="Session not found or not owned by this user for this agent")
        context_override = _build_context_override(req.session_id)

    data, status_code = run_agent(req.agent_id, req.message, session_id=req.session_id, context_override=context_override)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    if not req.session_id:
        registry_row, status_code = insert_chat_session_row(user.access_token, user.id, req.agent_id, data["session_id"], req.label)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=registry_row)

    return data
```

Note: a brand-new session (`req.session_id` is `None`) has no prior transcript yet, so `context_override` stays `None` for that first call — matches existing behavior exactly.

- [ ] **Step 2: Start the server and verify multi-turn continuation + ownership check**

```bash
cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task3-user-a@example.com")
token_b = get_token("task3-user-b@example.com")

r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "task3-agent"})
assert r.status_code == 200, r.text
agent_id = r.json()["agent_id"]

# Turn 1: new session
r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "Remember this word: GUAVACIRCUIT9. Just say OK.", "label": "my first session"})
assert r.status_code == 200, r.text
session_id = r.json()["session_id"]
print("turn 1:", r.json())

# Turn 2: continue same session, ask for the word back
r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "What was the word?", "session_id": session_id})
assert r.status_code == 200, r.text
print("turn 2:", r.json())
assert "GUAVACIRCUIT9" in r.json()["content"], "expected the model to recall the earlier turn"
print("OK: multi-turn continuation works end-to-end")

# Cross-user: user B tries to continue user A's session on user A's agent -> must be blocked
r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_b}"}, json={"agent_id": agent_id, "message": "hi", "session_id": session_id})
print("cross-user continuation attempt:", r.status_code, r.text[:200])
assert r.status_code == 403
print("OK: cross-user session continuation blocked with 403")
EOF
```

Expected: `OK: multi-turn continuation works end-to-end` and `OK: cross-user session continuation blocked with 403`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chat.py
git commit -m "feat: accept session_id on POST /chat and truly continue conversations"
```

---

### Task 4: `GET /agents/{agent_id}/sessions` and `GET /agents/{agent_id}/sessions/{session_id}/messages`

**Files:**
- Create: `app/routes/sessions.py`
- Modify: `app/main.py` — register the new router

**Interfaces:**
- Consumes: `app.deps.AuthedUser`, `get_current_user`; `app.powabase_client.get_agent_registry_entry`, `get_chat_session_entry`, `get_session_messages`, `list_chat_sessions` (Task 2).
- Produces: `GET /agents/{agent_id}/sessions` → bare JSON array `{id, session_id, label, created_at}`. `GET /agents/{agent_id}/sessions/{session_id}/messages` → Powabase's own `{"messages": [...], "session_id"}` passed through unchanged.

- [ ] **Step 1: Create `app/routes/sessions.py`**

```python
from fastapi import APIRouter, Depends, HTTPException

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    list_chat_sessions,
)

router = APIRouter(prefix="/agents", tags=["sessions"])


@router.get("/{agent_id}/sessions")
def list_sessions_route(agent_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    data, status_code = list_chat_sessions(user.access_token, agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{agent_id}/sessions/{session_id}/messages")
def get_session_messages_route(agent_id: str, session_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    data, status_code = get_session_messages(session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

- [ ] **Step 2: Register the router in `app/main.py`**

```python
from fastapi import FastAPI

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.ingest import router as ingest_router
from app.routes.sessions import router as sessions_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(sessions_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    return app


app = create_app()
```

- [ ] **Step 3: Restart the server and verify listing, message replay, and ownership checks**

```bash
kill %1 2>/dev/null; cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task4-user-a@example.com")
token_b = get_token("task4-user-b@example.com")

r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "task4-agent"})
agent_id = r.json()["agent_id"]

r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "hello there", "label": "task4 session"})
session_id = r.json()["session_id"]

r = requests.get(f"{APP}/agents/{agent_id}/sessions", headers={"Authorization": f"Bearer {token_a}"})
print("list sessions:", r.status_code, r.json())
assert r.status_code == 200
assert any(s["session_id"] == session_id and s["label"] == "task4 session" for s in r.json())
print("OK: session listed with correct label")

r = requests.get(f"{APP}/agents/{agent_id}/sessions/{session_id}/messages", headers={"Authorization": f"Bearer {token_a}"})
print("messages:", r.status_code, r.json())
assert r.status_code == 200 and len(r.json()["messages"]) == 2
print("OK: message transcript replayed from Powabase")

# Non-owner blocked at the agent level
r = requests.get(f"{APP}/agents/{agent_id}/sessions", headers={"Authorization": f"Bearer {token_b}"})
assert r.status_code == 403
print("OK: listing someone else's agent's sessions -> 403")

# Owner, but wrong/foreign session_id under their own agent -> 404
r = requests.get(f"{APP}/agents/{agent_id}/sessions/sess_does_not_exist/messages", headers={"Authorization": f"Bearer {token_a}"})
assert r.status_code == 404
print("OK: unknown session_id under owned agent -> 404")
EOF
```

Expected: all three `OK:` lines print.

- [ ] **Step 4: Commit**

```bash
git add app/routes/sessions.py app/main.py
git commit -m "feat: add GET /agents/{id}/sessions and .../messages"
```

---

### Task 5: `POST /agents/{agent_id}/sessions/{session_id}/attach-document`

**Files:**
- Modify: `app/powabase_client.py` — add `get_source_text_derivative`, `insert_session_document_row`, `list_session_documents_text`
- Modify: `app/routes/sessions.py` — add the attach-document route
- Modify: `app/routes/chat.py` — extend `_build_context_override` to fold in attached documents

**Interfaces:**
- Produces: `get_source_text_derivative(source_id: str) -> tuple[str | dict, int]` — on success (200), a plain-text `str`; on error, Powabase's JSON error dict (still a valid `(data, status_code)` pair — same convention, the success type just varies, matching how other functions in this module already return `list` vs `dict` depending on the call).
- Produces: `insert_session_document_row(access_token, user_id, agent_id, session_id, source_id, filename, extracted_text, token_estimate) -> tuple[dict, int]`.
- Produces: `list_session_documents_text(access_token, agent_id, session_id) -> tuple[list, int]` — rows shaped `{"filename", "extracted_text"}`.
- Consumes: `app.powabase_client.upload_source`, `get_source` (existing, from Task 5/ingest of the isolation plan).

- [ ] **Step 1: Append the new functions to `app/powabase_client.py`**

```python
def get_source_text_derivative(source_id: str):
    response = requests.get(
        f"{settings.powabase_url}/api/sources/{source_id}/derivatives/text/download",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    if response.status_code >= 400:
        return response.json(), response.status_code
    return response.text, response.status_code


def insert_session_document_row(
    access_token: str,
    user_id: str,
    agent_id: str,
    session_id: str,
    source_id: str,
    filename: str,
    extracted_text: str,
    token_estimate: int,
) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/session_documents",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "source_id": source_id,
            "filename": filename,
            "extracted_text": extracted_text,
            "token_estimate": token_estimate,
        },
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def list_session_documents_text(access_token: str, agent_id: str, session_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/session_documents",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "agent_id": f"eq.{agent_id}",
            "session_id": f"eq.{session_id}",
            "select": "filename,extracted_text",
            "order": "created_at.asc",
        },
    )
    return response.json(), response.status_code
```

- [ ] **Step 2: Add the attach-document route to `app/routes/sessions.py`**

Add these imports at the top (replacing the existing import lines):

```python
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    get_source,
    get_source_text_derivative,
    insert_session_document_row,
    list_chat_sessions,
    upload_source,
)

router = APIRouter(prefix="/agents", tags=["sessions"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120
MAX_DOCUMENT_TOKENS = 6000
```

Append this route at the end of the file:

```python
@router.post("/{agent_id}/sessions/{session_id}/attach-document")
def attach_document_route(
    agent_id: str,
    session_id: str,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(get_current_user),
):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    file_bytes = file.file.read()

    data, status_code = upload_source(file_bytes, file.filename)
    if status_code == 409:
        source_id = data["duplicate"]["id"]
    elif status_code < 400:
        source_id = data["id"]
    else:
        raise HTTPException(status_code=status_code, detail=data)

    elapsed = 0
    extraction_status = None
    while extraction_status not in TERMINAL_EXTRACTION_STATUSES:
        if elapsed >= POLL_TIMEOUT_SECONDS:
            raise HTTPException(status_code=504, detail="Timed out waiting for source extraction")

        data, status_code = get_source(source_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=data)

        extraction_status = data["extraction_status"]
        if extraction_status in TERMINAL_EXTRACTION_STATUSES:
            break

        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    if extraction_status != "extracted":
        raise HTTPException(
            status_code=422,
            detail=f"Document extraction ended in status '{extraction_status}', cannot attach to session",
        )

    text, status_code = get_source_text_derivative(source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=text)

    token_estimate = len(text) // 4
    if token_estimate > MAX_DOCUMENT_TOKENS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Document is too large to attach to a session: ~{token_estimate} estimated tokens "
                f"(limit is {MAX_DOCUMENT_TOKENS} tokens, ~{MAX_DOCUMENT_TOKENS * 4} characters). "
                "Use POST /ingest/file to add it to the agent's knowledge base instead."
            ),
        )

    row, status_code = insert_session_document_row(
        user.access_token, user.id, agent_id, session_id, source_id, file.filename, text, token_estimate
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=row)

    row.pop("extracted_text", None)
    return row
```

- [ ] **Step 3: Extend `_build_context_override` in `app/routes/chat.py` to include attached documents**

Replace the imports and the `_build_context_override` function:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    insert_chat_session_row,
    list_session_documents_text,
    run_agent,
)

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    agent_id: str
    message: str
    session_id: str | None = None
    label: str | None = None


def _build_context_override(access_token: str, agent_id: str, session_id: str) -> str | None:
    parts = []

    doc_rows, status_code = list_session_documents_text(access_token, agent_id, session_id)
    if status_code < 400 and doc_rows:
        docs_text = "\n\n".join(f'--- {row["filename"]} ---\n{row["extracted_text"]}' for row in doc_rows)
        parts.append(f"[Documents attached to this session]\n{docs_text}")

    messages_data, status_code = get_session_messages(session_id)
    if status_code < 400:
        transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages_data.get("messages", []))
        if transcript:
            parts.append(f"[Prior conversation in this session]\n{transcript}")

    return "\n\n".join(parts) if parts else None
```

And update the one call site inside `chat_route`:

```python
        context_override = _build_context_override(user.access_token, req.agent_id, req.session_id)
```

(The rest of `chat_route` is unchanged from Task 3.)

- [ ] **Step 4: Restart the server and verify the full attach-document flow**

```bash
kill %1 2>/dev/null; cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task5-user-a@example.com")
token_b = get_token("task5-user-b@example.com")

r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "task5-agent"})
agent_id = r.json()["agent_id"]

r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "hi"})
session_id = r.json()["session_id"]

# Attach a small document with a fact that's ONLY in the document, not the KB or prior chat
doc_bytes = b"CONFIDENTIAL SESSION MEMO: the launch codename is OCTOPUS-VELVET."
r = requests.post(
    f"{APP}/agents/{agent_id}/sessions/{session_id}/attach-document",
    headers={"Authorization": f"Bearer {token_a}"},
    files={"file": ("memo.txt", doc_bytes)},
)
print("attach-document:", r.status_code, r.json())
assert r.status_code == 200
assert "extracted_text" not in r.json()

# Ask about the fact in the SAME session -> should know it
r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "What is the launch codename mentioned in the attached memo?", "session_id": session_id})
print("chat in same session:", r.json())
assert "OCTOPUS-VELVET" in r.json()["content"]
print("OK: attached document visible within its session")

# Start a DIFFERENT session on the SAME agent -> must NOT know the fact
r = requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_id, "message": "What is the launch codename?"})
print("chat in a different session:", r.json())
assert "OCTOPUS-VELVET" not in r.json()["content"]
print("OK: attached document is NOT visible in a different session")

# Oversized document -> 422 with the limit stated
big_bytes = ("word " * 30000).encode()  # ~150,000 chars, well over the 24,000-char cap
r = requests.post(
    f"{APP}/agents/{agent_id}/sessions/{session_id}/attach-document",
    headers={"Authorization": f"Bearer {token_a}"},
    files={"file": ("huge.txt", big_bytes)},
)
print("oversized attach:", r.status_code, r.text[:300])
assert r.status_code == 422 and "6000" in r.text
print("OK: oversized document rejected with 422 and the limit in the message")

# Cross-user ownership check
r = requests.post(
    f"{APP}/agents/{agent_id}/sessions/{session_id}/attach-document",
    headers={"Authorization": f"Bearer {token_b}"},
    files={"file": ("hack.txt", b"malicious")},
)
assert r.status_code == 403
print("OK: cross-user attach-document blocked with 403")
EOF
```

Expected: all four `OK:` lines print.

- [ ] **Step 5: Commit**

```bash
git add app/powabase_client.py app/routes/sessions.py app/routes/chat.py
git commit -m "feat: add per-session document attachment via context_override, never added to the KB"
```

---

### Task 6: End-to-end sanity script for both features

**Files:**
- Create: `scripts/sanity_check_sessions.py`

**Interfaces:**
- Consumes: the full running app (`/auth/signup`, `/agents`, `/chat`, `/agents/{id}/sessions`, `/agents/{id}/sessions/{id}/messages`, `/agents/{id}/sessions/{id}/attach-document`) over HTTP against `http://127.0.0.1:8000`.

- [ ] **Step 1: Create `scripts/sanity_check_sessions.py`**

```python
import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-sessions-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-sessions-user-b@example.com", "password": "SanityTest123!"}


def signup_or_signin(creds):
    r = requests.post(
        f"{BASE}/auth/v1/signup",
        headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"},
        json=creds,
    )
    if r.status_code >= 400:
        r = requests.post(
            f"{BASE}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"},
            json=creds,
        )
    r.raise_for_status()
    return r.json()["access_token"]


def create_agent(token, name):
    r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": name})
    r.raise_for_status()
    return r.json()


def chat(token, agent_id, message, session_id=None, label=None):
    body = {"agent_id": agent_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    if label:
        body["label"] = label
    return requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity Sessions Agent A")
    agent_b = create_agent(token_b, "Sanity Sessions Agent B")
    print("agent A:", agent_a["agent_id"])
    print("agent B:", agent_b["agent_id"])

    # --- Feature 1: multi-turn history ---
    r = chat(token_a, agent_a["agent_id"], "Remember this: my favorite number is 8842. Just say OK.", label="numbers chat")
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    print("turn 1 ok, session:", session_id)

    r = chat(token_a, agent_a["agent_id"], "What's my favorite number?", session_id=session_id)
    assert r.status_code == 200 and "8842" in r.json()["content"], r.text
    print("turn 2 ok: history recalled ->", r.json()["content"])

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and any(s["session_id"] == session_id and s["label"] == "numbers chat" for s in r.json())
    print("session listed with label ok")

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/messages", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and len(r.json()["messages"]) == 4
    print("message transcript ok:", len(r.json()["messages"]), "messages")

    # --- Feature 2: per-session document, not in the KB ---
    doc = b"SESSION-ONLY FACT: the vault combination is 19-84-23."
    r = requests.post(
        f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("vault.txt", doc)},
    )
    assert r.status_code == 200, r.text
    print("document attached ok")

    r = chat(token_a, agent_a["agent_id"], "What is the vault combination?", session_id=session_id)
    assert r.status_code == 200 and "19-84-23" in r.json()["content"], r.text
    print("document visible in its own session ok")

    r = chat(token_a, agent_a["agent_id"], "What is the vault combination?")  # fresh session, no attachment
    assert r.status_code == 200 and "19-84-23" not in r.json()["content"], r.text
    print("document correctly absent from a different session ok")

    # --- Cross-user isolation still holds for the new endpoints ---
    r = chat(token_b, agent_a["agent_id"], "hi", session_id=session_id)
    assert r.status_code == 403
    print("cross-user session continuation blocked ok")

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user session listing blocked ok")

    r = requests.post(
        f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token_b}"},
        files={"file": ("hack.txt", b"nope")},
    )
    assert r.status_code == 403
    print("cross-user attach-document blocked ok")

    print("\nALL SESSION + DOCUMENT SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Restart the server and run the sanity check**

```bash
kill %1 2>/dev/null; cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 2
.venv/bin/python3 scripts/sanity_check_sessions.py
```

Expected: the script prints each step and ends with `ALL SESSION + DOCUMENT SANITY CHECKS PASSED`.

- [ ] **Step 3: Stop the background server**

```bash
kill %1 2>/dev/null
```

- [ ] **Step 4: Commit**

```bash
git add scripts/sanity_check_sessions.py
git commit -m "test: add end-to-end sanity check for chat history and document attachment"
```

---

## Self-review notes

- **Spec coverage:**
  - Feature 1, requirement 1 (optional `session_id`, continue-or-create) → Task 3.
  - Feature 1, requirement 2 (new RLS table for sessions) → Task 1 (`chat_sessions`).
  - Feature 1, requirement 3 (`GET /agents/{id}/sessions`, 403 on non-owned agent) → Task 4.
  - Feature 1, requirement 4 (message transcript endpoint, preferring Powabase's own stored history over a local `chat_messages` table) → Task 4, using `get_session_messages` from Task 2. No `chat_messages` table was created — confirmed unnecessary since `GET /api/sessions/{id}/messages` is reliable (verified live).
  - Feature 2 (attach-document endpoint, ownership-checked, size/token safeguard, injected via `context_override` not `knowledge_search`, never touches `upload_source`'s KB path) → Task 5. Confirmed via Task 5's verification that the fact is visible in its own session and absent from a sibling session on the same agent.
- **Placeholder scan:** none — every step has complete code and concrete expected output strings.
- **Type/name consistency:** `AuthedUser.id`/`access_token` used identically to the existing isolation code. `get_chat_session_entry`/`list_chat_sessions`/`get_session_messages`/`list_session_documents_text` signatures introduced in Task 2/5 are used identically in Tasks 3, 4, 5. `_build_context_override`'s signature changes from `(session_id)` in Task 3 to `(access_token, agent_id, session_id)` in Task 5 — this is a deliberate, called-out extension of the same function in the same file, not a naming drift.
- **Ordering fix applied:** `_build_context_override` initially only reconstructs conversation history (Task 3, which only depends on Task 2's functions); Task 5 extends it to also fold in attached documents, avoiding a forward reference to the `session_documents` table/functions that don't exist until Task 5.
