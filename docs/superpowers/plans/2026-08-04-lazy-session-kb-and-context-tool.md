# Lazy Per-Session Knowledge Bases + Session-Context Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the "naive" per-session document feature (full extracted text stored in `session_documents`, unconditionally injected into every message's `context_override`) with a lazy per-session Knowledge Base that a new custom `session_context_search` tool searches on demand, so documents only enter the model's context when the model actually decides they're relevant.

**Architecture:** `chat_sessions` gains a nullable `kb_id` (created lazily on first document attach, reused for later attaches in the same session) and a `session_token` (a 256-bit random value, generated when the session row is first created). Every `/chat` call injects the session's `session_token` into `context_override` with an instruction to pass it verbatim to `session_context_search`. That tool is a new inbound FastAPI route (`POST /tools/session-context`, publicly reachable via an ngrok tunnel) registered as a Powabase custom tool on every agent. **Verified live against the real Powabase project:** custom tool endpoints receive *only* the LLM's own tool-call arguments — no `session_id`/`run_id` is auto-injected by the platform, and `config_override` (which force-injects args for builtin tools) is a no-op for custom tools. So the tool resolves "which session" the same way any bearer-token API does: it looks up `chat_sessions` by `session_token` (service key, bypassing RLS — there is no end-user identity on this inbound call) and, if found, calls `POST /api/context-handlers` against that session's `kb_id`. An unknown/missing token returns a graceful "nothing to search" text response, never an error.

**Tech Stack:** FastAPI 0.139, Pydantic 2.13, `requests`, ngrok (tunnel for the inbound tool endpoint), Powabase (`/api/tools`, `/api/context-handlers`, `/api/knowledge-bases`, PostgREST `chat_sessions`).

## Global Constraints

- Keep the `(data, status_code)` tuple return pattern for every function in `app/powabase_client.py`, exactly like existing functions.
- `/api/*` calls use the **Service Role key** for both `apikey` and `Authorization` (existing pattern). `/rest/v1/chat_sessions` calls use `apikey: <Anon key>` + `Authorization: Bearer <caller's own access token>` **except** the new `get_chat_session_by_token` lookup, which the *tool endpoint* uses — that call has no end-user token available (Powabase's tool-caller doesn't forward one) and must use the **Service Role key**, bypassing RLS by design. This is the one deliberate exception; call it out with a comment.
- **`session_token` must never appear in any HTTP response body returned to an end user.** It's the sole access-control credential for the tool endpoint; treat it like a secret. `list_chat_sessions`'s `select=` must not include it (it already doesn't — leave as-is).
- No test framework is installed (no `pytest`, no `tests/` dir) — verification uses direct `requests` calls against a locally running `uvicorn`, matching the existing `scripts/sanity_check*.py` style.
- **Do not drop the `session_documents` table or delete its RLS policies as part of this plan.** Its Python functions (`insert_session_document_row`, `list_session_documents_text`, `get_source_text_derivative`) become dead code once Tasks 6 and 9 land and should be deleted from `powabase_client.py` — but the table itself stays until you've verified the new feature end-to-end and separately confirm the drop.
- Live API shapes referenced below (`POST /api/tools`, `POST /api/agents/{id}/tools`, `PUT /api/tools/{id}`, `POST /api/context-handlers`, `DELETE /api/knowledge-bases/{id}`, PostgREST DELETE response, `GET /api/sessions/{id}/runs`, `GET /api/knowledge-bases/{id}/sources`) were verified against the live project on 2026-08-04 — see inline notes in each task.

---

### Task 1: `chat_sessions.kb_id` + `chat_sessions.session_token` columns (manual SQL, Studio step)

This needs DDL access, which this project's `.env` doesn't have (no Database URL) — same situation as every prior table/column change in this project. Manual step in the Powabase Studio SQL editor.

**Files:** none (pure database change)

**Interfaces:**
- Produces: `public.chat_sessions.kb_id` (`uuid`, nullable — null means "no document ever attached to this session") and `public.chat_sessions.session_token` (`text`, nullable, unique — set once when the row is inserted). No RLS policy changes needed; the existing 4 owner-scoped policies on `chat_sessions` already cover these new columns for normal user-token access. The tool endpoint reads `session_token` via the **service key**, which bypasses RLS entirely — that's intentional (see Global Constraints).

- [ ] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run:

```sql
alter table public.chat_sessions add column kb_id uuid;
alter table public.chat_sessions add column session_token text;
create unique index chat_sessions_session_token_key on public.chat_sessions (session_token);

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2.

- [ ] **Step 2: Verify the columns exist and are writable via the service key, and RLS still blocks anon reads**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

r = requests.get(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"select": "id,powabase_session_id", "limit": 1})
print("existing rows sample:", r.status_code, r.json())

r = requests.get(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"select": "id,kb_id,session_token", "limit": 1})
print("anon read (RLS should block -> expect empty list, 200):", r.status_code, r.json())
assert r.json() == [], "RLS should hide all rows from an unauthenticated anon read"
print("kb_id / session_token columns verified")
EOF
```

Expected: the anon read returns `200` with an empty list (RLS blocks it, same as every other column on this table); the columns are visible in the `select=` without a PostgREST error (proves they exist).

- [ ] **Step 3: Commit**

No files changed in this task — nothing to commit. Proceed to Task 2.

---

### Task 2: Public tunnel for the inbound tool endpoint + `public_base_url` setting

Powabase's custom-tool caller makes an **inbound** HTTP request to our tool endpoint — the opposite direction of every other call in this codebase. `127.0.0.1:8000` isn't reachable from Powabase's servers, so this needs a public URL. This is a one-time manual setup (installing ngrok, creating a free account, an authtoken) that can't be done via this project's API — same category as the BYOK-key/Studio steps flagged elsewhere in this codebase's history.

**Files:**
- Modify: `app/config.py`
- Modify: `.env` (add `PUBLIC_BASE_URL`, filled in by the user after Step 1)

**Interfaces:**
- Produces: `settings.public_base_url: str` (empty string until configured) — consumed by Task 3's `ensure_session_context_tool()`.

- [ ] **Step 1: Ask the user to install and start ngrok**

Tell the user: "The session-context tool needs a public URL Powabase can call into. Please:
1. Install ngrok (https://ngrok.com/download) if not already installed.
2. Sign up for a free account and run `ngrok config add-authtoken <your-token>` (token is on your ngrok dashboard).
3. Once this app's `uvicorn` server is running on port 8000 (Task 11 starts it), run `ngrok http 8000` in a separate terminal and leave it running.
4. Paste the `https://....ngrok-free.app` forwarding URL it prints."

Wait for the user to provide the URL before continuing.

- [ ] **Step 2: Add `public_base_url` to settings**

Read `app/config.py`, then:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    powabase_url: str
    powabase_anon_key: str
    powabase_service_key: str
    public_base_url: str = ""


settings = Settings()
```

(Only the added `public_base_url: str = ""` line changes — default empty string so routes that don't need it aren't blocked by a missing env var.)

- [ ] **Step 3: Add the URL to `.env`**

Append a line to `/home/william/powabase-chatbot/.env` (using the URL the user provided in Step 1):

```
PUBLIC_BASE_URL=https://<the-ngrok-subdomain>.ngrok-free.app
```

- [ ] **Step 4: Verify the setting loads**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 -c "from app.config import settings; print(repr(settings.public_base_url))"
```

Expected: prints the ngrok URL, not an empty string.

- [ ] **Step 5: Commit**

```bash
git add app/config.py
git commit -m "feat: add public_base_url setting for the inbound tool endpoint"
```

(`.env` is gitignored per this repo's `.gitignore` — don't force-add it.)

---

### Task 3: `powabase_client.py` — tool registration + context-handler search functions

**Files:**
- Modify: `app/powabase_client.py`

**Interfaces:**
- Consumes: `settings.public_base_url` (Task 2).
- Produces: `SESSION_CONTEXT_TOOL_NAME: str` constant; `ensure_session_context_tool() -> str` (returns the Powabase tool id, creating or endpoint-updating it as needed); `assign_tool_to_agent(agent_id: str, tool_id: str, tool_name: str) -> tuple[dict, int]`; `query_context_handler(kb_id: str, query: str, top_k: int = 5) -> tuple[dict, int]`; `get_chat_session_by_token(session_token: str) -> tuple[list, int]`. Used by Task 5 (tool endpoint route), Task 7 (agent creation), Task 8 (backfill script).

- [ ] **Step 1: Add the functions**

Read `app/powabase_client.py`, then append these functions after `link_agent_knowledge_base` (keep everything else in the file unchanged):

```python
SESSION_CONTEXT_TOOL_NAME = "session_context_search"


def list_tools() -> tuple[dict, int]:
    response = requests.get(
        f"{settings.powabase_url}/api/tools",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def create_tool(name: str, description: str, input_schema: dict, config: dict) -> tuple[dict, int]:
    response = requests.post(
        f"{settings.powabase_url}/api/tools",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"name": name, "description": description, "type": "http", "input_schema": input_schema, "config": config},
    )
    return response.json(), response.status_code


def update_tool(tool_id: str, name: str, description: str, input_schema: dict, config: dict) -> tuple[dict, int]:
    response = requests.put(
        f"{settings.powabase_url}/api/tools/{tool_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"name": name, "description": description, "type": "http", "input_schema": input_schema, "config": config},
    )
    return response.json(), response.status_code


def assign_tool_to_agent(agent_id: str, tool_id: str, tool_name: str) -> tuple[dict, int]:
    response = requests.post(
        f"{settings.powabase_url}/api/agents/{agent_id}/tools",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"tool_type": "custom", "tool_name": tool_name, "tool_id": tool_id},
    )
    return response.json(), response.status_code


def ensure_session_context_tool() -> str:
    """Create the session_context_search Tool if it doesn't exist yet; if it
    exists but points at a stale endpoint (e.g. the ngrok URL changed), update
    it in place. Returns the tool's id either way."""
    if not settings.public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is not set — see Task 2 of the lazy-session-kb plan")

    endpoint = f"{settings.public_base_url}/tools/session-context"
    description = (
        "Search the document(s) attached to the CURRENT chat session (this is NOT the agent's "
        "permanent knowledge base). Call this whenever the user's question could plausibly be "
        "answered by a document they attached earlier in this same conversation. Do not call it "
        "for questions unrelated to any attached document. Always pass session_token with the "
        "EXACT value given to you in this conversation's context -- never invent, guess, or omit it."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in the session's attached document(s).",
            },
            "session_token": {
                "type": "string",
                "description": (
                    "The exact session_token value provided to you in this conversation's context. "
                    "Never invent or guess this value."
                ),
            },
        },
        "required": ["query", "session_token"],
    }
    config = {"endpoint": endpoint, "method": "POST"}

    tools, status_code = list_tools()
    if status_code >= 400:
        raise RuntimeError(f"Failed to list tools: {tools}")

    existing = next((t for t in tools.get("tools", []) if t.get("name") == SESSION_CONTEXT_TOOL_NAME), None)
    if existing is None:
        created, status_code = create_tool(SESSION_CONTEXT_TOOL_NAME, description, input_schema, config)
        if status_code >= 400:
            raise RuntimeError(f"Failed to create session context tool: {created}")
        return created["id"]

    if existing.get("config", {}).get("endpoint") != endpoint:
        updated, status_code = update_tool(existing["id"], SESSION_CONTEXT_TOOL_NAME, description, input_schema, config)
        if status_code >= 400:
            raise RuntimeError(f"Failed to update session context tool: {updated}")
    return existing["id"]


def query_context_handler(kb_id: str, query: str, top_k: int = 5) -> tuple[dict, int]:
    response = requests.post(
        f"{settings.powabase_url}/api/context-handlers",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"query": query, "knowledge_bases": [{"id": kb_id, "top_k": top_k}]},
    )
    return response.json(), response.status_code


def get_chat_session_by_token(session_token: str) -> tuple[list, int]:
    # Service key, deliberately: the inbound call from Powabase's tool-caller
    # carries no end-user identity, so there is no user access_token to scope
    # this query with. The session_token itself (a 256-bit random value,
    # never exposed in any user-facing response) is the access-control check.
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"session_token": f"eq.{session_token}", "select": "kb_id"},
    )
    return response.json(), response.status_code
```

- [ ] **Step 2: Verify `ensure_session_context_tool` creates the tool live**

Requires Task 2's `PUBLIC_BASE_URL` to be set (ngrok running).

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 -c "
from app.powabase_client import ensure_session_context_tool, list_tools
tool_id = ensure_session_context_tool()
print('tool_id:', tool_id)
tools, sc = list_tools()
names = [t['name'] for t in tools['tools']]
assert 'session_context_search' in names
print('confirmed present in /api/tools listing')
tool_id_2 = ensure_session_context_tool()
assert tool_id == tool_id_2, f'expected idempotent id, got {tool_id} vs {tool_id_2}'
print('idempotent ok')
"
```

Expected: prints a UUID, confirms it's listed, and the second call returns the identical id (no duplicate tool created).

- [ ] **Step 3: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add session-context tool registration and context-handler search helpers"
```

---

### Task 4: `powabase_client.py` — session KB lifecycle functions

**Files:**
- Modify: `app/powabase_client.py`

**Interfaces:**
- Produces: `update_chat_session_kb_id(access_token, agent_id, session_id, kb_id) -> tuple[dict, int]`; `delete_knowledge_base(kb_id: str) -> tuple[dict, int]`; `delete_chat_session_row(access_token, agent_id, session_id) -> tuple[dict, int]`. Also modifies `insert_chat_session_row` to accept and store `session_token`, and `get_chat_session_entry` to select `kb_id, session_token` in addition to its existing columns. Used by Task 6 (chat route), Task 9 (attach-document route + delete-session route).

- [ ] **Step 1: Extend `get_chat_session_entry`'s `select`**

In `app/powabase_client.py`, find `get_chat_session_entry` and change its `select` param:

```python
def get_chat_session_entry(access_token: str, agent_id: str, session_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}", "powabase_session_id": f"eq.{session_id}", "select": "id,label,created_at,kb_id,session_token"},
    )
    return response.json(), response.status_code
```

(Only the `select` value changes: `"id,label,created_at"` → `"id,label,created_at,kb_id,session_token"`.)

- [ ] **Step 2: Add `session_token` to `insert_chat_session_row`**

Change its signature and body:

```python
def insert_chat_session_row(access_token: str, user_id: str, agent_id: str, powabase_session_id: str, label: str | None, session_token: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"user_id": user_id, "agent_id": agent_id, "powabase_session_id": powabase_session_id, "label": label, "session_token": session_token},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code
```

- [ ] **Step 3: Add `update_chat_session_kb_id`, `delete_knowledge_base`, `delete_chat_session_row`**

Append after `insert_chat_session_row`:

```python
def update_chat_session_kb_id(access_token: str, agent_id: str, session_id: str, kb_id: str) -> tuple[dict, int]:
    response = requests.patch(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"agent_id": f"eq.{agent_id}", "powabase_session_id": f"eq.{session_id}"},
        json={"kb_id": kb_id},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def delete_knowledge_base(kb_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/api/knowledge-bases/{kb_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def delete_chat_session_row(access_token: str, agent_id: str, session_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}", "powabase_session_id": f"eq.{session_id}"},
    )
    # PostgREST DELETE with no Prefer header returns 204 with an empty body on
    # success (verified live) -- only parse JSON on the error path.
    if response.status_code >= 400:
        return response.json(), response.status_code
    return {}, response.status_code
```

- [ ] **Step 4: Verify with a throwaway row (service key, bypasses RLS, matches Task 1 Step 2's verification style)**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings
from app.powabase_client import delete_chat_session_row, get_chat_session_by_token

BASE = settings.powabase_url
SVC = settings.powabase_service_key

r = requests.get(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"select": "user_id", "limit": 1})
sample = r.json()
assert sample, "run scripts/sanity_check.py or sanity_check_sessions.py at least once first so a real user_id exists"
real_user_id = sample[0]["user_id"]

fake = {
    "user_id": real_user_id,
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "powabase_session_id": "sess_kb_migration_probe",
    "session_token": "probe-token-abc123",
}
r = requests.post(f"{BASE}/rest/v1/chat_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"}, json=fake)
assert r.status_code in (200, 201), r.text
print("insert ok")

rows, sc = get_chat_session_by_token("probe-token-abc123")
assert sc == 200 and len(rows) == 1 and rows[0]["kb_id"] is None, (sc, rows)
print("get_chat_session_by_token ok:", rows)

_, sc = delete_chat_session_row(SVC, "00000000-0000-0000-0000-000000000001", "sess_kb_migration_probe")
assert sc == 204, sc
print("delete_chat_session_row ok, status", sc)

rows, sc = get_chat_session_by_token("probe-token-abc123")
assert rows == [], rows
print("confirmed deleted")
EOF
```

Expected: all asserts pass, ending in "confirmed deleted".

- [ ] **Step 5: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add session kb_id/session_token lifecycle functions"
```

---

### Task 5: The session-context tool endpoint (`app/routes/tools.py`)

**Files:**
- Create: `app/routes/tools.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `get_chat_session_by_token`, `query_context_handler` (Task 3).
- Produces: `POST /tools/session-context` — the endpoint Powabase's custom tool caller hits. Always returns `200` with a plain-text body (verified live: Powabase passes a custom tool's raw HTTP response body through to the LLM verbatim as the tool's observation — it does not require or unwrap a JSON envelope).

- [ ] **Step 1: Create the route**

```python
from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from app.powabase_client import get_chat_session_by_token, query_context_handler

router = APIRouter(prefix="/tools", tags=["tools"])


class SessionContextToolBody(BaseModel):
    query: str
    session_token: str | None = None


@router.post("/session-context")
def session_context_tool_route(body: SessionContextToolBody):
    session_token = (body.session_token or "").strip()
    if not session_token:
        return PlainTextResponse("No session context available: missing session token.")

    rows, status_code = get_chat_session_by_token(session_token)
    if status_code >= 400 or not rows:
        return PlainTextResponse("No session context available: invalid session token.")

    kb_id = rows[0].get("kb_id")
    if not kb_id:
        return PlainTextResponse("No document has been attached to this session yet. There is nothing to search.")

    data, status_code = query_context_handler(kb_id, body.query)
    if status_code >= 400:
        return PlainTextResponse("Unable to search the session's document right now.")

    formatted = data.get("formatted_context") or "No relevant content found for that query."
    return PlainTextResponse(formatted)
```

- [ ] **Step 2: Wire the router into `main.py`**

Read `app/main.py`, then:

```python
from fastapi import FastAPI

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.ingest import router as ingest_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(sessions_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    app.include_router(tools_router)
    return app


app = create_app()
```

- [ ] **Step 3: Start the server and verify the endpoint directly**

```bash
cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --reload &
sleep 2
curl -s -X POST http://127.0.0.1:8000/tools/session-context -H "Content-Type: application/json" -d '{"query": "test", "session_token": "not-a-real-token"}'
echo
curl -s -X POST http://127.0.0.1:8000/tools/session-context -H "Content-Type: application/json" -d '{"query": "test"}'
```

Expected: both return `200` with a plain-text body — the first: `No session context available: invalid session token.`, the second (missing `session_token` entirely): `No session context available: missing session token.` Neither is a 4xx/5xx or a stack trace — confirms the "never error out" requirement.

Leave `uvicorn` running (with `--reload`) for the rest of this plan — Task 2's ngrok tunnel points at it, and Task 11's end-to-end script needs it live.

- [ ] **Step 4: Commit**

```bash
git add app/routes/tools.py app/main.py
git commit -m "feat: add inbound session-context tool endpoint"
```

---

### Task 6: `chat.py` — stop flooding documents, inject the session token instead

**Files:**
- Modify: `app/routes/chat.py`

**Interfaces:**
- Consumes: `insert_chat_session_row` (now takes `session_token`, Task 4).
- Produces: `_build_context_override` signature changes from `(access_token, agent_id, session_id)` to `(session_id, session_token)` — it no longer needs `access_token`/`agent_id` since it no longer queries `session_documents`. Conversation-history reconstruction (`get_session_messages`) is untouched.

- [ ] **Step 1: Rewrite `_build_context_override` and `chat_route`**

Read `app/routes/chat.py`, then replace the whole file:

```python
import secrets

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


def _build_context_override(session_id: str, session_token: str | None) -> str | None:
    parts = []

    if session_token:
        parts.append(
            "[Session tool context]\n"
            f"Your session_token for the session_context_search tool in this conversation is: {session_token}\n"
            "Always pass this exact value as the session_token argument when calling session_context_search. "
            "Never invent, guess, or omit it."
        )

    messages_data, status_code = get_session_messages(session_id)
    if status_code < 400:
        transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages_data.get("messages", []))
        if transcript:
            parts.append(f"[Prior conversation in this session]\n{transcript}")

    return "\n\n".join(parts) if parts else None


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
        context_override = _build_context_override(req.session_id, session_rows[0].get("session_token"))

    data, status_code = run_agent(req.agent_id, req.message, session_id=req.session_id, context_override=context_override)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    if not req.session_id:
        session_token = secrets.token_urlsafe(32)
        registry_row, status_code = insert_chat_session_row(user.access_token, user.id, req.agent_id, data["session_id"], req.label, session_token)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=registry_row)

    return data
```

Note: `list_session_documents_text` is no longer imported/used here — that's the "stop flooding documents" fix. It's still defined in `powabase_client.py`; Task 9 removes the definition once `sessions.py`'s usage is also gone.

- [ ] **Step 2: Restart the server and smoke-test a fresh chat**

```bash
curl -s -X POST http://127.0.0.1:8000/chat -H "Authorization: Bearer <a real user access token>" -H "Content-Type: application/json" -d '{"agent_id": "<a real agent id you own>", "message": "Say OK."}'
```

Expected: `200` with `{"content": "OK"...}`-shaped body, no 500. Full multi-scenario verification happens in Task 11.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chat.py
git commit -m "fix: stop unconditionally injecting session document text; inject session token for the context tool instead"
```

---

### Task 7: Register the tool on every newly created agent

**Files:**
- Modify: `app/routes/agents.py`

**Interfaces:**
- Consumes: `ensure_session_context_tool`, `assign_tool_to_agent`, `SESSION_CONTEXT_TOOL_NAME` (Task 3).

- [ ] **Step 1: Wire tool assignment into `create_agent_route`**

Read `app/routes/agents.py`, then:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    ensure_session_context_tool,
    insert_agent_registry_row,
    link_agent_knowledge_base,
    list_agent_registry_rows,
)

router = APIRouter(prefix="/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: str
    system_prompt: str | None = None


@router.post("")
def create_agent_route(req: CreateAgentRequest, user: AuthedUser = Depends(get_current_user)):
    kb_data, status_code = create_knowledge_base(f"{req.name}-{user.id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(req.name, req.system_prompt)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_data)
    agent_id = agent_data["id"]

    _, status_code = link_agent_knowledge_base(agent_id, kb_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to link knowledge base to new agent")

    tool_id = ensure_session_context_tool()
    _, status_code = assign_tool_to_agent(agent_id, tool_id, SESSION_CONTEXT_TOOL_NAME)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to attach session-context tool to new agent")

    registry_row, status_code = insert_agent_registry_row(user.access_token, user.id, agent_id, kb_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)
    return registry_row


@router.get("")
def list_agents_route(user: AuthedUser = Depends(get_current_user)):
    data, status_code = list_agent_registry_rows(user.access_token)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

- [ ] **Step 2: Verify a new agent gets the tool assigned**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

creds = {"email": "task7-verify-user@example.com", "password": "SanityTest123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task7 Verify Agent"})
assert r.status_code == 200, r.text
agent_id = r.json()["agent_id"]
print("created agent:", agent_id)

r = requests.get(f"{BASE}/api/agents/{agent_id}/tools", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
body = r.json()
tool_names = [t["tool_name"] for t in (body.get("tools") if isinstance(body, dict) else body)]
print("tools on new agent:", tool_names)
assert "session_context_search" in tool_names
print("confirmed: session_context_search auto-assigned on agent creation")
EOF
```

Expected: prints "confirmed: session_context_search auto-assigned on agent creation". (If the GET response shape differs from the guessed `{"tools": [...]}`, print the raw response first and adjust the parsing inline.)

- [ ] **Step 3: Commit**

```bash
git add app/routes/agents.py
git commit -m "feat: auto-assign session-context tool to every newly created agent"
```

---

### Task 8: Backfill the tool onto existing agents

**Files:**
- Create: `scripts/backfill_session_context_tool.py`

**Interfaces:**
- Consumes: `ensure_session_context_tool`, `assign_tool_to_agent`, `SESSION_CONTEXT_TOOL_NAME` (Task 3).

- [ ] **Step 1: Write the script**

```python
import requests

from app.config import settings
from app.powabase_client import SESSION_CONTEXT_TOOL_NAME, assign_tool_to_agent, ensure_session_context_tool

BASE = settings.powabase_url
SVC = settings.powabase_service_key


def main():
    tool_id = ensure_session_context_tool()
    print("session-context tool id:", tool_id)

    r = requests.get(
        f"{BASE}/rest/v1/agents_registry",
        headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"},
        params={"select": "agent_id,name"},
    )
    r.raise_for_status()
    rows = r.json()
    print(f"found {len(rows)} existing agents")

    for row in rows:
        _, status_code = assign_tool_to_agent(row["agent_id"], tool_id, SESSION_CONTEXT_TOOL_NAME)
        if status_code >= 400:
            print(f"  agent {row['agent_id']} ({row['name']}): skipped (status {status_code} — likely already assigned)")
        else:
            print(f"  agent {row['agent_id']} ({row['name']}): tool attached")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 scripts/backfill_session_context_tool.py
```

Expected: lists every pre-existing agent (from earlier sanity-check runs, etc.) and reports the tool attached (or skipped if this is a fresh project with none yet).

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill_session_context_tool.py
git commit -m "chore: add one-time backfill script for the session-context tool"
```

---

### Task 9: Rewrite `attach-document` for lazy per-session Knowledge Bases + add session delete

**Files:**
- Modify: `app/routes/sessions.py`
- Modify: `app/powabase_client.py` (delete now-dead functions)

**Interfaces:**
- Consumes: `create_knowledge_base`, `update_chat_session_kb_id`, `add_source_to_kb`, `delete_knowledge_base`, `delete_chat_session_row` (existing + Task 4).
- Produces: `POST /agents/{agent_id}/sessions/{session_id}/attach-document` now returns `{"kb_id", "source_id", "filename", ...index fields}` instead of a `session_documents` row. `DELETE /agents/{agent_id}/sessions/{session_id}` — ownership-checked, deletes the session's KB (if any) then the `chat_sessions` row.

- [ ] **Step 1: Rewrite the route file**

Read `app/routes/sessions.py`, then replace the imports and all routes:

```python
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    add_source_to_kb,
    create_knowledge_base,
    delete_chat_session_row,
    delete_knowledge_base,
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    get_source,
    list_chat_sessions,
    update_chat_session_kb_id,
    upload_source,
)

router = APIRouter(prefix="/agents", tags=["sessions"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


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

    kb_id = session_rows[0].get("kb_id")
    if not kb_id:
        kb_data, status_code = create_knowledge_base(f"session-{session_id}")
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_data)
        kb_id = kb_data["id"]
        _, status_code = update_chat_session_kb_id(user.access_token, agent_id, session_id, kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail="Failed to save session's knowledge base id")

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
            detail=f"Document extraction ended in status '{extraction_status}', cannot index",
        )

    index_data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=index_data)

    return {"kb_id": kb_id, "source_id": source_id, "filename": file.filename, **index_data}


@router.delete("/{agent_id}/sessions/{session_id}")
def delete_session_route(agent_id: str, session_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    kb_id = session_rows[0].get("kb_id")
    if kb_id:
        kb_result, status_code = delete_knowledge_base(kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_result)

    _, status_code = delete_chat_session_row(user.access_token, agent_id, session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to delete session")

    return {"deleted": True, "kb_deleted": bool(kb_id)}
```

- [ ] **Step 2: Delete the now-dead `session_documents` functions from `powabase_client.py`**

Read `app/powabase_client.py`, then delete these three function definitions entirely (they have no remaining callers after Step 1 and Task 6):
- `get_source_text_derivative`
- `insert_session_document_row`
- `list_session_documents_text`

Leave everything else in the file untouched. Do **not** touch the `session_documents` table itself (Global Constraints).

- [ ] **Step 3: Verify no leftover references**

```bash
cd /home/william/powabase-chatbot && grep -rn "session_documents\|insert_session_document_row\|list_session_documents_text\|get_source_text_derivative\|MAX_DOCUMENT_TOKENS" app/
```

Expected: no output.

- [ ] **Step 4: Restart uvicorn and smoke-test attach-document**

```bash
curl -s -X POST http://127.0.0.1:8000/agents/<agent_id>/sessions/<session_id>/attach-document -H "Authorization: Bearer <token>" -F "file=@test.pdf"
```

Expected: `200` with `{"kb_id": "...", "source_id": "...", "filename": "test.pdf", ...}`. Full scenario coverage is Task 11.

- [ ] **Step 5: Commit**

```bash
git add app/routes/sessions.py app/powabase_client.py
git commit -m "feat: lazy per-session knowledge bases for attach-document; add session delete endpoint"
```

---

### Task 10: End-to-end sanity script + live run

**Files:**
- Create: `scripts/sanity_check_session_kb.py`

**Interfaces:**
- Consumes: every route/function from Tasks 5–9, plus direct Powabase API calls (service key) to independently verify tool-call behavior and KB deletion. Both `GET /api/sessions/{id}/runs` (envelope: `{"limit","offset","runs":[...],"session_id"}`, each run has `created_at` and top-level `tool_calls: [{"tool_name","arguments","result","duration_ms","step"}]`) and `GET /api/knowledge-bases/{id}/sources` (envelope: `{"items":[...],"limit","offset","total"}`, each item has `source_id`, `index_status`) were live-verified on 2026-08-04.

- [ ] **Step 1: Write the script**

```python
import time

import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-kb-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-kb-user-b@example.com", "password": "SanityTest123!"}


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


def chat(token, agent_id, message, session_id=None):
    body = {"agent_id": agent_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    return requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def attach_document(token, agent_id, session_id, content_bytes, filename):
    return requests.post(
        f"{APP}/agents/{agent_id}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content_bytes)},
    )


def delete_session(token, agent_id, session_id):
    return requests.delete(f"{APP}/agents/{agent_id}/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"})


def latest_run_tool_calls(session_id):
    r = requests.get(f"{BASE}/api/sessions/{session_id}/runs", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
    r.raise_for_status()
    runs = r.json()["runs"]
    latest = sorted(runs, key=lambda run: run["created_at"])[-1]
    return latest.get("tool_calls") or []


def wait_for_kb_indexed(kb_id, source_id, timeout=60):
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}/sources", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
        r.raise_for_status()
        items = r.json()["items"]
        match = next((i for i in items if i["source_id"] == source_id), None)
        if match and match["index_status"] == "indexed":
            return
        if match and match["index_status"] == "failed":
            raise AssertionError(f"indexing failed for source {source_id}: {match}")
        time.sleep(2)
        elapsed += 2
    raise AssertionError(f"timed out waiting for source {source_id} to index into kb {kb_id}")


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity KB Agent A")
    print("agent A:", agent_a["agent_id"])

    # --- 1. No document attached: normal chat + tool reports nothing to search ---
    r = chat(token_a, agent_a["agent_id"], "Say OK, nothing else.")
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    print("turn 1 (no doc) ok, session:", session_id)

    r = chat(token_a, agent_a["agent_id"], "Is there a document attached to this conversation? If you're unsure, check.", session_id=session_id)
    assert r.status_code == 200, r.text
    print("turn 2 (no doc, tool-checking question) ok:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    for call in tool_calls:
        if call["tool_name"] == "session_context_search":
            assert "nothing to search" in call["result"].lower() or "no document" in call["result"].lower(), call
            print("  tool correctly reported nothing to search:", call["result"])

    # --- 2. Attach a document, ask something requiring it ---
    doc1 = b"CLASSIFIED PROJECT FACT: the reactor override code is NEON-7734."
    r = attach_document(token_a, agent_a["agent_id"], session_id, doc1, "doc1.txt")
    assert r.status_code == 200, r.text
    kb_id_1 = r.json()["kb_id"]
    source_id_1 = r.json()["source_id"]
    print("attach doc1 ok, kb_id:", kb_id_1)
    wait_for_kb_indexed(kb_id_1, source_id_1)

    r = chat(token_a, agent_a["agent_id"], "What is the reactor override code mentioned in the attached document?", session_id=session_id)
    assert r.status_code == 200 and "NEON-7734" in r.json()["content"], r.text
    print("doc1 fact correctly answered:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    assert any(c["tool_name"] == "session_context_search" for c in tool_calls), "expected the tool to be called for a doc-requiring question"
    print("  confirmed: tool was called for the doc-requiring question")

    # --- 3. Same session, unrelated question: tool should NOT be pulled in unnecessarily ---
    r = chat(token_a, agent_a["agent_id"], "What is 17 times 4? Answer with just the number.", session_id=session_id)
    assert r.status_code == 200, r.text
    print("unrelated question answered:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    called = any(c["tool_name"] == "session_context_search" for c in tool_calls)
    print(f"  session_context_search called for unrelated question: {called} (expected False)")
    assert not called, "efficiency fix failed: tool was called for a question unrelated to the document"

    # --- 4. Second document, same session: both searchable via the same session KB ---
    doc2 = b"SECOND FACT: the evacuation rally point is GATE-ORCHID-12."
    r = attach_document(token_a, agent_a["agent_id"], session_id, doc2, "doc2.txt")
    assert r.status_code == 200, r.text
    kb_id_2 = r.json()["kb_id"]
    source_id_2 = r.json()["source_id"]
    assert kb_id_2 == kb_id_1, f"expected the SAME session kb reused, got {kb_id_2} vs {kb_id_1}"
    print("attach doc2 ok, reused same kb_id:", kb_id_2)
    wait_for_kb_indexed(kb_id_2, source_id_2)

    r = chat(token_a, agent_a["agent_id"], "What is the reactor override code?", session_id=session_id)
    assert r.status_code == 200 and "NEON-7734" in r.json()["content"], r.text
    print("doc1 fact still answerable after doc2 attached:", r.json()["content"])

    r = chat(token_a, agent_a["agent_id"], "What is the evacuation rally point?", session_id=session_id)
    assert r.status_code == 200 and "GATE-ORCHID-12" in r.json()["content"], r.text
    print("doc2 fact answerable:", r.json()["content"])

    # --- 5. Delete the session: confirm the KB is actually gone via Powabase's API directly ---
    r = delete_session(token_a, agent_a["agent_id"], session_id)
    assert r.status_code == 200 and r.json()["kb_deleted"] is True, r.text
    print("session delete ok:", r.json())

    r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id_1}", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
    assert r.status_code == 404, f"expected the kb to be gone (404), got {r.status_code}: {r.text}"
    print("confirmed via Powabase API: session kb is actually deleted")

    # --- 6. Cross-user isolation ---
    r2 = chat(token_a, agent_a["agent_id"], "Say OK.")
    assert r2.status_code == 200
    session_id_2 = r2.json()["session_id"]
    doc3 = b"USER A PRIVATE FACT: the vault combination is 91-42-83."
    r = attach_document(token_a, agent_a["agent_id"], session_id_2, doc3, "doc3.txt")
    assert r.status_code == 200, r.text
    kb_id_3 = r.json()["kb_id"]
    source_id_3 = r.json()["source_id"]
    wait_for_kb_indexed(kb_id_3, source_id_3)

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user session listing blocked ok")

    r = delete_session(token_b, agent_a["agent_id"], session_id_2)
    assert r.status_code == 403
    print("cross-user session delete blocked ok")

    # No legitimate way for an attacker to learn User A's real session_token --
    # confirm a fabricated one gets the same graceful "invalid" response and
    # leaks nothing, hitting the tool endpoint directly (bypassing the LLM
    # entirely -- the strongest form of this test).
    r = requests.post(f"{APP}/tools/session-context", json={"query": "vault combination", "session_token": "guessed-token-does-not-exist"})
    assert r.status_code == 200
    assert "91-42-83" not in r.text
    assert "invalid session token" in r.text.lower()
    print("cross-user tool probe with a fabricated token correctly returned nothing:", r.text)

    print("\nALL LAZY-SESSION-KB SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the live `uvicorn` + ngrok setup**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 scripts/sanity_check_session_kb.py
```

Expected: every `assert` passes and the script prints `ALL LAZY-SESSION-KB SANITY CHECKS PASSED`. If step 3 (`unrelated question`) is flaky because the model calls the tool anyway, that's a real finding, not a test bug — tighten the tool's `description` (Task 3) to more strongly discourage off-topic calls, don't loosen the test.

- [ ] **Step 3: Commit**

```bash
git add scripts/sanity_check_session_kb.py
git commit -m "test: add end-to-end sanity check for lazy session kb and session-context tool"
```

---

## After this plan lands

- `public.session_documents` still exists in Postgres (Global Constraints — not dropped automatically). Once you've eyeballed Task 10's output and are satisfied, the drop is:
  ```sql
  drop table public.session_documents;
  ```
  Run that yourself in Studio when ready — it's intentionally not a step in this plan.
- Keep the ngrok tunnel running for as long as you want the session-context tool to work; if it restarts (new free-tier URL), update `PUBLIC_BASE_URL` in `.env` and re-run `ensure_session_context_tool()` (e.g. `python3 -c "from app.powabase_client import ensure_session_context_tool; print(ensure_session_context_tool())"`) to repoint the existing Tool at the new URL — no need to recreate it or reassign it to agents.
