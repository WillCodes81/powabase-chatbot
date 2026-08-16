# Credits, Rename, Model Selection & Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four independent features to the backend — per-user token credits with 402 enforcement on chat, rename endpoints for agents/chatbots/sessions, optional LLM model selection on agent creation, and per-user rate limiting on the two chat endpoints — plus the matching frontend UI on the existing (unmerged) `react-frontend` branch.

**Architecture:** Feature 1 adds a new `user_credits` table (lazy row creation on first use, atomic decrement via a Postgres RPC) and reuses the exact usage numbers Powabase's own run APIs report — which required live verification, since the two run functions do **not** report usage the same way (see Global Constraints). Feature 2 adds four thin `PATCH` routes that touch only our own DB columns, no Powabase API calls. Feature 3 threads an optional `model` string through the existing `create_agent()` call, verified live against this project's actual configured providers rather than an invented list. Feature 4 wraps the two chat routes in `slowapi`, keyed on the raw bearer token (not a second live auth call) to avoid doubling latency on every request. All four are independent — they can be built and reviewed in any order, but this plan sequences them 1→4 for a single linear review pass.

**Tech Stack:** FastAPI 0.139, Pydantic 2.13, `requests`, `slowapi`, Powabase (`/api/agents`, `/api/agents/runs/{id}`, `/api/orchestrations`, PostgREST `/rest/v1/*` incl. RPC), React 19 + TypeScript + Vite (frontend, on the `react-frontend` branch).

**Spec:** This plan is built directly from conversation (research findings + design approved in chat on 2026-08-16) — no separate spec file, matching this project's existing convention (see `docs/superpowers/plans/2026-08-09-chatbots-multi-agent-orchestration.md` and `2026-08-13-react-frontend.md`, both of which note the same thing).

## Global Constraints

- **`user_credits` rows are created lazily (on first need — chat or `GET /me/credits`), not on signup.** Tradeoff considered: creating the row at signup (via a Postgres trigger on `auth.users` insert, since the app never sees a "user created" webhook) guarantees every user has exactly one row from day one, but (a) needs a trigger function as extra DDL beyond what every other table in this project needs, and (b) does nothing for the users who already exist in this project today — they'd still need a one-off backfill script. Lazy creation via `ensure_user_credits_row` needs no trigger, no backfill, and naturally covers both existing and future users the first time they touch anything credit-related. The cost is that `GET /me/credits` and both chat routes each need to call `ensure_user_credits_row` instead of a plain read — a minor, already-idiomatic addition (see Task 2).
- Keep the `(data, status_code)` tuple return pattern for every function in `app/powabase_client.py`, exactly like every existing function in that file.
- `/api/*` calls use the **Service Role key** for both `apikey` and `Authorization` (existing pattern, unchanged). `/rest/v1/{table}` calls (including RPC) use `apikey: <Anon key>` + `Authorization: Bearer <the calling user's own access token>` — RLS enforces per-user scoping, same pattern as every existing table in this project.
- **Verified live on 2026-08-16, re-confirmed 2026-08-16 with a 2-subagent orchestration run: the `complete`/`orchestration_completed` event's `usage` is the only complete total — per-agent breakdowns exist but are not a substitute.** The stream also emits a `delegation_completed` event per subagent call, each carrying its own `usage` (e.g. `{"total_tokens": 70}` and `{"total_tokens": 67}` for two delegated calls in one run). Summing just those two gives 137 — but the same run's `complete` event reported `total_tokens: 1156`. The gap is the **coordinator's own LLM usage** (routing/reasoning/tool-calling), which never appears in any per-delegation event, only in the run-level aggregate. So `delegation_completed` usage is real but strictly partial; summing it would silently undercharge users by the coordinator's overhead (88% of the total in this test). The plan's design — read `usage` off the final `complete` event — was already using the one place the full, correct total exists; this is confirmed, not an estimate anywhere, and no task changes as a result of this check.
- **Verified live on 2026-08-16, critical for Feature 1:** `run_agent()`'s SSE `complete` event has **no `usage` key at all** — `event.get("usage")` is always `None` for a standalone-agent run. The real token counts only exist on the separate run record (`GET /api/agents/runs/{run_id}`), fetched via the `run_id` the `start` event carries (not currently captured — only `session_id` is). By contrast, `run_orchestration()`'s `complete` event **does** carry a populated `usage` object directly — confirmed with a real 2-agent orchestration run producing `{"prompt_tokens": 674, "completion_tokens": 34, ..., "total_tokens": 708}`. Task 2 fixes `run_agent()`; `run_orchestration()` needs no change.
- **Verified live on 2026-08-16, Feature 3:** `POST /api/agents` / `PATCH /api/agents/{id}` accept `model` as a free-form LiteLLM model ID — there is no fixed enum anywhere in the platform. This project has no BYOK provider keys configured (`GET /api/ai-provider-keys` → `[]`) but has AI-on-us for `anthropic`, `google`, `openai` (`GET /api/ai-provider-keys/platform_supported`). `gpt-4o`, `claude-sonnet-4-6`, and `gemini/gemini-2.5-flash` were each created and run end-to-end successfully on this project. Default model when omitted is `gpt-5.4-mini`. Orchestration create silently drops a top-level `model` (verified, and out of scope — only agent-level model selection was requested).
- This repo has **no `requirements.txt` or other dependency manifest** — packages are installed straight into `.venv` (confirmed: `pip list` shows only what's actually imported, no lockfile anywhere in the repo). Installing `slowapi` in Task 10 follows this same convention; don't introduce a manifest file as a side effect of this plan.
- No test framework is installed (no `pytest`, no `tests/` dir) — verification uses direct `requests` calls against a locally running `uvicorn` and the live Powabase API, matching every existing `scripts/sanity_check*.py` in this project.
- **Frontend tasks (11–13) run on the existing `react-frontend` branch**, checked out at the worktree `/home/william/powabase-chatbot/.worktrees/react-frontend` (branch `react-frontend`, currently a complete, working frontend not yet merged to `main`). Backend tasks (1–10) run on `main` in the primary checkout `/home/william/powabase-chatbot`. **For frontend manual testing, run the backend from the `main` checkout** (`cd /home/william/powabase-chatbot && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`) — it has both CORS (added in Task 10) and every new endpoint this plan adds; the `react-frontend` branch's own `app/` copy has neither. Run the frontend dev server from the worktree (`cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend && npm run dev`, default `http://localhost:5173`) pointed at that same backend via its existing `VITE_API_BASE_URL=http://127.0.0.1:8000`.
- Frontend TypeScript types are hand-written from route code (no OpenAPI schema exists) — match the exact shapes in `frontend/src/api/types.ts`.
- Frontend error responses are always FastAPI's `{"detail": ...}` shape, and `detail` is `string | Record<string, unknown> | unknown[]` — the existing `ApiError`/`describeError` pattern already handles this; new code doesn't need its own error-shape handling.

---

### Task 1: `user_credits` table + `deduct_credits` RPC (manual SQL, Studio step)

This needs DDL access, which this project's `.env` doesn't have (no Database URL) — same situation as every prior table/column change in this project's history (see Task 1 of the chatbots plan).

**Files:** none (pure database change, done outside this repo)

**Interfaces:**
- Produces: `public.user_credits` (`user_id uuid primary key references auth.users`, `tokens_remaining integer not null default 50000`, `tokens_used_total integer not null default 0`, `created_at timestamptz not null default now()`), RLS enabled, 4 owner-scoped policies (same pattern as every other table). `public.deduct_credits(p_user_id uuid, p_tokens integer) returns setof public.user_credits` — an atomic `UPDATE ... SET tokens_remaining = tokens_remaining - p_tokens, tokens_used_total = tokens_used_total + p_tokens WHERE user_id = p_user_id RETURNING *`, callable at `/rest/v1/rpc/deduct_credits`. Task 2 consumes both.

- [x] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run. (Executed 2026-08-16: the first attempt with double-quoted policy names — `"user_credits_delete_own"` etc. — errored with `syntax error at or near "for"` on the delete policy, with nothing committed; the working theory is the chat UI's markdown rendering mangled a straight quote into a smart quote on copy, swallowing a semicolon. Unquoted policy identifiers below are what actually succeeded — kept as the plan's canonical version since it's strictly more robust to future copy-paste, not just a one-off fix.)

Project → **Studio** → **SQL Editor**, paste and run:

```sql
create table public.user_credits (
  user_id uuid primary key references auth.users,
  tokens_remaining integer not null default 50000,
  tokens_used_total integer not null default 0,
  created_at timestamptz not null default now()
);

alter table public.user_credits enable row level security;

create policy user_credits_select_own on public.user_credits
  for select to authenticated using (user_id = auth.uid());

create policy user_credits_insert_own on public.user_credits
  for insert to authenticated with check (user_id = auth.uid());

create policy user_credits_update_own on public.user_credits
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy user_credits_delete_own on public.user_credits
  for delete to authenticated using (user_id = auth.uid());

create or replace function public.deduct_credits(p_user_id uuid, p_tokens integer)
returns setof public.user_credits
language sql
security invoker
set search_path = public
as $$
  update public.user_credits
  set tokens_remaining = tokens_remaining - p_tokens,
      tokens_used_total = tokens_used_total + p_tokens
  where user_id = p_user_id
  returning *;
$$;

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2. (Confirmed 2026-08-16: "success. No rows returned".)

- [x] **Step 2: Verify the table, RLS, and RPC exist and behave correctly**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

def get_token(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    return r.json()["access_token"], r.json()["user"]["id"] if "user" in r.json() else None

token, _ = get_token("task1-credits-verify@example.com")
H = {"apikey": ANON, "Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# anon (no user token) is blocked by RLS
r = requests.get(f"{BASE}/rest/v1/user_credits", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"select": "user_id", "limit": 1})
print("anon read user_credits (RLS should block -> expect [], 200):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

# authenticated user has no row yet
r = requests.get(f"{BASE}/rest/v1/user_credits", headers=H, params={"select": "*"})
print("authenticated read, no row yet:", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

# insert own row picks up defaults
r = requests.post(f"{BASE}/rest/v1/user_credits", headers={**H, "Prefer": "return=representation"}, json={"user_id": requests.get(f'{BASE}/auth/v1/user', headers={'apikey': ANON, 'Authorization': f'Bearer {token}'}).json()["id"]})
print("insert own row:", r.status_code, r.json())
assert r.status_code == 201
row = r.json()[0]
assert row["tokens_remaining"] == 50000 and row["tokens_used_total"] == 0
user_id = row["user_id"]

# deduct_credits RPC is atomic and returns the updated row
r = requests.post(f"{BASE}/rest/v1/rpc/deduct_credits", headers=H, json={"p_user_id": user_id, "p_tokens": 123})
print("deduct_credits RPC:", r.status_code, r.json())
assert r.status_code == 200
result = r.json()
result = result[0] if isinstance(result, list) else result
assert result["tokens_remaining"] == 50000 - 123
assert result["tokens_used_total"] == 123

# RPC is RLS-scoped: passing another (nonexistent) user_id updates nothing
r = requests.post(f"{BASE}/rest/v1/rpc/deduct_credits", headers=H, json={"p_user_id": "00000000-0000-0000-0000-000000000000", "p_tokens": 999})
print("deduct_credits for a foreign user_id (expect no-op, empty):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

print("\nSCHEMA + RPC VERIFIED")
EOF
```

Expected output ends with `SCHEMA + RPC VERIFIED`. If a query 404s, the schema cache hasn't reloaded — re-run `notify pgrst, 'reload schema';` and retry. If `deduct_credits` responds with a shape different from what's asserted above (e.g. not list-wrapped), note the actual shape here — Task 2's `deduct_user_credits` must match reality, not this guess. (Ran 2026-08-16, output ended with `SCHEMA + RPC VERIFIED`. RPC response shape confirmed list-wrapped — `[{"user_id": ..., "tokens_remaining": 49877, "tokens_used_total": 123, "created_at": ...}]` — matching Task 2's planned unwrap logic exactly, no change needed there.)

- [x] **Step 3: Commit the plan's record of this manual step**

No code changed in this task — nothing to commit. Proceed to Task 2.

---

### Task 2: `powabase_client.py` — credits functions + fix `run_agent()`'s missing usage

**Files:**
- Modify: `app/powabase_client.py`

**Interfaces:**
- Consumes: `public.user_credits`, `public.deduct_credits` RPC (Task 1).
- Produces: `get_agent_run(run_id: str) -> tuple[dict, int]`; `run_agent(...)` unchanged signature but now always returns a real `usage` dict (or `None` only if the follow-up fetch itself fails) instead of always `None`; `get_user_credits(access_token: str) -> tuple[list, int]`; `ensure_user_credits_row(access_token: str, user_id: str) -> dict` (returns the row dict directly, not a tuple — it always succeeds or raises, there's no caller-facing error path to distinguish); `deduct_user_credits(access_token: str, user_id: str, tokens: int) -> tuple[dict, int]`. Tasks 3–5 consume all of these.

- [ ] **Step 1: Add `get_agent_run` and fix `run_agent` to actually populate `usage`**

Read `app/powabase_client.py`, then find `run_agent` and replace it (adding `get_agent_run` immediately before it):

```python
def get_agent_run(run_id: str) -> tuple[dict, int]:
    response = requests.get(
        f"{settings.powabase_url}/api/agents/runs/{run_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


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
        run_id = None
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
                run_id = event.get("run_id")
            elif kind == "complete":
                usage = event.get("usage")
                if usage is None and run_id:
                    # Verified live 2026-08-16: the standalone-agent /run/stream
                    # complete event never carries usage (unlike orchestration
                    # runs) -- the token counts only exist on the run record.
                    run_data, run_status = get_agent_run(run_id)
                    if run_status < 400:
                        usage = run_data.get("usage")
                return {
                    "content": event["content"],
                    "session_id": run_session_id,
                    "usage": usage,
                }, 200
            elif kind == "error":
                return {"error": event.get("message"), "code": event.get("code")}, 502

        return {"error": "stream ended without a complete event"}, 502
```

(Only two things changed from the existing function: `run_id` is now captured from the `start` event alongside `session_id`, and the `complete` branch fetches the run record for `usage` when the event itself doesn't carry it.)

- [ ] **Step 2: Add credits functions**

Append to `app/powabase_client.py`:

```python
def get_user_credits(access_token: str) -> tuple[list, int]:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/user_credits",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"select": "user_id,tokens_remaining,tokens_used_total,created_at"},
    )
    return response.json(), response.status_code


def ensure_user_credits_row(access_token: str, user_id: str) -> dict:
    existing, status_code = get_user_credits(access_token)
    if status_code < 400 and existing:
        return existing[0]

    response = requests.post(
        f"{settings.powabase_url}/rest/v1/user_credits",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=representation",
        },
        json={"user_id": user_id},
    )
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]

    # A concurrent request created the row first (or ignore-duplicates
    # returned no representation for the no-op) -- re-select.
    existing, status_code = get_user_credits(access_token)
    return existing[0]


def deduct_user_credits(access_token: str, user_id: str, tokens: int) -> tuple[dict, int]:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/rpc/deduct_credits",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"p_user_id": user_id, "p_tokens": tokens},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code
```

- [ ] **Step 3: Verify live — usage now populates for a real agent run, and credits functions work end-to-end**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings
from app.powabase_client import create_agent, run_agent, delete_agent, get_user_credits, ensure_user_credits_row, deduct_user_credits

BASE = settings.powabase_url
ANON = settings.powabase_anon_key

def get_token_and_id(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    data = r.json()
    token = data["access_token"]
    user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token}"}).json()["id"]
    return token, user_id

token, user_id = get_token_and_id("task2-verify@example.com")

# --- run_agent now returns real usage ---
agent_data, sc = create_agent("task2-usage-agent", "Reply with exactly: PONG")
assert sc == 201, (sc, agent_data)
agent_id = agent_data["id"]

result, sc = run_agent(agent_id, "ping")
print("run_agent result:", sc, result)
assert sc == 200
assert result["content"] == "PONG"
assert result["usage"] is not None, "usage must now be populated"
assert result["usage"]["total_tokens"] > 0
print("run_agent usage populated:", result["usage"])

delete_agent(agent_id)

# --- ensure_user_credits_row is idempotent and doesn't reset balance ---
row1 = ensure_user_credits_row(token, user_id)
print("first ensure:", row1)
assert row1["tokens_remaining"] == 50000

deducted, sc = deduct_user_credits(token, user_id, 500)
print("deduct 500:", sc, deducted)
assert sc == 200
assert deducted["tokens_remaining"] == 49500

row2 = ensure_user_credits_row(token, user_id)
print("second ensure (must NOT reset balance):", row2)
assert row2["tokens_remaining"] == 49500, "ensure_user_credits_row must not clobber an existing row"

print("\nTASK 2 FUNCTIONS VERIFIED")
EOF
```

Expected output ends with `TASK 2 FUNCTIONS VERIFIED`.

- [ ] **Step 4: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add credits functions and fix run_agent's missing usage field"
```

---

### Task 3: `GET /me/credits`

**Files:**
- Create: `app/routes/credits.py`
- Modify: `app/main.py` — register the new router

**Interfaces:**
- Consumes: `ensure_user_credits_row` (Task 2).
- Produces: `app.routes.credits.router`; `GET /me/credits` → `{"tokens_remaining": int, "tokens_used_total": int}`.

- [ ] **Step 1: Create `app/routes/credits.py`**

```python
from fastapi import APIRouter, Depends

from app.deps import AuthedUser, get_current_user
from app.powabase_client import ensure_user_credits_row

router = APIRouter(tags=["credits"])


@router.get("/me/credits")
def get_my_credits_route(user: AuthedUser = Depends(get_current_user)):
    row = ensure_user_credits_row(user.access_token, user.id)
    return {"tokens_remaining": row["tokens_remaining"], "tokens_used_total": row["tokens_used_total"]}
```

- [ ] **Step 2: Register the router in `app/main.py`**

Read `app/main.py`, then:

```python
from fastapi import FastAPI

from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.credits import router as credits_router
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
    app.include_router(credits_router)
    return app


app = create_app()
```

- [ ] **Step 3: Restart the server and verify**

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
creds = {"email": "task3-credits-verify@example.com", "password": "TestPass123!"}

r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.get(f"{APP}/me/credits", headers={"Authorization": f"Bearer {token}"})
print(r.status_code, r.json())
assert r.status_code == 200
body = r.json()
assert "tokens_remaining" in body and "tokens_used_total" in body

# Second call is idempotent (row already exists)
r2 = requests.get(f"{APP}/me/credits", headers={"Authorization": f"Bearer {token}"})
assert r2.status_code == 200 and r2.json()["tokens_remaining"] == body["tokens_remaining"]

print("OK: GET /me/credits works and is idempotent")
EOF
```

Expected: `OK: GET /me/credits works and is idempotent`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/credits.py app/main.py
git commit -m "feat: add GET /me/credits"
```

---

### Task 4: Enforce credits in `POST /chat`

**Files:**
- Modify: `app/routes/chat.py`

**Interfaces:**
- Consumes: `ensure_user_credits_row`, `deduct_user_credits` (Task 2).
- Produces: `POST /chat` now returns `402` when `tokens_remaining <= 0`, and decrements the user's balance by the run's `total_tokens` after a successful response.

- [ ] **Step 1: Add the credit check and deduction**

Read `app/routes/chat.py`, then replace the whole file:

```python
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    deduct_user_credits,
    ensure_user_credits_row,
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
    credits_row = ensure_user_credits_row(user.access_token, user.id)
    if credits_row["tokens_remaining"] <= 0:
        raise HTTPException(status_code=402, detail="Token balance exhausted. You have no tokens remaining.")

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

    usage = data.get("usage")
    if usage and usage.get("total_tokens"):
        deduct_user_credits(user.access_token, user.id, usage["total_tokens"])

    return data
```

(A deduction failure -- e.g. the RPC call itself erroring -- is not raised as an HTTP error: the chat response the user already paid for in latency still returns. It's a best-effort bookkeeping step, not a gate.)

- [ ] **Step 2: Restart the server and verify the 402 gate and deduction end-to-end**

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

token = get_token("task4-chat-credits@example.com")
H = {"Authorization": f"Bearer {token}"}

r = requests.post(f"{APP}/agents", headers=H, json={"name": "Task4 Credits Agent", "system_prompt": "Reply with exactly: PONG"})
assert r.status_code == 200, r.text
agent_id = r.json()["agent_id"]

before = requests.get(f"{APP}/me/credits", headers=H).json()
print("before:", before)

r = requests.post(f"{APP}/chat", headers=H, json={"agent_id": agent_id, "message": "ping"})
print("chat:", r.status_code, r.json())
assert r.status_code == 200

after = requests.get(f"{APP}/me/credits", headers=H).json()
print("after:", after)
assert after["tokens_remaining"] < before["tokens_remaining"], "balance must decrease after a chat"
assert after["tokens_used_total"] > before["tokens_used_total"]
print("credits deducted correctly")

# Exhaust the balance directly via PostgREST (service key) and confirm 402
from app.config import settings as s
SVC_H = {"apikey": s.powabase_service_key, "Authorization": f"Bearer {s.powabase_service_key}", "Content-Type": "application/json"}
user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token}"}).json()["id"]
requests.patch(f"{BASE}/rest/v1/user_credits", headers=SVC_H, params={"user_id": f"eq.{user_id}"}, json={"tokens_remaining": 0})

r = requests.post(f"{APP}/chat", headers=H, json={"agent_id": agent_id, "message": "ping again"})
print("chat with zero balance:", r.status_code, r.json())
assert r.status_code == 402

print("\nOK: credit deduction and 402 gate both verified")
EOF
```

Expected: `OK: credit deduction and 402 gate both verified`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chat.py
git commit -m "feat: enforce and deduct token credits on POST /chat"
```

---

### Task 5: Enforce credits in `POST /chatbots/{id}/chat`

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `ensure_user_credits_row`, `deduct_user_credits` (Task 2). `run_orchestration`'s `usage` is already populated (Global Constraints) — no client-function change needed here.
- Produces: `POST /chatbots/{chatbot_id}/chat` now returns `402` when `tokens_remaining <= 0`, and decrements the user's balance after a successful response.

- [ ] **Step 1: Add the credit check and deduction**

Read `app/routes/chatbots.py`. First, add `deduct_user_credits` and `ensure_user_credits_row` to the existing `from app.powabase_client import (...)` block (keep it alphabetically sorted like the rest):

```python
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_orchestration_entity,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    create_orchestration,
    deduct_user_credits,
    delete_agent,
    delete_agent_registry_row,
    delete_chatbot_row,
    delete_knowledge_base,
    delete_orchestration,
    ensure_session_context_tool,
    ensure_user_credits_row,
    get_chatbot_agent_entry,
    get_chatbot_entry,
    get_chatbot_session_entry,
    get_session_messages,
    insert_agent_registry_row,
    insert_chatbot_row,
    insert_chatbot_session_row,
    link_agent_knowledge_base,
    list_chatbot_agent_rows,
    list_chatbot_rows,
    list_chatbot_sessions,
    remove_orchestration_entity,
    run_orchestration,
)
```

Then find `chatbot_chat_route` and replace it:

```python
@router.post("/{chatbot_id}/chat")
def chatbot_chat_route(chatbot_id: str, req: ChatbotChatRequest, user: AuthedUser = Depends(get_current_user)):
    credits_row = ensure_user_credits_row(user.access_token, user.id)
    if credits_row["tokens_remaining"] <= 0:
        raise HTTPException(status_code=402, detail="Token balance exhausted. You have no tokens remaining.")

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

    usage = data.get("usage")
    if usage and usage.get("total_tokens"):
        deduct_user_credits(user.access_token, user.id, usage["total_tokens"])

    return data
```

- [ ] **Step 2: Restart the server and verify the 402 gate and deduction end-to-end**

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

token = get_token("task5-chatbot-credits@example.com")
H = {"Authorization": f"Bearer {token}"}

r = requests.post(f"{APP}/chatbots", headers=H, json={
    "name": "Task5 Credits Chatbot", "agent_name": "Task5 Agent", "role_description": "Handles everything, always replies PONG.", "system_prompt": "Always reply with exactly: PONG"
})
assert r.status_code == 200, r.text
chatbot_id = r.json()["chatbot"]["id"]

before = requests.get(f"{APP}/me/credits", headers=H).json()
print("before:", before)

r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers=H, json={"message": "ping"})
print("chatbot chat:", r.status_code, r.json())
assert r.status_code == 200

after = requests.get(f"{APP}/me/credits", headers=H).json()
print("after:", after)
assert after["tokens_remaining"] < before["tokens_remaining"], "balance must decrease after a chatbot chat"
print("credits deducted correctly")

# Exhaust the balance directly and confirm 402
from app.config import settings as s
SVC_H = {"apikey": s.powabase_service_key, "Authorization": f"Bearer {s.powabase_service_key}", "Content-Type": "application/json"}
user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token}"}).json()["id"]
requests.patch(f"{BASE}/rest/v1/user_credits", headers=SVC_H, params={"user_id": f"eq.{user_id}"}, json={"tokens_remaining": 0})

r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers=H, json={"message": "ping again"})
print("chatbot chat with zero balance:", r.status_code, r.json())
assert r.status_code == 402

print("\nOK: chatbot credit deduction and 402 gate both verified")
EOF
```

Expected: `OK: chatbot credit deduction and 402 gate both verified`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: enforce and deduct token credits on POST /chatbots/{id}/chat"
```

---

### Task 6: `powabase_client.py` — rename/update functions

**Files:**
- Modify: `app/powabase_client.py`

**Interfaces:**
- Produces: `update_agent_registry_name(access_token, agent_id, name) -> tuple[dict, int]`; `update_chatbot_name(access_token, chatbot_id, name) -> tuple[dict, int]`; `update_chat_session_label(access_token, agent_id, session_id, label) -> tuple[dict, int]`; `update_chatbot_session_label(access_token, chatbot_id, session_id, label) -> tuple[dict, int]`. Tasks 7–8 consume these.

- [ ] **Step 1: Add the four functions**

Append to `app/powabase_client.py`:

```python
def update_agent_registry_name(access_token: str, agent_id: str, name: str) -> tuple[dict, int]:
    response = requests.patch(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"agent_id": f"eq.{agent_id}"},
        json={"name": name},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def update_chatbot_name(access_token: str, chatbot_id: str, name: str) -> tuple[dict, int]:
    response = requests.patch(
        f"{settings.powabase_url}/rest/v1/chatbots",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"id": f"eq.{chatbot_id}"},
        json={"name": name},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def update_chat_session_label(access_token: str, agent_id: str, session_id: str, label: str) -> tuple[dict, int]:
    response = requests.patch(
        f"{settings.powabase_url}/rest/v1/chat_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"agent_id": f"eq.{agent_id}", "powabase_session_id": f"eq.{session_id}"},
        json={"label": label},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def update_chatbot_session_label(access_token: str, chatbot_id: str, session_id: str, label: str) -> tuple[dict, int]:
    response = requests.patch(
        f"{settings.powabase_url}/rest/v1/chatbot_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        params={"chatbot_id": f"eq.{chatbot_id}", "powabase_session_id": f"eq.{session_id}"},
        json={"label": label},
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code
```

(All four mirror the existing `update_chat_session_kb_id` exactly — same header/`Prefer`/list-unwrap pattern.)

- [ ] **Step 2: Verify live (no server needed)**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings
from app.powabase_client import (
    create_agent, create_knowledge_base, link_agent_knowledge_base, insert_agent_registry_row,
    update_agent_registry_name, delete_agent, delete_knowledge_base, delete_agent_registry_row,
    create_orchestration, add_orchestration_entity, insert_chatbot_row, update_chatbot_name,
    delete_orchestration, delete_chatbot_row,
)

BASE = settings.powabase_url
ANON = settings.powabase_anon_key

def get_token_and_id(email):
    creds = {"email": email, "password": "TestPass123!"}
    r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    if r.status_code >= 400:
        r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
    token = r.json()["access_token"]
    user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token}"}).json()["id"]
    return token, user_id

token, user_id = get_token_and_id("task6-rename-verify@example.com")

# agents_registry rename
kb_data, sc = create_knowledge_base(f"task6-kb-{user_id}")
agent_data, sc = create_agent("task6-agent", None)
agent_id = agent_data["id"]
link_agent_knowledge_base(agent_id, kb_data["id"])
insert_agent_registry_row(token, user_id, agent_id, kb_data["id"], "Original Name")

updated, sc = update_agent_registry_name(token, agent_id, "Renamed Agent")
print("update_agent_registry_name:", sc, updated)
assert sc == 200 and updated["name"] == "Renamed Agent"

delete_agent(agent_id)
delete_knowledge_base(kb_data["id"])
delete_agent_registry_row(token, agent_id)

# chatbots rename
orch_data, sc = create_orchestration("task6-orch", {"additional_instructions": "test"})
orch_id = orch_data["id"]
chatbot_row, sc = insert_chatbot_row(token, user_id, orch_id, "Original Chatbot Name")
chatbot_id = chatbot_row["id"]

updated, sc = update_chatbot_name(token, chatbot_id, "Renamed Chatbot")
print("update_chatbot_name:", sc, updated)
assert sc == 200 and updated["name"] == "Renamed Chatbot"

delete_orchestration(orch_id)
delete_chatbot_row(token, chatbot_id)

print("\nTASK 6 FUNCTIONS VERIFIED")
EOF
```

Expected output ends with `TASK 6 FUNCTIONS VERIFIED`. (Session-label functions are exercised end-to-end in Tasks 7–8, since they need a real session which needs the running server's `/chat` flow.)

- [ ] **Step 3: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add rename/relabel functions for agents, chatbots, and sessions"
```

---

### Task 7: `PATCH /agents/{agent_id}` and `PATCH /agents/{agent_id}/sessions/{session_id}`

**Files:**
- Modify: `app/routes/agents.py`
- Modify: `app/routes/sessions.py`

**Interfaces:**
- Consumes: `update_agent_registry_name`, `update_chat_session_label` (Task 6).
- Produces: `PATCH /agents/{agent_id}` body `{name}` → updated registry row. `PATCH /agents/{agent_id}/sessions/{session_id}` body `{label}` → updated session row.

- [ ] **Step 1: Add `PATCH /agents/{agent_id}`**

Read `app/routes/agents.py`, then replace the whole file:

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
    get_agent_registry_entry,
    insert_agent_registry_row,
    link_agent_knowledge_base,
    list_agent_registry_rows,
    update_agent_registry_name,
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


class UpdateAgentRequest(BaseModel):
    name: str


@router.patch("/{agent_id}")
def update_agent_route(agent_id: str, req: UpdateAgentRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    data, status_code = update_agent_registry_name(user.access_token, agent_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

(Note: `get_agent_registry_entry` already exists in `powabase_client.py` and previously wasn't imported by `agents.py` — it's added here for the ownership check, same helper `chat.py`/`sessions.py` already use.)

- [ ] **Step 2: Add `PATCH /agents/{agent_id}/sessions/{session_id}`**

Read `app/routes/sessions.py`. Add `update_chat_session_label` to the existing import block:

```python
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
    update_chat_session_label,
    upload_source,
)
```

Then append this route to the end of the file:

```python
class UpdateSessionRequest(BaseModel):
    label: str


@router.patch("/{agent_id}/sessions/{session_id}")
def update_session_route(agent_id: str, session_id: str, req: UpdateSessionRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    data, status_code = update_chat_session_label(user.access_token, agent_id, session_id, req.label)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

`sessions.py` doesn't currently import `BaseModel` — add `from pydantic import BaseModel` to its import block (alongside the existing `fastapi` import line at the top of the file).

- [ ] **Step 3: Restart the server and verify both routes, plus cross-user protection**

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

token_a = get_token("task7-user-a@example.com")
token_b = get_token("task7-user-b@example.com")
HA = {"Authorization": f"Bearer {token_a}"}
HB = {"Authorization": f"Bearer {token_b}"}

r = requests.post(f"{APP}/agents", headers=HA, json={"name": "Task7 Original Name"})
agent_id = r.json()["agent_id"]

r = requests.patch(f"{APP}/agents/{agent_id}", headers=HA, json={"name": "Task7 Renamed"})
print("rename agent:", r.status_code, r.json())
assert r.status_code == 200 and r.json()["name"] == "Task7 Renamed"

r = requests.patch(f"{APP}/agents/{agent_id}", headers=HB, json={"name": "Malicious Rename"})
assert r.status_code == 403, (r.status_code, r.text)
print("cross-user agent rename blocked with 403 as expected")

r = requests.post(f"{APP}/chat", headers=HA, json={"agent_id": agent_id, "message": "hello", "label": "Original Session Label"})
session_id = r.json()["session_id"]

r = requests.patch(f"{APP}/agents/{agent_id}/sessions/{session_id}", headers=HA, json={"label": "Renamed Session"})
print("rename session:", r.status_code, r.json())
assert r.status_code == 200 and r.json()["label"] == "Renamed Session"

r = requests.patch(f"{APP}/agents/{agent_id}/sessions/{session_id}", headers=HB, json={"label": "Malicious Rename"})
assert r.status_code in (403, 404), (r.status_code, r.text)
print("cross-user session rename blocked as expected")

print("\nOK: agent rename + session rename + both cross-user blocks verified")
EOF
```

Expected: `OK: agent rename + session rename + both cross-user blocks verified`.

- [ ] **Step 4: Commit**

```bash
git add app/routes/agents.py app/routes/sessions.py
git commit -m "feat: add PATCH /agents/{id} and PATCH /agents/{id}/sessions/{id} for renaming"
```

---

### Task 8: `PATCH /chatbots/{chatbot_id}` and `PATCH /chatbots/{chatbot_id}/sessions/{session_id}`

**Files:**
- Modify: `app/routes/chatbots.py`

**Interfaces:**
- Consumes: `update_chatbot_name`, `update_chatbot_session_label` (Task 6).
- Produces: `PATCH /chatbots/{chatbot_id}` body `{name}` → updated chatbot row. `PATCH /chatbots/{chatbot_id}/sessions/{session_id}` body `{label}` → updated session row.

- [ ] **Step 1: Add both routes**

Read `app/routes/chatbots.py`. Add `update_chatbot_name` and `update_chatbot_session_label` to the existing `from app.powabase_client import (...)` block (alphabetically sorted with the rest, which by this point in the plan also includes `deduct_user_credits` and `ensure_user_credits_row` from Task 5):

```python
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_orchestration_entity,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    create_orchestration,
    deduct_user_credits,
    delete_agent,
    delete_agent_registry_row,
    delete_chatbot_row,
    delete_knowledge_base,
    delete_orchestration,
    ensure_session_context_tool,
    ensure_user_credits_row,
    get_chatbot_agent_entry,
    get_chatbot_entry,
    get_chatbot_session_entry,
    get_session_messages,
    insert_agent_registry_row,
    insert_chatbot_row,
    insert_chatbot_session_row,
    link_agent_knowledge_base,
    list_chatbot_agent_rows,
    list_chatbot_rows,
    list_chatbot_sessions,
    remove_orchestration_entity,
    run_orchestration,
    update_chatbot_name,
    update_chatbot_session_label,
)
```

Then append these routes to the end of the file:

```python
class UpdateChatbotRequest(BaseModel):
    name: str


@router.patch("/{chatbot_id}")
def update_chatbot_route(chatbot_id: str, req: UpdateChatbotRequest, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")

    data, status_code = update_chatbot_name(user.access_token, chatbot_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


class UpdateChatbotSessionRequest(BaseModel):
    label: str


@router.patch("/{chatbot_id}/sessions/{session_id}")
def update_chatbot_session_route(chatbot_id: str, session_id: str, req: UpdateChatbotSessionRequest, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")

    session_rows, status_code = get_chatbot_session_entry(user.access_token, chatbot_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this chatbot")

    data, status_code = update_chatbot_session_label(user.access_token, chatbot_id, session_id, req.label)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
```

- [ ] **Step 2: Restart the server and verify both routes, plus cross-user protection**

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

token_a = get_token("task8-user-a@example.com")
token_b = get_token("task8-user-b@example.com")
HA = {"Authorization": f"Bearer {token_a}"}
HB = {"Authorization": f"Bearer {token_b}"}

r = requests.post(f"{APP}/chatbots", headers=HA, json={
    "name": "Task8 Original Chatbot", "agent_name": "Task8 Agent", "role_description": "Handles everything, always replies PONG.", "system_prompt": "Always reply with exactly: PONG"
})
chatbot_id = r.json()["chatbot"]["id"]

r = requests.patch(f"{APP}/chatbots/{chatbot_id}", headers=HA, json={"name": "Task8 Renamed Chatbot"})
print("rename chatbot:", r.status_code, r.json())
assert r.status_code == 200 and r.json()["name"] == "Task8 Renamed Chatbot"

r = requests.patch(f"{APP}/chatbots/{chatbot_id}", headers=HB, json={"name": "Malicious Rename"})
assert r.status_code == 403, (r.status_code, r.text)
print("cross-user chatbot rename blocked with 403 as expected")

r = requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers=HA, json={"message": "hello", "label": "Original Session Label"})
session_id = r.json()["session_id"]

r = requests.patch(f"{APP}/chatbots/{chatbot_id}/sessions/{session_id}", headers=HA, json={"label": "Renamed Session"})
print("rename chatbot session:", r.status_code, r.json())
assert r.status_code == 200 and r.json()["label"] == "Renamed Session"

r = requests.patch(f"{APP}/chatbots/{chatbot_id}/sessions/{session_id}", headers=HB, json={"label": "Malicious Rename"})
assert r.status_code in (403, 404), (r.status_code, r.text)
print("cross-user chatbot session rename blocked as expected")

print("\nOK: chatbot rename + chatbot session rename + both cross-user blocks verified")
EOF
```

Expected: `OK: chatbot rename + chatbot session rename + both cross-user blocks verified`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/chatbots.py
git commit -m "feat: add PATCH /chatbots/{id} and PATCH /chatbots/{id}/sessions/{id} for renaming"
```

---

### Task 9: Optional `model` field on agent creation

**Files:**
- Modify: `app/powabase_client.py` — `create_agent`
- Modify: `app/routes/agents.py` — `CreateAgentRequest`
- Modify: `app/routes/chatbots.py` — `CreateChatbotRequest`, `AddAgentRequest`, `_create_subagent`

**Interfaces:**
- Produces: `create_agent(name, system_prompt, model=None) -> tuple[dict, int]`; `CreateAgentRequest.model: str | None`; `CreateChatbotRequest.model: str | None` (applies to the chatbot's first agent); `AddAgentRequest.model: str | None`; `_create_subagent(name, system_prompt, user_id, model=None) -> tuple[str, str]`.

- [ ] **Step 1: Add `model` to `create_agent`**

Read `app/powabase_client.py`, then find `create_agent` and replace it:

```python
def create_agent(name: str, system_prompt: str | None, model: str | None = None) -> dict:
    body = {"name": name}
    if system_prompt:
        body["system_prompt"] = system_prompt
    if model:
        body["model"] = model
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
```

- [ ] **Step 2: Thread `model` through `POST /agents`**

Read `app/routes/agents.py`, then update `CreateAgentRequest` and `create_agent_route`:

```python
class CreateAgentRequest(BaseModel):
    name: str
    system_prompt: str | None = None
    model: str | None = None


@router.post("")
def create_agent_route(req: CreateAgentRequest, user: AuthedUser = Depends(get_current_user)):
    kb_data, status_code = create_knowledge_base(f"{req.name}-{user.id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(req.name, req.system_prompt, req.model)
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
```

(Only `create_agent`'s call site and the new `model` field changed; the rest of the file — `PATCH /agents/{agent_id}` from Task 7, `GET /agents` — is unchanged.)

- [ ] **Step 3: Thread `model` through `POST /chatbots` and `POST /chatbots/{id}/agents`**

Read `app/routes/chatbots.py`, then update `_create_subagent`, `CreateChatbotRequest`, `create_chatbot_route`, `AddAgentRequest`, and `add_chatbot_agent_route`:

```python
class CreateChatbotRequest(BaseModel):
    name: str
    agent_name: str
    role_description: str
    system_prompt: str | None = None
    model: str | None = None


def _create_subagent(name: str, system_prompt: str | None, user_id: str, model: str | None = None) -> tuple[str, str]:
    """Agent + its own isolated KB + session-context tool -- same recipe as POST /agents."""
    kb_data, status_code = create_knowledge_base(f"{name}-{user_id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(name, system_prompt, model)
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
    agent_id, kb_id = _create_subagent(req.agent_name, req.system_prompt, user.id, req.model)

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


class AddAgentRequest(BaseModel):
    name: str
    role_description: str
    system_prompt: str | None = None
    model: str | None = None


@router.post("/{chatbot_id}/agents")
def add_chatbot_agent_route(chatbot_id: str, req: AddAgentRequest, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    agent_id, kb_id = _create_subagent(req.name, req.system_prompt, user.id, req.model)

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

(Every other route in the file — `GET /chatbots`, `GET /chatbots/{id}`, session routes, delete routes, the Task 5 credit gate, the Task 8 rename routes — is unchanged.)

- [ ] **Step 4: Restart the server and verify the model is actually applied on all three creation paths**

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

token = get_token("task9-model-verify@example.com")
H = {"Authorization": f"Bearer {token}"}

# POST /agents with an explicit model
r = requests.post(f"{APP}/agents", headers=H, json={"name": "Task9 Agent", "model": "claude-sonnet-4-6"})
assert r.status_code == 200, r.text
agent_id = r.json()["agent_id"]
live = requests.get(f"{BASE}/api/agents/{agent_id}", headers=SVC_H).json()
print("agent model on Powabase's own record:", live.get("model"))
assert live.get("model") == "claude-sonnet-4-6"

# POST /agents with no model -> must behave IDENTICALLY to before this task existed,
# not just "some default gets applied". Verify three ways: (1) the request body our
# own code now sends is byte-identical to the pre-Task-9 body (no model key at all,
# not model: null or model: ""), (2) the resulting agent's resolved model matches an
# agent created by literally replaying the pre-Task-9 request shape directly against
# Powabase (bypassing our app entirely), and (3) it matches every agent already living
# in this project from before this plan, which never set model.
r = requests.post(f"{APP}/agents", headers=H, json={"name": "Task9 Default Agent"})
agent_id2 = r.json()["agent_id"]
live2 = requests.get(f"{BASE}/api/agents/{agent_id2}", headers=SVC_H).json()
print("agent model when omitted via our API:", live2.get("model"))
assert live2.get("model")

# (2) Replay the exact pre-Task-9 request body directly against Powabase, no model key.
r3 = requests.post(f"{BASE}/api/agents", headers=SVC_H, json={"name": "Task9 Pre-Change-Equivalent Agent"})
live3 = r3.json()
print("agent model via literal pre-Task-9-shaped request:", live3.get("model"))
assert live3.get("model") == live2.get("model"), "omitting model must resolve identically to the pre-existing (no-model-field-ever) request shape"

# (3) Cross-check against agents already in this project from before this plan existed.
existing = requests.get(f"{BASE}/api/agents", headers=SVC_H, params={"limit": 10}).json().get("agents", [])
pre_existing_models = {a["model"] for a in existing if a["id"] not in (agent_id, agent_id2, live3["id"])}
print("models on agents already in this project:", pre_existing_models)
assert live2.get("model") in pre_existing_models, "the omitted-model default must match what every pre-existing agent already resolved to"

requests.delete(f"{BASE}/api/agents/{live3['id']}", headers=SVC_H)

# POST /chatbots applies model to the first agent
r = requests.post(f"{APP}/chatbots", headers=H, json={
    "name": "Task9 Chatbot", "agent_name": "Task9 Chatbot Agent", "role_description": "Handles everything.", "model": "gpt-4o"
})
assert r.status_code == 200, r.text
chatbot_id = r.json()["chatbot"]["id"]
sub_agent_id = r.json()["agent"]["agent_id"]
live3 = requests.get(f"{BASE}/api/agents/{sub_agent_id}", headers=SVC_H).json()
print("chatbot's first agent model:", live3.get("model"))
assert live3.get("model") == "gpt-4o"

# POST /chatbots/{id}/agents applies model to a new subagent
r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers=H, json={
    "name": "Task9 Second Agent", "role_description": "Handles the rest.", "model": "gemini/gemini-2.5-flash"
})
assert r.status_code == 200, r.text
second_agent_id = r.json()["agent_id"]
live4 = requests.get(f"{BASE}/api/agents/{second_agent_id}", headers=SVC_H).json()
print("added subagent model:", live4.get("model"))
assert live4.get("model") == "gemini/gemini-2.5-flash"

print("\nOK: model field verified on all three creation paths against Powabase's own records")
EOF
```

Expected: `OK: model field verified on all three creation paths against Powabase's own records`.

- [ ] **Step 5: Commit**

```bash
git add app/powabase_client.py app/routes/agents.py app/routes/chatbots.py
git commit -m "feat: add optional model selection to agent, chatbot, and subagent creation"
```

---

### Task 10: CORS + rate limiting on chat endpoints

**Files:**
- Create: `app/rate_limit.py`
- Modify: `app/main.py` — CORS middleware + `Limiter` wiring
- Modify: `app/routes/chat.py` — apply `@limiter.limit(...)` to `POST /chat`
- Modify: `app/routes/chatbots.py` — apply `@limiter.limit(...)` to `POST /chatbots/{id}/chat`

**Interfaces:**
- Produces: `app.rate_limit.limiter` (a `slowapi.Limiter`), imported by both chat routes. `POST /chat` and `POST /chatbots/{id}/chat` now return `429` past 20 requests/minute for the same bearer token. The backend also now accepts cross-origin requests from the frontend dev server (needed for Tasks 11-13).

- [ ] **Step 1: Install slowapi**

```bash
cd /home/william/powabase-chatbot && .venv/bin/pip install slowapi
```

- [ ] **Step 2: Create `app/rate_limit.py`**

```python
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    # Key on the raw bearer token, not a verified user id -- resolving the
    # token to a user requires a live call to Powabase's /auth/v1/user, and
    # doing that a second time here (on top of the get_current_user
    # dependency) would double the auth round-trips on every chat request.
    # A bad/expired token still gets its own bucket; get_current_user rejects
    # it with 401 before the route body runs regardless of rate-limit status.
    auth = request.headers.get("authorization")
    return auth if auth else get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
```

- [ ] **Step 3: Wire CORS and the limiter into `app/main.py`**

Read `app/main.py`, then replace the whole file:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.rate_limit import limiter
from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.credits import router as credits_router
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
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(chatbots_router)
    app.include_router(sessions_router)
    app.include_router(ingest_router)
    app.include_router(chat_router)
    app.include_router(tools_router)
    app.include_router(credits_router)
    return app


app = create_app()
```

- [ ] **Step 4: Apply the limit to `POST /chat`**

Read `app/routes/chat.py`. Add `from fastapi import Request` (extend the existing `from fastapi import ...` line) and `from app.rate_limit import limiter`, then update the route:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

```python
from app.rate_limit import limiter
```

```python
@router.post("/chat")
@limiter.limit("20/minute")
def chat_route(request: Request, req: ChatRequest, user: AuthedUser = Depends(get_current_user)):
```

(Only the decorator and the new leading `request: Request` parameter change — the function body is identical to Task 4's version.)

- [ ] **Step 5: Apply the limit to `POST /chatbots/{id}/chat`**

Read `app/routes/chatbots.py`. Add `Request` to the existing `from fastapi import ...` line and `from app.rate_limit import limiter`, then update the route:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

```python
from app.rate_limit import limiter
```

```python
@router.post("/{chatbot_id}/chat")
@limiter.limit("20/minute")
def chatbot_chat_route(chatbot_id: str, request: Request, req: ChatbotChatRequest, user: AuthedUser = Depends(get_current_user)):
```

(Only the decorator and the new `request: Request` parameter change — the function body is identical to Task 5's version.)

- [ ] **Step 6: Restart the server and verify the 429, keyed per-token, without spending real chat runs**

The rate limiter's decorator wraps the whole endpoint function and rejects before the body executes — so a bogus `agent_id` (which would otherwise 403 from inside the function body) is enough to test the limiter cheaply, with no real Powabase run cost.

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

token_a = get_token("task10-ratelimit-a@example.com")
token_b = get_token("task10-ratelimit-b@example.com")
HA = {"Authorization": f"Bearer {token_a}"}
HB = {"Authorization": f"Bearer {token_b}"}

statuses = []
for i in range(25):
    r = requests.post(f"{APP}/chat", headers=HA, json={"agent_id": "00000000-0000-0000-0000-000000000000", "message": "ping"})
    statuses.append(r.status_code)

print("statuses for user A's 25 rapid requests:", statuses)
assert statuses[:20].count(429) == 0, "the first 20 must not be rate-limited"
assert 429 in statuses[20:], "request 21+ must be rate-limited"

# A different user (different bearer token) has its own, unaffected bucket
r = requests.post(f"{APP}/chat", headers=HB, json={"agent_id": "00000000-0000-0000-0000-000000000000", "message": "ping"})
print("user B's first request (fresh bucket):", r.status_code)
assert r.status_code != 429, "a different user's bucket must not be affected by user A's rate limit"

# CORS: an OPTIONS preflight from the frontend origin is accepted
r = requests.options(f"{APP}/me/credits", headers={
    "Origin": "http://localhost:5173",
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization",
})
print("CORS preflight:", r.status_code, dict(r.headers).get("access-control-allow-origin"))
assert r.status_code in (200, 204)
assert dict(r.headers).get("access-control-allow-origin") == "http://localhost:5173"

print("\nOK: per-token rate limiting and CORS both verified")
EOF
```

Expected: `OK: per-token rate limiting and CORS both verified`.

- [ ] **Step 7: Commit**

```bash
git add app/rate_limit.py app/main.py app/routes/chat.py app/routes/chatbots.py
git commit -m "feat: add CORS middleware and per-user rate limiting on chat endpoints"
```

---

### Task 11: Frontend — token balance display

**Files:** (all under `/home/william/powabase-chatbot/.worktrees/react-frontend/frontend/src/`, branch `react-frontend`)
- Modify: `api/client.ts` — add `api.patch` (also needed by Task 12, adding it here since it's a one-line, low-risk change and this is the first frontend task)
- Modify: `api/types.ts` — add `CreditsSummary`
- Create: `api/credits.ts`
- Create: `context/CreditsContext.tsx`
- Modify: `components/AppShell.tsx` / `AppShell.module.css` — persistent display
- Modify: `components/ChatPanel.tsx` — fire a reload after every sent message
- Modify: `pages/AgentDetailPage.tsx`, `pages/ChatbotDetailPage.tsx` — wire the reload

**Interfaces:**
- Consumes: `GET /me/credits` (Task 3, backend).
- Produces: `CreditsSummary` type; `getMyCredits()`; `CreditsProvider`/`useCredits()` (`{ credits: CreditsSummary | null, loading, error, reload }`); `ChatPanel`'s new `onMessageSent?: () => void` prop.

- [ ] **Step 1: Add `api.patch` to the fetch wrapper**

Read `frontend/src/api/client.ts`, then find the `export const api = { ... }` block and replace it:

```typescript
export const api = {
  get: <T,>(path: string, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'GET', query }),
  post: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  postForm: <T,>(path: string, formData: FormData, query?: Record<string, string | undefined>) =>
    request<T>(path, { method: 'POST', body: formData, isFormData: true, query }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
};
```

- [ ] **Step 2: Add the `CreditsSummary` type**

Read `frontend/src/api/types.ts`, then append:

```typescript
export interface CreditsSummary {
  tokens_remaining: number;
  tokens_used_total: number;
}
```

- [ ] **Step 3: Create `api/credits.ts`**

```typescript
import { api } from './client';
import type { CreditsSummary } from './types';

export function getMyCredits() {
  return api.get<CreditsSummary>('/me/credits');
}
```

- [ ] **Step 4: Create `context/CreditsContext.tsx`**

```tsx
import { createContext, useContext, type ReactNode } from 'react';
import { getMyCredits } from '../api/credits';
import { useAsync } from '../hooks/useAsync';
import type { CreditsSummary } from '../api/types';

interface CreditsContextValue {
  credits: CreditsSummary | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const CreditsContext = createContext<CreditsContextValue | undefined>(undefined);

export function CreditsProvider({ children }: { children: ReactNode }) {
  const { data, loading, error, reload } = useAsync(() => getMyCredits(), []);
  return <CreditsContext.Provider value={{ credits: data, loading, error, reload }}>{children}</CreditsContext.Provider>;
}

export function useCredits(): CreditsContextValue {
  const ctx = useContext(CreditsContext);
  if (!ctx) throw new Error('useCredits must be used within CreditsProvider');
  return ctx;
}
```

- [ ] **Step 5: Show the balance in `AppShell`**

Read `frontend/src/components/AppShell.tsx`, then replace the whole file:

```tsx
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { CreditsProvider, useCredits } from '../context/CreditsContext';
import styles from './AppShell.module.css';

function CreditsDisplay() {
  const { credits } = useCredits();
  if (!credits) return null;
  return (
    <div className={styles.credits}>
      <p className={styles.creditsLabel}>Tokens remaining</p>
      <p className={styles.creditsValue}>{credits.tokens_remaining.toLocaleString()}</p>
    </div>
  );
}

function AppShellLayout() {
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
        <CreditsDisplay />
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

export function AppShell() {
  return (
    <CreditsProvider>
      <AppShellLayout />
    </CreditsProvider>
  );
}
```

- [ ] **Step 6: Style the credits block**

Read `frontend/src/components/AppShell.module.css`, then find the `.nav` rule's closing brace and insert this immediately after it (before `.navLink, .navLinkActive`):

```css
.credits {
  border-top: 1px solid var(--color-border);
  padding: 12px 10px;
  margin-bottom: 4px;
}

.creditsLabel {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted);
  margin: 0 0 2px;
}

.creditsValue {
  font-family: var(--font-mono);
  font-size: 15px;
  color: var(--color-accent);
  margin: 0;
}
```

- [ ] **Step 7: Refresh the balance after every chat message**

Read `frontend/src/components/ChatPanel.tsx`, then update the props interface and `handleSend`:

```tsx
interface ChatPanelProps {
  initialMessages?: SessionMessage[];
  initialSessionId?: string | null;
  sendMessage: (message: string, sessionId: string | null) => Promise<ChatResult>;
  onSessionStart?: (sessionId: string) => void;
  onMessageSent?: () => void;
}

export function ChatPanel({
  initialMessages = [],
  initialSessionId = null,
  sendMessage,
  onSessionStart,
  onMessageSent,
}: ChatPanelProps) {
```

Inside `handleSend`, right after the existing `if (sessionId === null) { ... }` block (still inside the `try`):

```tsx
    try {
      const result = await sendMessage(text, sessionId);
      setMessages((prev) => [...prev, { role: 'assistant', content: result.content }]);
      if (sessionId === null) {
        setSessionId(result.session_id);
        onSessionStart?.(result.session_id);
      }
      onMessageSent?.();
    } catch (err) {
```

- [ ] **Step 8: Wire the reload in both detail pages**

Read `frontend/src/pages/AgentDetailPage.tsx`. Add the import and hook, then pass the prop:

```tsx
import { useCredits } from '../context/CreditsContext';
```

```tsx
export function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const credits = useCredits();
```

(add the `credits` line right after the existing `agentId` destructure)

```tsx
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithAgent(agentId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
            onMessageSent={credits.reload}
          />
```

Read `frontend/src/pages/ChatbotDetailPage.tsx`. Same pattern:

```tsx
import { useCredits } from '../context/CreditsContext';
```

```tsx
export function ChatbotDetailPage() {
  const { chatbotId } = useParams<{ chatbotId: string }>();
  const navigate = useNavigate();
  const credits = useCredits();
```

```tsx
          <ChatPanel
            key={conversation.chatConfig.key}
            initialMessages={conversation.chatConfig.initialMessages}
            initialSessionId={conversation.chatConfig.initialSessionId}
            sendMessage={(message, sessionId) => chatWithChatbot(chatbotId!, message, sessionId)}
            onSessionStart={(sessionId) => {
              conversation.onSessionStart(sessionId);
              sessions.reload();
            }}
            onMessageSent={credits.reload}
          />
```

- [ ] **Step 9: Type-check, build, and manually verify in the browser**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend && npx tsc --noEmit && npm run build
```

Expected: both commands exit 0 with no errors.

Then, per Global Constraints, run the backend from the `main` checkout and the frontend dev server from this worktree:

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend && npm run dev
```

Open `http://localhost:5173`, sign in (or sign up), and confirm: the sidebar shows "Tokens remaining" with a number under the nav links; sending a chat message in any agent/chatbot detail page decreases the displayed number without a manual page reload.

- [ ] **Step 10: Commit**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend
git add src/api/client.ts src/api/types.ts src/api/credits.ts src/context/CreditsContext.tsx src/components/AppShell.tsx src/components/AppShell.module.css src/components/ChatPanel.tsx src/pages/AgentDetailPage.tsx src/pages/ChatbotDetailPage.tsx
git commit -m "feat: add persistent token balance display, refreshing after each chat message"
```

---

### Task 12: Frontend — rename UI on agent cards, chatbot cards, and session list items

**Files:** (all under the `react-frontend` worktree's `frontend/src/`)
- Create: `components/EditableName.tsx` / `EditableName.module.css`
- Modify: `api/agents.ts`, `api/chatbots.ts`, `api/sessions.ts` — update functions
- Modify: `components/AgentCard.tsx`, `components/ChatbotCard.tsx`, `components/SessionHistoryPanel.tsx`
- Modify: `pages/DashboardPage.tsx`, `pages/AgentDetailPage.tsx`, `pages/ChatbotDetailPage.tsx` — wire reload callbacks

**Interfaces:**
- Consumes: `PATCH /agents/{id}`, `PATCH /agents/{id}/sessions/{id}`, `PATCH /chatbots/{id}`, `PATCH /chatbots/{id}/sessions/{id}` (Tasks 7–8, backend); `api.patch` (Task 11).
- Produces: `EditableName` component (`{ value: string, onSave: (newValue: string) => Promise<void> }`); `updateAgentName(agentId, name)`, `updateChatbotName(chatbotId, name)`, `updateSessionLabel(agentId, sessionId, label)`, `updateChatbotSessionLabel(chatbotId, sessionId, label)`; `SessionHistoryPanel`'s new `onRename?: (session: SessionSummary, newLabel: string) => Promise<void>` prop; `AgentCard`/`ChatbotCard`'s new `onRenamed: () => void` prop.

- [ ] **Step 1: Create `components/EditableName.tsx`**

```tsx
import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import styles from './EditableName.module.css';

interface EditableNameProps {
  value: string;
  onSave: (newValue: string) => Promise<void>;
}

export function EditableName({ value, onSave }: EditableNameProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEdit(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDraft(value);
    setError(null);
    setEditing(true);
  }

  function cancel(e: MouseEvent | KeyboardEvent) {
    e.preventDefault();
    e.stopPropagation();
    setError(null);
    setEditing(false);
  }

  async function commit() {
    const trimmed = draft.trim();
    if (!trimmed || trimmed === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(trimmed);
      setEditing(false);
    } catch {
      setError('Rename failed');
    } finally {
      setSaving(false);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      commit();
    }
    if (e.key === 'Escape') {
      cancel(e);
    }
  }

  if (editing) {
    return (
      <span className={styles.editing}>
        <input
          className={styles.input}
          autoFocus
          value={draft}
          disabled={saving}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          onClick={(e) => e.stopPropagation()}
        />
        <button type="button" className={styles.pencil} disabled={saving} onClick={(e) => { e.preventDefault(); e.stopPropagation(); commit(); }} aria-label="Save">
          ✓
        </button>
        <button type="button" className={styles.pencil} disabled={saving} onClick={cancel} aria-label="Cancel">
          ✕
        </button>
        {error && <span className={styles.error}>{error}</span>}
      </span>
    );
  }

  return (
    <span className={styles.view}>
      {value}
      <button type="button" className={styles.pencil} aria-label="Rename" onClick={startEdit}>
        ✎
      </button>
    </span>
  );
}
```

(`e.preventDefault()` on the pencil/save/cancel buttons is what stops the surrounding `<Link>` from navigating when `EditableName` sits inside a card link — React Router's `Link` checks `event.defaultPrevented` before navigating.)

- [ ] **Step 2: Create `components/EditableName.module.css`**

```css
.view {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.editing {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.input {
  width: 160px;
  max-width: 100%;
  padding: 4px 8px;
  font-size: 14px;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
  background: var(--color-canvas);
  color: var(--color-text);
}
.input:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 1px;
}

.pencil {
  background: transparent;
  border: none;
  padding: 2px 4px;
  color: var(--color-text-muted);
  font-size: 13px;
  line-height: 1;
  border-radius: var(--radius);
}
.pencil:hover:not(:disabled) {
  color: var(--color-accent);
  background: var(--color-surface-raised);
}
.pencil:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error {
  font-size: 12px;
  color: var(--color-danger-strong);
}
```

- [ ] **Step 3: Add the update API functions**

Read `frontend/src/api/agents.ts`, then replace the whole file:

```typescript
import { api } from './client';
import type { AgentCreated, AgentSummary } from './types';

export function listAgents() {
  return api.get<AgentSummary[]>('/agents');
}

export function createAgent(name: string, systemPrompt?: string) {
  return api.post<AgentCreated>('/agents', { name, system_prompt: systemPrompt });
}

export function updateAgentName(agentId: string, name: string) {
  return api.patch<AgentCreated>(`/agents/${agentId}`, { name });
}
```

Read `frontend/src/api/chatbots.ts`. Append these two functions to the end of the file:

```typescript
export function updateChatbotName(chatbotId: string, name: string) {
  return api.patch<ChatbotSummary & { user_id: string }>(`/chatbots/${chatbotId}`, { name });
}

export function updateChatbotSessionLabel(chatbotId: string, sessionId: string, label: string) {
  return api.patch<{ id: string; label: string | null; created_at: string }>(
    `/chatbots/${chatbotId}/sessions/${sessionId}`,
    { label },
  );
}
```

Read `frontend/src/api/sessions.ts`. Append:

```typescript
export function updateSessionLabel(agentId: string, sessionId: string, label: string) {
  return api.patch<{ id: string; label: string | null; created_at: string }>(
    `/agents/${agentId}/sessions/${sessionId}`,
    { label },
  );
}
```

- [ ] **Step 4: Wire rename into `AgentCard` and `ChatbotCard`**

Read `frontend/src/components/AgentCard.tsx`, then replace the whole file:

```tsx
import { Link } from 'react-router-dom';
import type { AgentSummary } from '../api/types';
import { updateAgentName } from '../api/agents';
import { EditableName } from './EditableName';
import styles from './Card.module.css';

export function AgentCard({ agent, onRenamed }: { agent: AgentSummary; onRenamed: () => void }) {
  return (
    <Link to={`/agents/${agent.agent_id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        <EditableName
          value={agent.name}
          onSave={async (newName) => {
            await updateAgentName(agent.agent_id, newName);
            onRenamed();
          }}
        />
      </p>
      <p className={styles.meta}>{agent.agent_id}</p>
    </Link>
  );
}
```

Read `frontend/src/components/ChatbotCard.tsx`, then replace the whole file:

```tsx
import { Link } from 'react-router-dom';
import type { ChatbotSummary } from '../api/types';
import { updateChatbotName } from '../api/chatbots';
import { EditableName } from './EditableName';
import styles from './Card.module.css';

export function ChatbotCard({ chatbot, onRenamed }: { chatbot: ChatbotSummary; onRenamed: () => void }) {
  return (
    <Link to={`/chatbots/${chatbot.id}`} className={styles.card}>
      <p className={styles.name}>
        <span className={styles.dot} />
        <EditableName
          value={chatbot.name}
          onSave={async (newName) => {
            await updateChatbotName(chatbot.id, newName);
            onRenamed();
          }}
        />
      </p>
      <p className={styles.meta}>{chatbot.orchestrator_id}</p>
    </Link>
  );
}
```

- [ ] **Step 5: Pass `onRenamed` from `DashboardPage`**

Read `frontend/src/pages/DashboardPage.tsx`, then find the two `.map(...)` calls and update them:

```tsx
            {agents.data.map((agent) => (
              <AgentCard key={agent.id} agent={agent} onRenamed={agents.reload} />
            ))}
```

```tsx
            {chatbots.data.map((chatbot) => (
              <ChatbotCard key={chatbot.id} chatbot={chatbot} onRenamed={chatbots.reload} />
            ))}
```

- [ ] **Step 6: Wire rename into `SessionHistoryPanel`**

Read `frontend/src/components/SessionHistoryPanel.tsx`, then replace the whole file:

```tsx
import type { SessionSummary } from '../api/types';
import { ConfirmButton } from './ConfirmButton';
import { EditableName } from './EditableName';
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
  onRename?: (session: SessionSummary, newLabel: string) => Promise<void>;
}

export function SessionHistoryPanel({ loading, error, sessions, onContinue, onDelete, onRename }: SessionHistoryPanelProps) {
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
            <p className={styles.label}>
              {onRename ? (
                <EditableName value={session.label || 'Untitled session'} onSave={(newLabel) => onRename(session, newLabel)} />
              ) : (
                session.label || 'Untitled session'
              )}
            </p>
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

- [ ] **Step 7: Wire `onRename` in `AgentDetailPage` and `ChatbotDetailPage`**

Read `frontend/src/pages/AgentDetailPage.tsx`. Add the import:

```tsx
import { listSessions, getSessionMessages, deleteSession, attachDocumentToSession, updateSessionLabel } from '../api/sessions';
```

Add a handler function (alongside the existing `handleDeleteSession`/`handleContinueSession`):

```tsx
  async function handleRenameSession(session: SessionSummary, newLabel: string) {
    await updateSessionLabel(agentId!, session.session_id, newLabel);
    sessions.reload();
  }
```

Pass it to the panel:

```tsx
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={handleContinueSession}
          onDelete={(session) => handleDeleteSession(session.session_id)}
          onRename={handleRenameSession}
        />
```

Read `frontend/src/pages/ChatbotDetailPage.tsx`. Add the import:

```tsx
import {
  getChatbot,
  addChatbotAgent,
  deleteChatbotAgent,
  deleteChatbot,
  chatWithChatbot,
  listChatbotSessions,
  getChatbotSessionMessages,
  updateChatbotSessionLabel,
} from '../api/chatbots';
```

Add a handler function:

```tsx
  async function handleRenameSession(session: SessionSummary, newLabel: string) {
    await updateChatbotSessionLabel(chatbotId!, session.session_id, newLabel);
    sessions.reload();
  }
```

Pass it to the panel:

```tsx
        <SessionHistoryPanel
          loading={sessions.loading}
          error={sessions.error}
          sessions={sessions.data}
          onContinue={handleContinueSession}
          onRename={handleRenameSession}
        />
```

- [ ] **Step 8: Type-check, build, and manually verify in the browser**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend && npx tsc --noEmit && npm run build
```

Expected: both exit 0.

With the backend (main checkout, port 8000) and frontend dev server (this worktree, port 5173) both running as in Task 11 Step 9: on the dashboard, hover an agent or chatbot card and click the pencil icon next to its name — confirm it does **not** navigate, lets you edit inline, and Enter/✓ saves (card reflects the new name after the list reloads) while Escape/✕ cancels without saving. Open an agent or chatbot detail page with at least one past session and confirm the same rename behavior works on a session row's label.

- [ ] **Step 9: Commit**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend
git add src/components/EditableName.tsx src/components/EditableName.module.css src/api/agents.ts src/api/chatbots.ts src/api/sessions.ts src/components/AgentCard.tsx src/components/ChatbotCard.tsx src/components/SessionHistoryPanel.tsx src/pages/DashboardPage.tsx src/pages/AgentDetailPage.tsx src/pages/ChatbotDetailPage.tsx
git commit -m "feat: add inline rename for agent cards, chatbot cards, and session labels"
```

---

### Task 13: Frontend — model dropdown on create-agent and create-chatbot forms

**Files:** (all under the `react-frontend` worktree's `frontend/src/`)
- Create: `lib/models.ts`
- Modify: `api/agents.ts`, `api/chatbots.ts` — thread `model` through create calls
- Modify: `pages/CreateAgentPage.tsx`, `pages/CreateChatbotPage.tsx` — add the dropdown

**Interfaces:**
- Consumes: `model` field on `POST /agents` / `POST /chatbots` (Task 9, backend).
- Produces: `AVAILABLE_MODELS: { value: string; label: string }[]`; `createAgent(name, systemPrompt?, model?)`; `createChatbot(name, agentName, roleDescription, systemPrompt?, model?)`.

- [ ] **Step 1: Create `lib/models.ts`**

```typescript
// Not an exhaustive Powabase-provided list -- Powabase's /api/agents accepts any
// LiteLLM model id with no fixed enum. These four are what's actually usable on
// this project today: no BYOK provider keys are configured, but AI-on-us covers
// anthropic/google/openai, and each was created and run end-to-end successfully
// (verified live 2026-08-16). Leaving the dropdown at "Default" omits the field
// entirely, so Powabase's own default (gpt-5.4-mini) applies.
export interface ModelOption {
  value: string;
  label: string;
}

export const AVAILABLE_MODELS: ModelOption[] = [
  { value: '', label: 'Default (gpt-5.4-mini)' },
  { value: 'gpt-4o', label: 'GPT-4o (OpenAI)' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (Anthropic)' },
  { value: 'gemini/gemini-2.5-flash', label: 'Gemini 2.5 Flash (Google)' },
];
```

- [ ] **Step 2: Thread `model` through the create API calls**

Read `frontend/src/api/agents.ts`, then find `createAgent` and replace it:

```typescript
export function createAgent(name: string, systemPrompt?: string, model?: string) {
  return api.post<AgentCreated>('/agents', { name, system_prompt: systemPrompt, model: model || undefined });
}
```

Read `frontend/src/api/chatbots.ts`, then find `createChatbot` and replace it:

```typescript
export function createChatbot(name: string, agentName: string, roleDescription: string, systemPrompt?: string, model?: string) {
  return api.post<ChatbotCreated>('/chatbots', {
    name,
    agent_name: agentName,
    role_description: roleDescription,
    system_prompt: systemPrompt,
    model: model || undefined,
  });
}
```

- [ ] **Step 3: Add the dropdown to `CreateAgentPage`**

Read `frontend/src/pages/CreateAgentPage.tsx`, then replace the whole file:

```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createAgent } from '../api/agents';
import { describeError } from '../lib/errors';
import { AVAILABLE_MODELS } from '../lib/models';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateAgentPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [model, setModel] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const agent = await createAgent(name.trim(), systemPrompt.trim() || undefined, model || undefined);
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
        <div className="field">
          <label htmlFor="agent-model">Model (optional)</label>
          <select id="agent-model" className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            {AVAILABLE_MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !name.trim()}>
          {submitting ? 'Creating…' : 'Create agent'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Add the dropdown to `CreateChatbotPage`**

Read `frontend/src/pages/CreateChatbotPage.tsx`, then replace the whole file:

```tsx
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { createChatbot } from '../api/chatbots';
import { describeError } from '../lib/errors';
import { AVAILABLE_MODELS } from '../lib/models';
import { ErrorBanner } from '../components/ErrorBanner';
import styles from './FormPage.module.css';

export function CreateChatbotPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [agentName, setAgentName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [model, setModel] = useState('');
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
        model || undefined,
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
        <div className="field">
          <label htmlFor="chatbot-model">First agent's model (optional)</label>
          <select id="chatbot-model" className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            {AVAILABLE_MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" type="submit" disabled={submitting || !canSubmit}>
          {submitting ? 'Creating…' : 'Create chatbot'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 5: Type-check, build, and manually verify in the browser**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend && npx tsc --noEmit && npm run build
```

Expected: both exit 0.

With the backend and frontend dev server running as before: open "Create new" under "My agents", pick a non-default model from the dropdown, submit, then check the created agent actually has that model via `curl -s -H "apikey: $POWABASE_SERVICE_KEY" -H "Authorization: Bearer $POWABASE_SERVICE_KEY" $POWABASE_URL/api/agents/<agent_id>` (or the Studio agent detail view) — confirm `model` matches what was picked. Repeat for "Create new" under "My chatbots".

- [ ] **Step 6: Commit**

```bash
cd /home/william/powabase-chatbot/.worktrees/react-frontend/frontend
git add src/lib/models.ts src/api/agents.ts src/api/chatbots.ts src/pages/CreateAgentPage.tsx src/pages/CreateChatbotPage.tsx
git commit -m "feat: add model selection dropdown to create-agent and create-chatbot forms"
```
