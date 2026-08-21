# Chatbots (Multi-Agent Orchestration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new top-level "chatbot" entity — a Powabase orchestrator coordinating one or more user-defined subagents — as a user-facing layer above today's single-agent `agents_registry`, without changing any existing standalone-agent behavior.

**Architecture:** A new `chatbots` table (one row per orchestrator, owned by a user) and two new nullable columns on `agents_registry` (`chatbot_id`, `orchestration_entity_id`) let a subagent be tracked exactly like a standalone agent, plus two extra pointers back to its chatbot and its Powabase orchestration-entity-link id. `POST /chatbots` creates an orchestrator (`strategy: "supervisor"`, a fixed, non-user-configurable `orchestrator_config.additional_instructions`) plus its first subagent (its own isolated KB, same helper logic as `POST /agents`), and adds that agent as an entity. `POST /chatbots/{id}/agents` repeats the "create subagent + add as entity" half for additional members. Deletion is the hard part: `DELETE /api/orchestrations/{id}` does **not** cascade to member agents (verified live), and deleting an agent that's still an orchestration entity leaves a dangling reference (also verified live) — so every deletion route must explicitly remove the Powabase orchestration entity link, the agent, and the agent's KB, in that order, and — critically — when the last subagent is removed from a chatbot, the whole orchestrator and the `chatbots` row are cascade-deleted too (never leaving a zero-entity orchestrator alive). Chat with a chatbot goes through `POST /api/orchestrations/{id}/run/stream`; unlike single-agent `/chat`, this endpoint's `context_override` is silently ignored (verified live), so `chatbot_id`-scoped chat relies purely on native `session_id` continuity — no context/transcript injection is attempted at the orchestrator level.

**Tech Stack:** FastAPI 0.139, Pydantic 2.13, `requests`, Powabase (`/api/orchestrations`, `/api/agents`, `/api/knowledge-bases`, PostgREST).

## Global Constraints

- Keep the `(data, status_code)` tuple return pattern for every function in `app/powabase_client.py`, exactly like every existing function in that file.
- `/api/*` calls use the **Service Role key** for both `apikey` and `Authorization` (existing pattern, unchanged). `/rest/v1/{table}` calls for `chatbots`/`chatbot_sessions`/`agents_registry` use `apikey: <Anon key>` + `Authorization: Bearer <the calling user's own access token>` — never the service key — so Postgres RLS itself enforces per-user scoping (defense in depth, same pattern as every existing table in this project).
- **Do not modify any existing route file's existing routes.** `app/routes/agents.py`, `app/routes/chat.py`, `app/routes/ingest.py`, `app/routes/sessions.py` are untouched except where explicitly noted (only `insert_agent_registry_row`'s signature in `powabase_client.py` gains two new optional kwargs — its one existing call site in `routes/agents.py` is not modified and continues to insert `NULL` for both).
- **`context_override` must never be passed to `run_orchestration`.** Verified live on 2026-08-09: `POST /api/orchestrations/{id}/run/stream` accepts `context_override` in the request body (200 OK) but the coordinator never sees it — a test message with `context_override: "The secret code is XYZZY-99."` got the answer "I don't know." Do not build a `_build_context_override`-style helper for chatbot chat; it would be dead code.
- **The orchestrator's `orchestrator_config.additional_instructions` is fixed and not exposed via any request body field.** It lives as the module-level constant `ORCHESTRATOR_SYSTEM_PROMPT` in `app/routes/chatbots.py`. Users supply `role_description` per subagent (required field) and each subagent's own `system_prompt` (optional, same as today's `POST /agents`) — never the orchestrator's own prompt.
- **`DELETE /api/agents/{id}` and `DELETE /api/knowledge-bases/{id}` are idempotent** — verified live, both return `200` even for an already-deleted id. Treat any status `>= 400` from these two as a genuine failure; there is no "already gone" case to special-case.
- **`DELETE /api/orchestrations/{id}` and `DELETE /api/orchestrations/{id}/entities/{eid}` are NOT idempotent** — verified live, both return `404` (`{"error": "Orchestration not found"}` / `{"error": "Entity not found"}`) for an already-gone resource. Treat `404` from these two as "already removed, continue" and only `>= 400` and `!= 404` as a real failure — this makes retrying a partially-failed delete safe.
- No test framework is installed (no `pytest`, no `tests/` dir) — verification uses direct `requests` calls against a locally running `uvicorn` and the live Powabase API, matching every existing `scripts/sanity_check*.py` in this project.
- Live API shapes referenced below (`POST /api/orchestrations`, entity add/remove, orchestration `run/stream` SSE event shapes including the zero-entity `complete` event's `status: "failed"` field, `DELETE /api/orchestrations/{id}` non-cascading behavior, dangling-entity behavior after agent deletion, delete idempotency) were verified live against the project on 2026-08-09.

---

### Task 1: `chatbots` table, `agents_registry` columns, `chatbot_sessions` table (manual SQL, Studio step)

This needs DDL access, which this project's `.env` doesn't have (no Database URL) — same situation as every prior table/column change in this project's history. Manual step in the Powabase Studio SQL editor.

**Files:** none (pure database change, done outside this repo)

**Interfaces:**
- Produces: `public.chatbots` (`id`, `user_id`, `orchestrator_id uuid not null`, `name`, `created_at`), RLS enabled, 4 owner-scoped policies (same pattern as `agents_registry`). `public.agents_registry.chatbot_id` (`uuid`, nullable, references `chatbots(id)`) and `public.agents_registry.orchestration_entity_id` (`uuid`, nullable — Powabase's own entity-link id, needed to call `DELETE /api/orchestrations/{id}/entities/{eid}` precisely). `public.chatbot_sessions` (`id`, `user_id`, `chatbot_id uuid not null references chatbots(id)`, `powabase_session_id text not null`, `label text`, `created_at`), RLS enabled, 4 owner-scoped policies — mirrors `chat_sessions` but without `kb_id`/`session_token` (chatbot-level chat has no session-context-tool injection, per the `context_override` finding above).

- [ ] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run:

```sql
create table public.chatbots (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users,
  orchestrator_id uuid not null,
  name text not null,
  created_at timestamptz not null default now()
);

alter table public.chatbots enable row level security;

create policy "chatbots_select_own" on public.chatbots
  for select to authenticated using (user_id = auth.uid());

create policy "chatbots_insert_own" on public.chatbots
  for insert to authenticated with check (user_id = auth.uid());

create policy "chatbots_update_own" on public.chatbots
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "chatbots_delete_own" on public.chatbots
  for delete to authenticated using (user_id = auth.uid());

alter table public.agents_registry add column chatbot_id uuid references public.chatbots(id);
alter table public.agents_registry add column orchestration_entity_id uuid;

create table public.chatbot_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users,
  chatbot_id uuid not null references public.chatbots(id),
  powabase_session_id text not null,
  label text,
  created_at timestamptz not null default now()
);

alter table public.chatbot_sessions enable row level security;

create policy "chatbot_sessions_select_own" on public.chatbot_sessions
  for select to authenticated using (user_id = auth.uid());

create policy "chatbot_sessions_insert_own" on public.chatbot_sessions
  for insert to authenticated with check (user_id = auth.uid());

create policy "chatbot_sessions_update_own" on public.chatbot_sessions
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "chatbot_sessions_delete_own" on public.chatbot_sessions
  for delete to authenticated using (user_id = auth.uid());

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2.

- [ ] **Step 2: Verify the tables/columns exist, RLS blocks anon reads, and existing `agents_registry` rows are unaffected**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

# New columns exist and existing rows got NULL (not an error, not a default other than NULL)
r = requests.get(f"{BASE}/rest/v1/agents_registry", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"select": "id,chatbot_id,orchestration_entity_id", "limit": 5})
print("existing agents_registry rows now show new columns:", r.status_code, r.json())
assert r.status_code == 200
assert all(row["chatbot_id"] is None and row["orchestration_entity_id"] is None for row in r.json()), "existing rows must have NULL for both new columns"

# chatbots / chatbot_sessions tables exist and anon (no user token) is blocked by RLS
r = requests.get(f"{BASE}/rest/v1/chatbots", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"select": "id", "limit": 1})
print("anon read chatbots (RLS should block -> expect [], 200):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

r = requests.get(f"{BASE}/rest/v1/chatbot_sessions", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"select": "id", "limit": 1})
print("anon read chatbot_sessions (RLS should block -> expect [], 200):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

print("\nSCHEMA VERIFIED")
EOF
```

Expected output ends with `SCHEMA VERIFIED`. If the first query 404s, the schema cache hasn't reloaded — re-run `notify pgrst, 'reload schema';` and retry.

- [ ] **Step 3: Commit the plan's record of this manual step**

No code changed in this task — nothing to commit. Proceed to Task 2.

---

### Task 2: `powabase_client.py` — orchestration lifecycle functions + chatbot/chatbot-session DB functions

**Files:**
- Modify: `app/powabase_client.py` — add orchestration API functions, `chatbots`/`chatbot_sessions` PostgREST functions, extend `insert_agent_registry_row`

**Interfaces:**
- Produces: `create_orchestration(name: str, orchestrator_config: dict) -> tuple[dict, int]`; `add_orchestration_entity(orchestration_id: str, agent_id: str, role_description: str) -> tuple[dict, int]`; `remove_orchestration_entity(orchestration_id: str, entity_id: str) -> tuple[dict, int]`; `delete_orchestration(orchestration_id: str) -> tuple[dict, int]`; `delete_agent(agent_id: str) -> tuple[dict, int]`; `run_orchestration(orchestration_id: str, message: str, session_id: str | None = None) -> tuple[dict, int]` (mirrors `run_agent`'s SSE-parsing shape but never sends `context_override`, and treats a `complete` event with `status: "failed"` as an error, not a success). `insert_chatbot_row(access_token, user_id, orchestrator_id, name) -> tuple[dict, int]`; `list_chatbot_rows(access_token) -> tuple[list, int]`; `get_chatbot_entry(access_token, chatbot_id) -> tuple[list, int]`; `delete_chatbot_row(access_token, chatbot_id) -> tuple[dict, int]`; `list_chatbot_agent_rows(access_token, chatbot_id) -> tuple[list, int]`; `get_chatbot_agent_entry(access_token, chatbot_id, agent_id) -> tuple[list, int]`; `delete_agent_registry_row(access_token, agent_id) -> tuple[dict, int]`; `insert_chatbot_session_row(access_token, user_id, chatbot_id, powabase_session_id, label) -> tuple[dict, int]`; `get_chatbot_session_entry(access_token, chatbot_id, session_id) -> tuple[list, int]`. `insert_agent_registry_row` gains two new optional kwargs: `chatbot_id: str | None = None, orchestration_entity_id: str | None = None` — its existing call site in `routes/agents.py` is untouched and keeps inserting `NULL` for both. Task 3 onward consumes all of these.

- [ ] **Step 1: Extend `insert_agent_registry_row`'s signature**

Read `app/powabase_client.py`, then find `insert_agent_registry_row` and replace it:

```python
def insert_agent_registry_row(
    access_token: str,
    user_id: str,
    agent_id: str,
    kb_id: str,
    name: str,
    chatbot_id: str | None = None,
    orchestration_entity_id: str | None = None,
) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={
            "user_id": user_id,
            "agent_id": agent_id,
            "kb_id": kb_id,
            "name": name,
            "chatbot_id": chatbot_id,
            "orchestration_entity_id": orchestration_entity_id,
        },
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code
```

(Only the signature and the `json=` body change — two new keys added, both `None` by default, which PostgREST inserts as SQL `NULL`.)

- [ ] **Step 2: Add orchestration lifecycle functions**

Append to `app/powabase_client.py`, after `run_agent`:

```python
def create_orchestration(name: str, orchestrator_config: dict) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/orchestrations",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"name": name, "strategy": "supervisor", "orchestrator_config": orchestrator_config},
    )
    return response.json(), response.status_code


def add_orchestration_entity(orchestration_id: str, agent_id: str, role_description: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}/entities",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"entity_type": "agent", "entity_ref_id": agent_id, "role_description": role_description},
    )
    return response.json(), response.status_code


def remove_orchestration_entity(orchestration_id: str, entity_id: str) -> dict:
    response = requests.delete(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}/entities/{entity_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def delete_orchestration(orchestration_id: str) -> dict:
    response = requests.delete(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def delete_agent(agent_id: str) -> dict:
    response = requests.delete(
        f"{settings.powabase_url}/api/agents/{agent_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def run_orchestration(orchestration_id: str, message: str, session_id: str | None = None) -> dict:
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id

    with requests.post(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}/run/stream",
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
                if event.get("status") == "failed":
                    return {"error": event.get("error") or "orchestration run failed"}, 502
                return {
                    "content": event["content"],
                    "session_id": run_session_id,
                    "usage": event.get("usage"),
                }, 200
            elif kind == "error":
                return {"error": event.get("message"), "code": event.get("code")}, 502

        return {"error": "stream ended without a complete event"}, 502
```

(`run_orchestration` is a near-copy of `run_agent` — the differences are the URL path, no `context_override` parameter at all, and the `status == "failed"` check inside the `complete` handler, which `run_agent` doesn't need because a single agent's `/run/stream` doesn't emit that shape.)

- [ ] **Step 3: Add `chatbots` table functions**

Append:

```python
def insert_chatbot_row(access_token: str, user_id: str, orchestrator_id: str, name: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/chatbots",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"user_id": user_id, "orchestrator_id": orchestrator_id, "name": name},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def list_chatbot_rows(access_token: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chatbots",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"select": "id,orchestrator_id,name,created_at", "order": "created_at.desc"},
    )
    return response.json(), response.status_code


def get_chatbot_entry(access_token: str, chatbot_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chatbots",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"id": f"eq.{chatbot_id}", "select": "id,orchestrator_id,name,created_at"},
    )
    return response.json(), response.status_code


def delete_chatbot_row(access_token: str, chatbot_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/rest/v1/chatbots",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"id": f"eq.{chatbot_id}"},
    )
    if response.status_code >= 400:
        return response.json(), response.status_code
    return {}, response.status_code
```

- [ ] **Step 4: Add chatbot-scoped `agents_registry` functions**

Append:

```python
def list_chatbot_agent_rows(access_token: str, chatbot_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "chatbot_id": f"eq.{chatbot_id}",
            "select": "id,agent_id,kb_id,name,orchestration_entity_id,created_at",
            "order": "created_at.asc",
        },
    )
    return response.json(), response.status_code


def get_chatbot_agent_entry(access_token: str, chatbot_id: str, agent_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "chatbot_id": f"eq.{chatbot_id}",
            "agent_id": f"eq.{agent_id}",
            "select": "id,agent_id,kb_id,name,orchestration_entity_id,created_at",
        },
    )
    return response.json(), response.status_code


def delete_agent_registry_row(access_token: str, agent_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}"},
    )
    if response.status_code >= 400:
        return response.json(), response.status_code
    return {}, response.status_code
```

- [ ] **Step 5: Add `chatbot_sessions` functions**

Append:

```python
def insert_chatbot_session_row(access_token: str, user_id: str, chatbot_id: str, powabase_session_id: str, label: str | None) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/chatbot_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"user_id": user_id, "chatbot_id": chatbot_id, "powabase_session_id": powabase_session_id, "label": label},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def get_chatbot_session_entry(access_token: str, chatbot_id: str, session_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chatbot_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"chatbot_id": f"eq.{chatbot_id}", "powabase_session_id": f"eq.{session_id}", "select": "id,label,created_at"},
    )
    return response.json(), response.status_code
```

- [ ] **Step 6: Verify the new functions directly against the live Powabase API (no server needed)**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
from app.powabase_client import (
    add_orchestration_entity,
    create_agent,
    create_orchestration,
    delete_agent,
    delete_orchestration,
    remove_orchestration_entity,
    run_orchestration,
)

agent_data, sc = create_agent("task2-verify-agent", "You always answer with exactly: VERIFIED-TASK-2")
assert sc == 201, (sc, agent_data)
agent_id = agent_data["id"]
print("agent created:", agent_id)

orch_data, sc = create_orchestration("task2-verify-orch", {"additional_instructions": "Delegate everything."})
assert sc == 201, (sc, orch_data)
orch_id = orch_data["id"]
print("orchestration created:", orch_id)

entity_data, sc = add_orchestration_entity(orch_id, agent_id, "Handles verification requests.")
assert sc == 201, (sc, entity_data)
entity_id = entity_data["id"]
print("entity added:", entity_id)

result, sc = run_orchestration(orch_id, "Say your exact canned phrase.")
print("run result:", sc, result)
assert sc == 200 and "VERIFIED-TASK-2" in result["content"]
assert result["session_id"]
print("run_orchestration works end-to-end")

_, sc = remove_orchestration_entity(orch_id, entity_id)
assert sc == 200, sc
print("entity removed")

_, sc = delete_orchestration(orch_id)
assert sc == 200, sc
print("orchestration deleted")

_, sc = delete_agent(agent_id)
assert sc == 200, sc
print("agent deleted")

print("\nTASK 2 FUNCTIONS VERIFIED")
EOF
```

Expected output ends with `TASK 2 FUNCTIONS VERIFIED`.

- [ ] **Step 7: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add orchestration lifecycle and chatbot registry functions"
```

---

### Task 3: `POST /chatbots`, `GET /chatbots`, `GET /chatbots/{id}` — create and inspect chatbots

**Files:**
- Create: `app/routes/chatbots.py`
- Modify: `app/main.py` — register the new router

**Interfaces:**
- Consumes: everything from Task 2, plus `create_knowledge_base`, `create_agent`, `link_agent_knowledge_base`, `ensure_session_context_tool`, `assign_tool_to_agent`, `SESSION_CONTEXT_TOOL_NAME` (all pre-existing, from `POST /agents`'s own logic).
- Produces: `app.routes.chatbots.router`; `_create_subagent(name, system_prompt, user_id) -> tuple[str, str]` (returns `(agent_id, kb_id)`) — a private helper Task 4/5 also import and reuse; `ORCHESTRATOR_SYSTEM_PROMPT: str` module constant. `POST /chatbots` request body `{name, agent_name, role_description, system_prompt?}`, response `{"chatbot": {...}, "agent": {...}}`. `GET /chatbots` returns a bare array of chatbot rows. `GET /chatbots/{id}` returns `{...chatbot fields, "agents": [...]}`.

- [ ] **Step 1: Create `app/routes/chatbots.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_orchestration_entity,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    create_orchestration,
    ensure_session_context_tool,
    get_chatbot_entry,
    insert_agent_registry_row,
    insert_chatbot_row,
    link_agent_knowledge_base,
    list_chatbot_agent_rows,
    list_chatbot_rows,
)

router = APIRouter(prefix="/chatbots", tags=["chatbots"])

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the coordinator of a multi-agent assistant. Your job is to route each "
    "user request to the specialist agent(s) whose role best matches it, using the "
    "role descriptions provided for each agent. If a request spans multiple agents' "
    "roles, delegate to each relevant agent and synthesize their results into a single, "
    "coherent reply. If no agent's role matches the request, answer directly using your "
    "own general knowledge, or say plainly that you don't have a specialist for that. "
    "Never fabricate information a delegated agent didn't provide."
)


class CreateChatbotRequest(BaseModel):
    name: str
    agent_name: str
    role_description: str
    system_prompt: str | None = None


def _create_subagent(name: str, system_prompt: str | None, user_id: str) -> tuple[str, str]:
    """Agent + its own isolated KB + session-context tool -- same recipe as POST /agents."""
    kb_data, status_code = create_knowledge_base(f"{name}-{user_id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(name, system_prompt)
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

    return agent_id, kb_id


@router.post("")
def create_chatbot_route(req: CreateChatbotRequest, user: AuthedUser = Depends(get_current_user)):
    agent_id, kb_id = _create_subagent(req.agent_name, req.system_prompt, user.id)

    orch_data, status_code = create_orchestration(req.name, {"additional_instructions": ORCHESTRATOR_SYSTEM_PROMPT})
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=orch_data)
    orchestrator_id = orch_data["id"]

    entity_data, status_code = add_orchestration_entity(orchestrator_id, agent_id, req.role_description)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=entity_data)
    entity_id = entity_data["id"]

    chatbot_row, status_code = insert_chatbot_row(user.access_token, user.id, orchestrator_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=chatbot_row)
    chatbot_id = chatbot_row["id"]

    registry_row, status_code = insert_agent_registry_row(
        user.access_token,
        user.id,
        agent_id,
        kb_id,
        req.agent_name,
        chatbot_id=chatbot_id,
        orchestration_entity_id=entity_id,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)

    return {"chatbot": chatbot_row, "agent": registry_row}


@router.get("")
def list_chatbots_route(user: AuthedUser = Depends(get_current_user)):
    data, status_code = list_chatbot_rows(user.access_token)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{chatbot_id}")
def get_chatbot_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")

    agent_rows, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_rows)

    return {**chatbot_rows[0], "agents": agent_rows}
```

- [ ] **Step 2: Register the router in `app/main.py`**

Read `app/main.py`, then:

```python
from fastapi import FastAPI

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.ingest import router as ingest_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
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

- [ ] **Step 3: Start the server and verify create/list/get**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"
creds = {"email": "task3-verify@example.com", "password": "TestPass123!"}

r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token}"}, json={
    "name": "Task3 Chatbot", "agent_name": "Task3 First Agent", "role_description": "Handles everything for now."
})
print(r.status_code, r.json())
assert r.status_code == 200
body = r.json()
chatbot_id = body["chatbot"]["id"]
assert body["agent"]["chatbot_id"] == chatbot_id
assert body["agent"]["orchestration_entity_id"]

r = requests.get(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token}"})
assert r.status_code == 200 and any(c["id"] == chatbot_id for c in r.json())
print("list ok")

r = requests.get(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token}"})
assert r.status_code == 200
detail = r.json()
assert detail["id"] == chatbot_id
assert len(detail["agents"]) == 1
print("get with agents ok:", detail)

print("OK: chatbot create/list/get all work")
EOF
```

Expected: `OK: chatbot create/list/get all work`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/chatbots.py app/main.py
git commit -m "feat: add POST/GET /chatbots to create and inspect multi-agent chatbots"
```

---

### Task 4: `POST /chatbots/{id}/agents` — add a subagent to an existing chatbot

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `_create_subagent`, `add_orchestration_entity`, `get_chatbot_entry`, `insert_agent_registry_row` (all Task 2/3).
- Produces: `POST /chatbots/{chatbot_id}/agents` request body `{name, role_description, system_prompt?}`, response is the new `agents_registry` row.

- [ ] **Step 1: Add the route**

Add `AddAgentRequest` and the route to `app/routes/chatbots.py` (append after `get_chatbot_route`):

```python
class AddAgentRequest(BaseModel):
    name: str
    role_description: str
    system_prompt: str | None = None


@router.post("/{chatbot_id}/agents")
def add_chatbot_agent_route(chatbot_id: str, req: AddAgentRequest, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    agent_id, kb_id = _create_subagent(req.name, req.system_prompt, user.id)

    entity_data, status_code = add_orchestration_entity(orchestrator_id, agent_id, req.role_description)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=entity_data)
    entity_id = entity_data["id"]

    registry_row, status_code = insert_agent_registry_row(
        user.access_token,
        user.id,
        agent_id,
        kb_id,
        req.name,
        chatbot_id=chatbot_id,
        orchestration_entity_id=entity_id,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)
    return registry_row
```

- [ ] **Step 2: Restart the server and verify a chatbot can grow to 2 agents, and cross-user is blocked**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
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

r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task4 Chatbot", "agent_name": "Task4 Agent One", "role_description": "Handles topic one."
})
chatbot_id = r.json()["chatbot"]["id"]

r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task4 Agent Two", "role_description": "Handles topic two."
})
print(r.status_code, r.json())
assert r.status_code == 200
assert r.json()["chatbot_id"] == chatbot_id

r = requests.get(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
assert len(r.json()["agents"]) == 2
print("chatbot now has 2 agents")

# Cross-user: user B cannot add an agent to user A's chatbot
r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_b}"}, json={
    "name": "Malicious Agent", "role_description": "Should not be allowed."
})
assert r.status_code == 403, (r.status_code, r.text)
print("cross-user add-agent blocked with 403 as expected")

print("OK: multi-agent add + cross-user block both work")
EOF
```

Expected: `OK: multi-agent add + cross-user block both work`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: add POST /chatbots/{id}/agents to grow a chatbot's team"
```

---

### Task 5: `DELETE /chatbots/{id}/agents/{agent_id}` — remove one subagent, cascading the whole chatbot if it was the last one

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `get_chatbot_entry`, `get_chatbot_agent_entry`, `list_chatbot_agent_rows`, `remove_orchestration_entity`, `delete_knowledge_base`, `delete_agent`, `delete_agent_registry_row`, `delete_orchestration`, `delete_chatbot_row` (all Task 2/3).
- Produces: `DELETE /chatbots/{chatbot_id}/agents/{agent_id}` → `{"deleted": true, "chatbot_deleted": bool}`.

- [ ] **Step 1: Add the route**

Add these imports to the top of `app/routes/chatbots.py`'s existing `from app.powabase_client import (...)` block: `delete_agent`, `delete_agent_registry_row`, `delete_chatbot_row`, `delete_knowledge_base`, `delete_orchestration`, `get_chatbot_agent_entry`, `remove_orchestration_entity`. Then append:

```python
@router.delete("/{chatbot_id}/agents/{agent_id}")
def delete_chatbot_agent_route(chatbot_id: str, agent_id: str, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    agent_rows, status_code = get_chatbot_agent_entry(user.access_token, chatbot_id, agent_id)
    if status_code >= 400 or not agent_rows:
        raise HTTPException(status_code=404, detail="Agent not found on this chatbot")
    agent_row = agent_rows[0]

    all_agents, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=all_agents)

    if len(all_agents) == 1:
        # Last agent on this chatbot: the whole orchestration must go too (mentor
        # requirement -- never leave a zero-entity orchestrator alive).
        _, sc = delete_orchestration(orchestrator_id)
        if sc >= 400 and sc != 404:
            raise HTTPException(status_code=sc, detail="Failed to delete orchestrator")

        kb_id = agent_row.get("kb_id")
        if kb_id:
            _, sc = delete_knowledge_base(kb_id)
            if sc >= 400:
                raise HTTPException(status_code=sc, detail="Failed to delete agent's knowledge base")

        _, sc = delete_agent(agent_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent")

        _, sc = delete_agent_registry_row(user.access_token, agent_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent registry row")

        _, sc = delete_chatbot_row(user.access_token, chatbot_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete chatbot row")

        return {"deleted": True, "chatbot_deleted": True}

    # Other agents remain: remove just this one's orchestration entity link, then
    # the agent and its KB. The chatbot and orchestrator stay alive.
    entity_id = agent_row.get("orchestration_entity_id")
    if entity_id:
        _, sc = remove_orchestration_entity(orchestrator_id, entity_id)
        if sc >= 400 and sc != 404:
            raise HTTPException(status_code=sc, detail="Failed to remove agent from orchestrator")

    kb_id = agent_row.get("kb_id")
    if kb_id:
        _, sc = delete_knowledge_base(kb_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent's knowledge base")

    _, sc = delete_agent(agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent")

    _, sc = delete_agent_registry_row(user.access_token, agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent registry row")

    return {"deleted": True, "chatbot_deleted": False}
```

- [ ] **Step 2: Restart the server and verify both branches, plus cross-user protection, plus the orphaned-orchestrator guarantee against Powabase's own API**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
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
SVC_H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}

# --- Branch 1: 2-agent chatbot, delete one, the other survives ---
r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task5 Multi Chatbot", "agent_name": "Task5 Agent One", "role_description": "Handles topic one."
})
chatbot_id = r.json()["chatbot"]["id"]
orchestrator_id = r.json()["chatbot"]["orchestrator_id"]
agent_one_id = r.json()["agent"]["agent_id"]

r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task5 Agent Two", "role_description": "Handles topic two."
})
agent_two_id = r.json()["agent_id"]
kb_two_id = r.json()["kb_id"]

# Cross-user: user B cannot delete user A's subagent
r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_two_id}", headers={"Authorization": f"Bearer {token_b}"})
assert r.status_code == 403, (r.status_code, r.text)
print("cross-user agent delete blocked with 403 as expected")

r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_one_id}", headers={"Authorization": f"Bearer {token_a}"})
print("delete agent_one (not last):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == {"deleted": True, "chatbot_deleted": False}

# Orchestrator and chatbot still alive; agent_two's KB untouched
r = requests.get(f"{BASE}/api/orchestrations/{orchestrator_id}", headers=SVC_H)
assert r.status_code == 200, "orchestrator should still exist"
print("orchestrator survives with 1 remaining entity:", len(r.json()["entities"]))
assert len(r.json()["entities"]) == 1

r = requests.get(f"{BASE}/api/knowledge-bases/{kb_two_id}", headers=SVC_H)
assert r.status_code == 200, "surviving agent's KB must be untouched"
print("surviving agent's KB confirmed intact")

r = requests.get(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
assert r.status_code == 200 and len(r.json()["agents"]) == 1
print("chatbot still functions with the remaining agent")

# --- Branch 2: single-agent chatbot, delete its one agent -> whole chatbot gone ---
r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task5 Single Chatbot", "agent_name": "Task5 Solo Agent", "role_description": "Handles everything."
})
solo_chatbot_id = r.json()["chatbot"]["id"]
solo_orchestrator_id = r.json()["chatbot"]["orchestrator_id"]
solo_agent_id = r.json()["agent"]["agent_id"]

r = requests.delete(f"{APP}/chatbots/{solo_chatbot_id}/agents/{solo_agent_id}", headers={"Authorization": f"Bearer {token_a}"})
print("delete solo agent (last one):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == {"deleted": True, "chatbot_deleted": True}

# Independently verify via Powabase's OWN API that the orchestrator is actually gone
r = requests.get(f"{BASE}/api/orchestrations/{solo_orchestrator_id}", headers=SVC_H)
assert r.status_code == 404, f"expected orchestrator gone (404), got {r.status_code}: {r.text}"
print("CONFIRMED via Powabase API: orchestrator is actually deleted, not just our DB row")

r = requests.get(f"{APP}/chatbots/{solo_chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
assert r.status_code == 403, "chatbot row should be gone -> RLS-scoped lookup finds nothing -> 403"
print("chatbot row confirmed gone")

print("\nOK: agent deletion (both branches) + cross-user + orphan-orchestrator prevention all verified")
EOF
```

Expected: `OK: agent deletion (both branches) + cross-user + orphan-orchestrator prevention all verified`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: add DELETE /chatbots/{id}/agents/{agent_id}, cascading the whole chatbot when the last agent is removed"
```

---

### Task 6: `DELETE /chatbots/{id}` — full chatbot deletion

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `get_chatbot_entry`, `list_chatbot_agent_rows`, `delete_orchestration`, `delete_knowledge_base`, `delete_agent`, `delete_agent_registry_row`, `delete_chatbot_row` (all Task 2/3/5).
- Produces: `DELETE /chatbots/{chatbot_id}` → `{"deleted": true, "agents_deleted": <int>}`.

- [ ] **Step 1: Add the route**

Append to `app/routes/chatbots.py`:

```python
@router.delete("/{chatbot_id}")
def delete_chatbot_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    agent_rows, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_rows)

    _, sc = delete_orchestration(orchestrator_id)
    if sc >= 400 and sc != 404:
        raise HTTPException(status_code=sc, detail="Failed to delete orchestrator")

    for row in agent_rows:
        kb_id = row.get("kb_id")
        if kb_id:
            _, sc = delete_knowledge_base(kb_id)
            if sc >= 400:
                raise HTTPException(status_code=sc, detail=f"Failed to delete knowledge base for agent {row['agent_id']}")

        _, sc = delete_agent(row["agent_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete agent {row['agent_id']}")

        _, sc = delete_agent_registry_row(user.access_token, row["agent_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete registry row for agent {row['agent_id']}")

    _, sc = delete_chatbot_row(user.access_token, chatbot_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete chatbot row")

    return {"deleted": True, "agents_deleted": len(agent_rows)}
```

- [ ] **Step 2: Restart the server and verify full deletion with multiple agents, checking every KB is actually gone via Powabase's API, plus cross-user protection**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"
SVC_H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task6-user-a@example.com")
token_b = get_token("task6-user-b@example.com")

r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task6 Chatbot", "agent_name": "Task6 Agent One", "role_description": "Handles topic one."
})
chatbot_id = r.json()["chatbot"]["id"]
orchestrator_id = r.json()["chatbot"]["orchestrator_id"]
kb_one_id = r.json()["agent"]["kb_id"]

r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task6 Agent Two", "role_description": "Handles topic two."
})
kb_two_id = r.json()["kb_id"]

# Cross-user: user B cannot delete user A's chatbot
r = requests.delete(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_b}"})
assert r.status_code == 403, (r.status_code, r.text)
print("cross-user chatbot delete blocked with 403 as expected")

r = requests.delete(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
print("full chatbot delete:", r.status_code, r.json())
assert r.status_code == 200 and r.json() == {"deleted": True, "agents_deleted": 2}

# Independently verify via Powabase's OWN API: orchestrator gone, both KBs gone
r = requests.get(f"{BASE}/api/orchestrations/{orchestrator_id}", headers=SVC_H)
assert r.status_code == 404, f"expected orchestrator gone, got {r.status_code}"
print("CONFIRMED: orchestrator gone")

r = requests.get(f"{BASE}/api/knowledge-bases/{kb_one_id}", headers=SVC_H)
assert r.status_code == 404, f"expected kb_one gone, got {r.status_code}"
print("CONFIRMED: agent one's KB gone")

r = requests.get(f"{BASE}/api/knowledge-bases/{kb_two_id}", headers=SVC_H)
assert r.status_code == 404, f"expected kb_two gone, got {r.status_code}"
print("CONFIRMED: agent two's KB gone")

r = requests.get(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
assert r.status_code == 403
print("chatbot row confirmed gone")

print("\nOK: full chatbot deletion verified end-to-end against Powabase's own API")
EOF
```

Expected: `OK: full chatbot deletion verified end-to-end against Powabase's own API`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: add DELETE /chatbots/{id} for full chatbot teardown"
```

---

### Task 7: `POST /chatbots/{id}/chat` — chat with the orchestrator

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `get_chatbot_entry`, `get_chatbot_session_entry`, `insert_chatbot_session_row`, `run_orchestration` (Task 2/3).
- Produces: `POST /chatbots/{chatbot_id}/chat` request body `{message, session_id?, label?}`, response `{"content", "session_id", "usage"}` — same shape as the existing single-agent `/chat`, minus any context-injection fields (none exist there either).

- [ ] **Step 1: Add the route**

Add `get_chatbot_session_entry`, `insert_chatbot_session_row`, `run_orchestration` to the imports at the top of `app/routes/chatbots.py`, then append:

```python
class ChatbotChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    label: str | None = None


@router.post("/{chatbot_id}/chat")
def chatbot_chat_route(chatbot_id: str, req: ChatbotChatRequest, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    if req.session_id:
        session_rows, status_code = get_chatbot_session_entry(user.access_token, chatbot_id, req.session_id)
        if status_code >= 400 or not session_rows:
            raise HTTPException(status_code=403, detail="Session not found or not owned by this user for this chatbot")

    data, status_code = run_orchestration(orchestrator_id, req.message, session_id=req.session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    if not req.session_id:
        _, status_code = insert_chatbot_session_row(user.access_token, user.id, chatbot_id, data["session_id"], req.label)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail="Failed to save chat session")

    return data
```

- [ ] **Step 2: Restart the server and verify the two-fabricated-fact scenario, multi-turn continuity, and cross-user chat blocking**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import time
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"
SVC_H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

def wait_for_kb_indexed(kb_id, source_id, timeout=90):
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}/sources", headers=SVC_H)
        items = r.json()["items"]
        match = next((i for i in items if i["source_id"] == source_id), None)
        if match and match["index_status"] == "indexed":
            return
        time.sleep(2)
        elapsed += 2
    raise AssertionError("indexing timed out")

def ingest(token, agent_id, content, filename):
    r = requests.post(
        f"{APP}/ingest/file",
        headers={"Authorization": f"Bearer {token}"},
        data={"agent_id": agent_id},
        files={"file": (filename, content)},
    )
    r.raise_for_status()
    return r.json()

token_a = get_token("task7-user-a@example.com")
token_b = get_token("task7-user-b@example.com")

r = requests.post(f"{APP}/chatbots", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task7 Chatbot", "agent_name": "Task7 WiFi Agent",
    "role_description": "Answers questions about office WiFi access and passwords.",
    "system_prompt": "Use your knowledge base to answer WiFi questions.",
})
chatbot_id = r.json()["chatbot"]["id"]
agent_wifi_id = r.json()["agent"]["agent_id"]

r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_a}"}, json={
    "name": "Task7 Parking Agent",
    "role_description": "Answers questions about parking garage access codes.",
    "system_prompt": "Use your knowledge base to answer parking questions.",
})
agent_parking_id = r.json()["agent_id"]

wifi_doc = ingest(token_a, agent_wifi_id, b"COMPANY FACT: the WiFi password is ZEBRA-CLOUD-3.", "wifi.txt")
wait_for_kb_indexed(wifi_doc["knowledge_base_id"], wifi_doc["source_id"])

parking_doc = ingest(token_a, agent_parking_id, b"COMPANY FACT: the parking code is 5591.", "parking.txt")
wait_for_kb_indexed(parking_doc["knowledge_base_id"], parking_doc["source_id"])

r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={
    "message": "What is the WiFi password and the parking code? Give me both."
})
assert r.status_code == 200, (r.status_code, r.text)
content = r.json()["content"]
session_id = r.json()["session_id"]
print("combined chat:", content)
assert "ZEBRA-CLOUD-3" in content and "5591" in content, "chatbot must draw on both subagents' isolated KBs"
print("CONFIRMED: chatbot correctly drew on both subagents")

# multi-turn continuity via session_id
r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers={"Authorization": f"Bearer {token_a}"}, json={
    "message": "What did I just ask you?", "session_id": session_id
})
assert r.status_code == 200
print("multi-turn recall:", r.json()["content"])

# Cross-user: user B cannot chat with user A's chatbot
r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers={"Authorization": f"Bearer {token_b}"}, json={"message": "hi"})
assert r.status_code == 403
print("cross-user chat blocked with 403 as expected")

# Cross-user: user B cannot reuse user A's session_id even against a chatbot B doesn't own (already covered), but also confirm B can't hijack the session_id shape generally -- not owning the chatbot is sufficient (already asserted above).

print("\nOK: chatbot chat verified -- multi-agent facts, multi-turn, cross-user blocked")
EOF
```

Expected: `OK: chatbot chat verified -- multi-agent facts, multi-turn, cross-user blocked`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: add POST /chatbots/{id}/chat to converse with the orchestrator"
```

---

### Task 8: End-to-end adversarial sanity script

**Files:**
- Create: `scripts/sanity_check_chatbots.py`

**Interfaces:**
- Consumes: the full running app (`/chatbots*`) plus direct Powabase API calls (service key) to independently verify orchestrator/KB deletion, matching the style of `scripts/sanity_check.py` and `scripts/sanity_check_session_kb.py`.

- [ ] **Step 1: Write the script**

```python
import time

import requests

from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"
SVC_H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}

USER_A = {"email": "sanity-chatbot-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-chatbot-user-b@example.com", "password": "SanityTest123!"}


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


def create_chatbot(token, name, agent_name, role_description):
    r = requests.post(
        f"{APP}/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "agent_name": agent_name, "role_description": role_description},
    )
    r.raise_for_status()
    return r.json()


def add_agent(token, chatbot_id, name, role_description):
    r = requests.post(
        f"{APP}/chatbots/{chatbot_id}/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "role_description": role_description},
    )
    r.raise_for_status()
    return r.json()


def ingest(token, agent_id, content, filename):
    r = requests.post(
        f"{APP}/ingest/file",
        headers={"Authorization": f"Bearer {token}"},
        data={"agent_id": agent_id},
        files={"file": (filename, content)},
    )
    r.raise_for_status()
    return r.json()


def wait_for_kb_indexed(kb_id, source_id, timeout=90):
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}/sources", headers=SVC_H)
        r.raise_for_status()
        items = r.json()["items"]
        match = next((i for i in items if i["source_id"] == source_id), None)
        if match and match["index_status"] == "indexed":
            return
        if match and match["index_status"] == "failed":
            raise AssertionError(f"indexing failed: {match}")
        time.sleep(2)
        elapsed += 2
    raise AssertionError(f"timed out waiting for source {source_id} to index into kb {kb_id}")


def chat(token, chatbot_id, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    return requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    # --- 1. Two-subagent chatbot, each with its own fabricated fact ---
    result = create_chatbot(token_a, "Sanity Chatbot", "Sanity WiFi Agent", "Answers office WiFi questions.")
    chatbot_id = result["chatbot"]["id"]
    orchestrator_id = result["chatbot"]["orchestrator_id"]
    agent_wifi = result["agent"]

    agent_parking = add_agent(token_a, chatbot_id, "Sanity Parking Agent", "Answers parking garage questions.")

    doc_wifi = ingest(token_a, agent_wifi["agent_id"], b"OFFICE FACT: the WiFi password is TRIDENT-OWL-88.", "wifi.txt")
    wait_for_kb_indexed(agent_wifi["kb_id"], doc_wifi["source_id"])

    doc_parking = ingest(token_a, agent_parking["agent_id"], b"OFFICE FACT: the parking code is 3307.", "parking.txt")
    wait_for_kb_indexed(agent_parking["kb_id"], doc_parking["source_id"])

    r = chat(token_a, chatbot_id, "What is the WiFi password and the parking code? Give me both, verbatim.")
    assert r.status_code == 200, r.text
    content = r.json()["content"]
    session_id = r.json()["session_id"]
    assert "TRIDENT-OWL-88" in content, f"missing wifi fact: {content}"
    assert "3307" in content, f"missing parking fact: {content}"
    print("chatbot correctly drew on both subagents' isolated KBs:", content)

    # --- 2. Delete one of two subagents; the other survives untouched ---
    r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_parking['agent_id']}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json()["chatbot_deleted"] is False, r.text
    print("deleted parking agent, chatbot survives:", r.json())

    rk = requests.get(f"{BASE}/api/knowledge-bases/{agent_wifi['kb_id']}", headers=SVC_H)
    assert rk.status_code == 200, "surviving agent's KB must be untouched"
    print("surviving agent's KB confirmed intact via Powabase API")

    r = chat(token_a, chatbot_id, "What is the WiFi password?", session_id=session_id)
    assert r.status_code == 200 and "TRIDENT-OWL-88" in r.json()["content"], r.text
    print("chatbot still functions correctly with the remaining agent:", r.json()["content"])

    r = requests.get(f"{BASE}/api/orchestrations/{orchestrator_id}", headers=SVC_H)
    assert r.status_code == 200 and len(r.json()["entities"]) == 1
    print("orchestrator confirmed still alive with exactly 1 entity")

    # --- 3. Single-agent chatbot: delete its one agent -> orchestrator actually gone ---
    solo = create_chatbot(token_a, "Sanity Solo Chatbot", "Sanity Solo Agent", "Handles everything.")
    solo_chatbot_id = solo["chatbot"]["id"]
    solo_orchestrator_id = solo["chatbot"]["orchestrator_id"]
    solo_agent_id = solo["agent"]["agent_id"]

    r = requests.delete(f"{APP}/chatbots/{solo_chatbot_id}/agents/{solo_agent_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json() == {"deleted": True, "chatbot_deleted": True}, r.text
    print("deleted the only agent on a single-agent chatbot:", r.json())

    r = requests.get(f"{BASE}/api/orchestrations/{solo_orchestrator_id}", headers=SVC_H)
    assert r.status_code == 404, f"orchestrator must be actually gone, got {r.status_code}"
    print("CONFIRMED via Powabase API: no orphaned orchestrator survives single-agent deletion")

    # --- 4. Full chatbot deletion with multiple agents: verify every KB is gone via Powabase's API ---
    multi = create_chatbot(token_a, "Sanity Multi Chatbot", "Sanity Multi Agent One", "Handles topic one.")
    multi_chatbot_id = multi["chatbot"]["id"]
    multi_orchestrator_id = multi["chatbot"]["orchestrator_id"]
    kb_one = multi["agent"]["kb_id"]

    agent_two = add_agent(token_a, multi_chatbot_id, "Sanity Multi Agent Two", "Handles topic two.")
    kb_two = agent_two["kb_id"]

    r = requests.delete(f"{APP}/chatbots/{multi_chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json() == {"deleted": True, "agents_deleted": 2}, r.text
    print("full chatbot deletion:", r.json())

    for kb_id, label in [(kb_one, "one"), (kb_two, "two")]:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}", headers=SVC_H)
        assert r.status_code == 404, f"kb {label} must be gone, got {r.status_code}"
    print("CONFIRMED via Powabase API: every subagent KB is actually gone after full deletion")

    r = requests.get(f"{BASE}/api/orchestrations/{multi_orchestrator_id}", headers=SVC_H)
    assert r.status_code == 404
    print("CONFIRMED: orchestrator gone after full deletion")

    # --- 5. Cross-user: user B cannot touch user A's remaining chatbot ---
    r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_b}"}, json={
        "name": "hostile", "role_description": "hostile"
    })
    assert r.status_code == 403
    print("cross-user add-agent blocked")

    r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_wifi['agent_id']}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user remove-agent blocked")

    r = chat(token_b, chatbot_id, "hi")
    assert r.status_code == 403
    print("cross-user chat blocked")

    r = requests.delete(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user full delete blocked")

    print("\nALL CHATBOT ORCHESTRATION SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Restart the server and run the sanity check**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
.venv/bin/python3 scripts/sanity_check_chatbots.py
```

Expected: every `assert` passes and the script prints `ALL CHATBOT ORCHESTRATION SANITY CHECKS PASSED`.

- [ ] **Step 3: Stop the background server**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null
```

- [ ] **Step 4: Commit**

```bash
git add scripts/sanity_check_chatbots.py
git commit -m "test: add end-to-end adversarial sanity check for multi-agent chatbots"
```

---

## Self-review notes

- **Spec coverage:** mentor requirement #1 (multiple agents + deletion soundness) → Tasks 4/5/6/8. Requirement #2 (no orphaned orchestrator) → Task 5's `len(all_agents) == 1` branch, verified against Powabase's own API in Task 5 Step 2 and Task 8. Requirement #3 (WE manage the orchestrator prompt, general strategy) → `ORCHESTRATOR_SYSTEM_PROMPT` constant in Task 3, never exposed as a request field; `strategy: "supervisor"` fixed in `create_orchestration`. Architecture sketch's `chatbots`/`agents_registry.chatbot_id` → Task 1. All 7 routes from the sketch → Tasks 3/4/5/6/7. Testing checklist (2 subagents with distinct facts, delete one, single-agent cascade verified live, full deletion verified live, cross-user blocked on every mutating route) → Task 8, plus inline verification in each task.
- **Deviation from the original sketch, with research justification:** `POST /chatbots/{id}/chat` does not build a `context_override` (the sketch said "reuse as much... as findings allow" — findings showed `context_override` is a no-op on orchestration runs, confirmed live in the pre-plan research). A new `chatbot_sessions` table (not in the original sketch) was added because the sketch's "session/token/history logic" reuse still needs *some* row to check session ownership against for a returning `session_id` — `chat_sessions` couldn't be reused directly since it's keyed to `agent_id` not `chatbot_id`/orchestrator, and it carries `kb_id`/`session_token` columns that have no meaning at the orchestrator level.
- **Placeholder scan:** none — every step has complete code and concrete expected output, all drawn from what was actually observed running against the live project.
- **Type/name consistency:** `agents_registry` rows returned by chatbot routes always carry `agent_id`, `kb_id`, `name`, `chatbot_id`, `orchestration_entity_id` — used identically in Tasks 3/4/5/6/8. `run_orchestration`'s return shape (`{"content", "session_id", "usage"}`) matches what Task 7's route returns directly and what Task 8's script asserts on.
