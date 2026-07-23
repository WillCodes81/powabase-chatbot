# Per-User Agent Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the shared hardcoded `KNOWLEDGE_BASE_ID`/`AGENT_ID` in the Powabase RAG chatbot backend with full per-user isolation — every signed-in user can create their own agents, each with its own dedicated knowledge base, and can only ingest into or chat with agents they own.

**Architecture:** A FastAPI dependency (`get_current_user`) validates the caller's bearer token against Powabase's GoTrue (`GET /auth/v1/user`) and returns both the user's id and their raw access token. A new Postgres table `public.agents_registry` (RLS-protected, one row per agent a user owns) is the source of truth for ownership. All Postgres/PostgREST calls against `agents_registry` are made with `apikey: <anon>` + `Authorization: Bearer <user's own access token>` — never the service-role key — so Postgres RLS itself enforces per-user scoping (defense in depth: even a route that forgets to filter cannot see another user's rows). All calls to the Powabase AI surface (`/api/*`: creating KBs/agents, uploading sources, running agents) keep using the service-role key, matching the existing `powabase_client.py` style.

**Tech Stack:** FastAPI 0.139, Pydantic 2.13, `requests`, Powabase (Supabase-compatible BaaS: GoTrue auth + PostgREST + the `/api/*` AI surface).

## Global Constraints

- Keep the `(data, status_code)` tuple return pattern for every function in `app/powabase_client.py` — every caller checks `status_code >= 400` and raises `HTTPException(status_code=status_code, detail=data)`, exactly like the existing `signup`/`signin`/`upload_source` functions.
- Every request to `/api/*` uses the **Service Role key** for both `apikey` and `Authorization` headers (existing pattern).
- Every request to `/rest/v1/agents_registry` uses `apikey: <Anon key>` + `Authorization: Bearer <the calling user's own access token>` — **not** the service key — so RLS actually filters the rows. This is why `AuthedUser` (Task 1) carries `access_token`, not just `id`.
- `get_current_user` (Task 1) is a dependency on every route below except `POST /auth/signup` and `POST /auth/signin`.
- No test framework is installed in this project (no `pytest`, no `tests/` dir). Verification steps in this plan use direct `requests` calls against a locally running `uvicorn` server (or, where no server is needed yet, direct Python function calls) — don't introduce `pytest` as part of this plan.
- Live API shapes referenced below (`GET /auth/v1/user`, KB create, agent create, KB-link, PostgREST) were verified against the live project on 2026-07-23 — see inline response examples in each task.

---

### Task 1: Auth dependency

**Files:**
- Modify: `app/powabase_client.py` — add `get_authenticated_user`
- Create: `app/deps.py`

**Interfaces:**
- Produces: `app.deps.AuthedUser` (dataclass: `id: str`, `access_token: str`) and `app.deps.get_current_user` (FastAPI dependency, reads the `Authorization` header, raises `HTTPException(401)` on missing/invalid token, otherwise returns `AuthedUser`). Every later task imports both from `app.deps`.
- Produces: `app.powabase_client.get_authenticated_user(access_token: str) -> tuple[dict, int]` — calls `GET /auth/v1/user`. On success (200) the dict has an `"id"` key (the user's UUID). On failure (401/403) the dict is GoTrue's error envelope (`{"code", "error_code", "msg"}`) — callers only need the status code.

- [ ] **Step 1: Add `get_authenticated_user` to `app/powabase_client.py`**

Append this function (same header/style as `signup`/`signin` above it):

```python
def get_authenticated_user(access_token: str) -> dict:
    response = requests.get(
        f"{settings.powabase_url}/auth/v1/user",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
    )
    return response.json(), response.status_code
```

- [ ] **Step 2: Create `app/deps.py`**

```python
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.powabase_client import get_authenticated_user


@dataclass
class AuthedUser:
    id: str
    access_token: str


def get_current_user(authorization: str | None = Header(default=None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ")
    data, status_code = get_authenticated_user(token)
    if status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return AuthedUser(id=data["id"], access_token=token)
```

- [ ] **Step 3: Verify with a real token**

`get_current_user`'s `authorization` parameter has a `Header(default=None)` default object, but calling the function directly with a positional string bypasses FastAPI's DI and just runs it as plain Python — so this is testable without a running server.

Run:

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings
from app.deps import get_current_user
from fastapi import HTTPException

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
creds = {"email": "task1-verify@example.com", "password": "TestPass123!"}

r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

user = get_current_user(f"Bearer {token}")
assert user.id and user.access_token == token
print("OK valid token ->", user.id)

try:
    get_current_user("Bearer not.a.valid.token")
    raise SystemExit("FAIL: expected HTTPException")
except HTTPException as e:
    assert e.status_code == 401
    print("OK invalid token -> 401")

try:
    get_current_user(None)
    raise SystemExit("FAIL: expected HTTPException")
except HTTPException as e:
    assert e.status_code == 401
    print("OK missing header -> 401")
EOF
```

Expected output:
```
OK valid token -> <some-uuid>
OK invalid token -> 401
OK missing header -> 401
```

- [ ] **Step 4: Commit**

```bash
git add app/powabase_client.py app/deps.py
git commit -m "feat: add auth dependency validating bearer tokens against GoTrue"
```

---

### Task 2: `agents_registry` table with RLS (manual Studio step)

This task needs DDL access, which this project's `.env` doesn't have credentials for (no Database URL). Per user decision, this is a manual step run by the user in the Powabase Studio SQL editor — not an automated migration.

**Files:** none (pure database change, done outside this repo)

**Interfaces:**
- Produces: `public.agents_registry` table with columns `id uuid`, `user_id uuid`, `agent_id uuid`, `kb_id uuid`, `name text`, `created_at timestamptz`, RLS enabled, 4 policies (own select/insert/update/delete). Task 3 onward reads/writes this table via `/rest/v1/agents_registry`.

- [ ] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run:

```sql
create table public.agents_registry (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users,
  agent_id uuid not null,
  kb_id uuid not null,
  name text not null,
  created_at timestamptz not null default now()
);

alter table public.agents_registry enable row level security;

create policy "agents_registry_select_own" on public.agents_registry
  for select to authenticated using (user_id = auth.uid());

create policy "agents_registry_insert_own" on public.agents_registry
  for insert to authenticated with check (user_id = auth.uid());

create policy "agents_registry_update_own" on public.agents_registry
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "agents_registry_delete_own" on public.agents_registry
  for delete to authenticated using (user_id = auth.uid());

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2.

- [ ] **Step 2: Verify the table exists and RLS actually blocks cross-role access**

Run:

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

fake_row = {
    "user_id": "00000000-0000-0000-0000-000000000000",
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "kb_id": "00000000-0000-0000-0000-000000000002",
    "name": "rls-test-row",
}

r = requests.post(
    f"{BASE}/rest/v1/agents_registry",
    headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"},
    json=fake_row,
)
print("insert via service key:", r.status_code)
assert r.status_code in (200, 201), r.text

r = requests.get(f"{BASE}/rest/v1/agents_registry", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"name": "eq.rls-test-row"})
print("read via service key (bypasses RLS, should see 1 row):", r.status_code, len(r.json()))
assert len(r.json()) == 1

r = requests.get(f"{BASE}/rest/v1/agents_registry", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"name": "eq.rls-test-row"})
print("read via anon key, no user token (RLS should block, expect 0 rows):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

r = requests.delete(f"{BASE}/rest/v1/agents_registry", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"name": "eq.rls-test-row"})
print("cleanup:", r.status_code)

print("\nTABLE + RLS VERIFIED")
EOF
```

Expected output ends with `TABLE + RLS VERIFIED`. If the first insert 404s, the schema cache hasn't reloaded — re-run `notify pgrst, 'reload schema';` and retry.

- [ ] **Step 3: Commit the plan's record of this manual step**

No code changed in this task, so there's nothing to commit. Proceed to Task 3.

---

### Task 3: `POST /agents` — create an agent + its own isolated KB

**Files:**
- Modify: `app/powabase_client.py` — add `create_knowledge_base`, `create_agent`, `link_agent_knowledge_base`, `insert_agent_registry_row`
- Create: `app/routes/agents.py`
- Modify: `app/main.py` — register the new router

**Interfaces:**
- Consumes: `app.deps.AuthedUser`, `app.deps.get_current_user` (Task 1).
- Produces: `app.powabase_client.create_knowledge_base(name: str) -> tuple[dict, int]`, `create_agent(name: str, system_prompt: str | None) -> tuple[dict, int]`, `link_agent_knowledge_base(agent_id: str, kb_id: str) -> tuple[dict, int]`, `insert_agent_registry_row(access_token: str, user_id: str, agent_id: str, kb_id: str, name: str) -> tuple[dict, int]` (single dict, not a list — unwraps PostgREST's `return=representation` array). `POST /agents` route, response body `{id, user_id, agent_id, kb_id, name, created_at}` (the registry row). Task 5/6 use `agent_id` from this response.

- [ ] **Step 1: Add KB/agent/registry-insert functions to `app/powabase_client.py`**

Append:

```python
def create_knowledge_base(name: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/knowledge-bases",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"name": name},
    )
    return response.json(), response.status_code


def create_agent(name: str, system_prompt: str | None) -> dict:
    body = {"name": name}
    if system_prompt:
        body["system_prompt"] = system_prompt
    response = requests.post(
        f"{settings.powabase_url}/api/agents",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    return response.json(), response.status_code


def link_agent_knowledge_base(agent_id: str, kb_id: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/agents/{agent_id}/knowledge-bases",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"knowledge_base_id": kb_id},
    )
    return response.json(), response.status_code


def insert_agent_registry_row(access_token: str, user_id: str, agent_id: str, kb_id: str, name: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={"user_id": user_id, "agent_id": agent_id, "kb_id": kb_id, "name": name},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code
```

- [ ] **Step 2: Create `app/routes/agents.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    create_agent,
    create_knowledge_base,
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

    registry_row, status_code = insert_agent_registry_row(user.access_token, user.id, agent_id, kb_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)
    return registry_row
```

Note: this imports `list_agent_registry_rows`, which doesn't exist until Task 4. That's expected — Task 4 adds it right after. If running Task 3 in isolation, stub it out or do Task 4's Step 1 first.

- [ ] **Step 3: Register the router in `app/main.py`**

```python
from fastapi import FastAPI

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.ingest import router as ingest_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")
    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    return app


app = create_app()
```

- [ ] **Step 4: Start the server and verify `POST /agents`**

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
creds = {"email": "task3-verify@example.com", "password": "TestPass123!"}

r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post("http://127.0.0.1:8000/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "task3-agent"})
print(r.status_code, r.json())
assert r.status_code == 200
body = r.json()
assert body["name"] == "task3-agent"
assert body["agent_id"] and body["kb_id"]
print("OK: agent + KB created, registry row returned")
EOF
```

Expected: `OK: agent + KB created, registry row returned`.

- [ ] **Step 5: Commit**

```bash
git add app/powabase_client.py app/routes/agents.py app/main.py
git commit -m "feat: add POST /agents to create a per-user agent with its own KB"
```

---

### Task 4: `GET /agents` — list a user's own agents

**Files:**
- Modify: `app/powabase_client.py` — add `list_agent_registry_rows`
- Modify: `app/routes/agents.py` — add the list route (the import already added in Task 3 Step 2)

**Interfaces:**
- Produces: `app.powabase_client.list_agent_registry_rows(access_token: str) -> tuple[list, int]`. `GET /agents` route, response is a bare JSON array of `{id, agent_id, name, created_at}`.

- [ ] **Step 1: Add `list_agent_registry_rows` to `app/powabase_client.py`**

```python
def list_agent_registry_rows(access_token: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"select": "id,agent_id,name,created_at", "order": "created_at.desc"},
    )
    return response.json(), response.status_code
```

- [ ] **Step 2: Add the list route to `app/routes/agents.py`**

Append to the file (the `list_agent_registry_rows` import is already there from Task 3 Step 2):

```python
@router.get("")
def list_agents_route(user: AuthedUser = Depends(get_current_user)):
    data, status_code = list_agent_registry_rows(user.access_token)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

- [ ] **Step 3: Restart the server and verify**

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
creds = {"email": "task3-verify@example.com", "password": "TestPass123!"}  # reuse Task 3's user, already has 1 agent

r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.get("http://127.0.0.1:8000/agents", headers={"Authorization": f"Bearer {token}"})
print(r.status_code, r.json())
assert r.status_code == 200
assert isinstance(r.json(), list) and len(r.json()) >= 1
assert set(r.json()[0].keys()) == {"id", "agent_id", "name", "created_at"}
print("OK: list returns this user's agents only")
EOF
```

Expected: `OK: list returns this user's agents only`.

- [ ] **Step 4: Commit**

```bash
git add app/powabase_client.py app/routes/agents.py
git commit -m "feat: add GET /agents to list a user's own agents"
```

---

### Task 5: Update `POST /ingest/file` for per-agent ownership

**Files:**
- Modify: `app/powabase_client.py` — add `get_agent_registry_entry`
- Modify: `app/routes/ingest.py` — require auth, accept `agent_id`, 403 on non-owned agent, drop `KNOWLEDGE_BASE_ID`

**Interfaces:**
- Consumes: `app.deps.AuthedUser`, `get_current_user`.
- Produces: `app.powabase_client.get_agent_registry_entry(access_token: str, agent_id: str) -> tuple[list, int]` — returns a list of `{"kb_id": ...}` (0 or 1 rows; RLS + the `agent_id` filter mean a non-empty result implies both "exists" and "owned by this user"). Task 6 reuses this same function.

- [ ] **Step 1: Add `get_agent_registry_entry` to `app/powabase_client.py`**

```python
def get_agent_registry_entry(access_token: str, agent_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}", "select": "kb_id"},
    )
    return response.json(), response.status_code
```

- [ ] **Step 2: Rewrite `app/routes/ingest.py`**

```python
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import add_source_to_kb, get_agent_registry_entry, get_source, upload_source

router = APIRouter(prefix="/ingest", tags=["ingest"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


@router.post("/file")
def ingest_file_route(
    file: UploadFile = File(...),
    agent_id_form: str | None = Form(default=None, alias="agent_id"),
    agent_id_query: str | None = Query(default=None, alias="agent_id"),
    user: AuthedUser = Depends(get_current_user),
):
    agent_id = agent_id_form or agent_id_query
    if not agent_id:
        raise HTTPException(status_code=422, detail="agent_id is required (form field or query param)")

    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")
    kb_id = registry_rows[0]["kb_id"]

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
            detail=f"Source extraction ended in status '{extraction_status}', cannot index",
        )

    data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

This removes the `KNOWLEDGE_BASE_ID` module-level constant entirely.

- [ ] **Step 3: Restart the server and verify both the happy path and the ownership check**

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

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task5-user-a@example.com")
token_b = get_token("task5-user-b@example.com")

r = requests.post("http://127.0.0.1:8000/agents", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "task5-agent-a"})
agent_a_id = r.json()["agent_id"]

# owner uploads successfully
r = requests.post(
    "http://127.0.0.1:8000/ingest/file",
    headers={"Authorization": f"Bearer {token_a}"},
    data={"agent_id": agent_a_id},
    files={"file": ("task5-doc.txt", b"hello from task 5")},
)
print("owner ingest:", r.status_code, r.text[:200])
assert r.status_code < 400

# non-owner is forbidden
r = requests.post(
    "http://127.0.0.1:8000/ingest/file",
    headers={"Authorization": f"Bearer {token_b}"},
    data={"agent_id": agent_a_id},
    files={"file": ("task5-doc2.txt", b"should be blocked")},
)
print("non-owner ingest:", r.status_code, r.text[:200])
assert r.status_code == 403

print("OK: ingest ownership check works")
EOF
```

Expected: `OK: ingest ownership check works` (owner ingest may take ~10-20s while extraction polls).

- [ ] **Step 4: Commit**

```bash
git add app/powabase_client.py app/routes/ingest.py
git commit -m "feat: require auth and agent ownership on POST /ingest/file"
```

---

### Task 6: Update `POST /chat` for per-agent ownership

**Files:**
- Modify: `app/routes/chat.py` — require auth, accept `agent_id` in body, 403 on non-owned agent, drop `AGENT_ID`

**Interfaces:**
- Consumes: `app.deps.AuthedUser`, `get_current_user`, `app.powabase_client.get_agent_registry_entry` (Task 5).

- [ ] **Step 1: Rewrite `app/routes/chat.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import get_agent_registry_entry, run_agent

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    agent_id: str
    message: str


@router.post("/chat")
def chat_route(req: ChatRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, req.agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    data, status_code = run_agent(req.agent_id, req.message)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

This removes the `AGENT_ID` module-level constant entirely.

- [ ] **Step 2: Restart the server and verify both the happy path and the ownership check**

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

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"]

token_a = get_token("task5-user-a@example.com")  # reuse Task 5's user, already owns task5-agent-a
token_b = get_token("task5-user-b@example.com")

r = requests.get("http://127.0.0.1:8000/agents", headers={"Authorization": f"Bearer {token_a}"})
agent_a_id = next(a["agent_id"] for a in r.json() if a["name"] == "task5-agent-a")

# owner can chat
r = requests.post("http://127.0.0.1:8000/chat", headers={"Authorization": f"Bearer {token_a}"}, json={"agent_id": agent_a_id, "message": "hello"})
print("owner chat:", r.status_code, str(r.json())[:200])
assert r.status_code == 200

# non-owner is forbidden
r = requests.post("http://127.0.0.1:8000/chat", headers={"Authorization": f"Bearer {token_b}"}, json={"agent_id": agent_a_id, "message": "hello"})
print("non-owner chat:", r.status_code, r.text[:200])
assert r.status_code == 403

print("OK: chat ownership check works")
EOF
```

Expected: `OK: chat ownership check works`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chat.py
git commit -m "feat: require auth and agent ownership on POST /chat"
```

---

### Task 7: Sanity test — two-user end-to-end isolation

**Files:**
- Create: `scripts/sanity_check.py`

**Interfaces:**
- Consumes: the full running app (`/auth/signup` or `/auth/signin`, `/agents`, `/ingest/file`, `/chat`) via HTTP against `http://127.0.0.1:8000`.

- [ ] **Step 1: Create `scripts/sanity_check.py`**

```python
import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-user-b@example.com", "password": "SanityTest123!"}

DOC_A = (b"The secret code for Project Aurora is BLUE-42.", "docA.txt")
DOC_B = (b"The secret code for Project Titan is RED-99.", "docB.txt")


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


def ingest(token, agent_id, file_bytes, filename):
    return requests.post(
        f"{APP}/ingest/file",
        headers={"Authorization": f"Bearer {token}"},
        data={"agent_id": agent_id},
        files={"file": (filename, file_bytes)},
    )


def chat(token, agent_id, message):
    return requests.post(
        f"{APP}/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_id": agent_id, "message": message},
    )


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity Agent A")
    agent_b = create_agent(token_b, "Sanity Agent B")
    print("agent A:", agent_a["agent_id"])
    print("agent B:", agent_b["agent_id"])

    r = ingest(token_a, agent_a["agent_id"], *DOC_A)
    assert r.status_code < 400, f"ingest A failed: {r.status_code} {r.text}"
    print("ingest A ok")

    r = ingest(token_b, agent_b["agent_id"], *DOC_B)
    assert r.status_code < 400, f"ingest B failed: {r.status_code} {r.text}"
    print("ingest B ok")

    r = chat(token_a, agent_a["agent_id"], "What is the secret code for Project Aurora?")
    assert r.status_code == 200, f"chat A failed: {r.status_code} {r.text}"
    content_a = r.json()["content"]
    assert "BLUE-42" in content_a, f"agent A answer missing its own doc's fact: {content_a}"
    assert "RED-99" not in content_a, f"agent A leaked agent B's fact: {content_a}"
    print("chat A ok:", content_a)

    r = chat(token_b, agent_b["agent_id"], "What is the secret code for Project Titan?")
    assert r.status_code == 200, f"chat B failed: {r.status_code} {r.text}"
    content_b = r.json()["content"]
    assert "RED-99" in content_b, f"agent B answer missing its own doc's fact: {content_b}"
    assert "BLUE-42" not in content_b, f"agent B leaked agent A's fact: {content_b}"
    print("chat B ok:", content_b)

    r = chat(token_a, agent_b["agent_id"], "What is the secret code for Project Titan?")
    assert r.status_code == 403, f"expected 403 for cross-user chat, got {r.status_code} {r.text}"
    print("cross-user chat blocked with 403 as expected")

    r = ingest(token_a, agent_b["agent_id"], b"malicious content", "hack.txt")
    assert r.status_code == 403, f"expected 403 for cross-user ingest, got {r.status_code} {r.text}"
    print("cross-user ingest blocked with 403 as expected")

    print("\nALL SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Restart the server and run the sanity check**

```bash
kill %1 2>/dev/null; cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 2
.venv/bin/python3 scripts/sanity_check.py
```

Expected: the script prints each step and ends with:
```
ALL SANITY CHECKS PASSED
```

If a chat assertion fails (wrong fact appearing), check `/tmp/uvicorn.log` — the most likely cause is the KB link (Task 3 Step 1) or the `kb_id` lookup (Task 5 Step 1) pointing at the wrong knowledge base.

- [ ] **Step 3: Stop the background server**

```bash
kill %1 2>/dev/null
```

- [ ] **Step 4: Commit**

```bash
git add scripts/sanity_check.py
git commit -m "test: add two-user end-to-end agent isolation sanity check"
```

---

## Self-review notes

- **Spec coverage:** Phase 1 → Task 1. Phase 2 → Task 2. Phase 3 → Task 3. Phase 4 → Task 4. Phase 5 → Task 5. Phase 6 → Task 6. Phase 7 → Task 7. `KNOWLEDGE_BASE_ID` removed in Task 5 Step 2; `AGENT_ID` removed in Task 6 Step 1.
- **Placeholder scan:** none — every step has complete code and exact expected output.
- **Type/name consistency:** `AuthedUser.id` / `AuthedUser.access_token` used identically in Tasks 3, 4, 5, 6. `get_agent_registry_entry` return shape (`list` of `{"kb_id": ...}`) used identically in Tasks 5 and 6. `insert_agent_registry_row` return shape (single dict, list already unwrapped) matches what Task 3's route returns directly.
