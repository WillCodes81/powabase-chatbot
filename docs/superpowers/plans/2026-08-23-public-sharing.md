# Public Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a signed-in owner spin up a single-agent chat experience that anyone can use without an account — via a direct link or an embedded widget on another site — while every existing authenticated route, its CORS policy, and its RLS-backed ownership model stay byte-for-byte unchanged.

**Architecture:** One new authenticated call (`POST /public/agents`) creates a dedicated agent (fixed system prompt, its own permanent KB) plus a `public_shares` row keyed by a random `share_id`. Every other public route is unauthenticated and reads/writes exclusively via the Powabase **service-role key** — never the anon key + a user token — because there is no real user session to scope RLS with. Anonymous visitor identity is a client-generated `anon_session_id` (not a `user_id`), tracked in a new `public_share_sessions` table with no `user_id` column at all. Credit charges land on the **agent owner's** balance by calling the existing `acquire_credit_lock`/`deduct_user_credits`/etc. functions unchanged, just passing the service-role key in the `access_token` slot (those functions already bypass RLS with any caller — they were written key-agnostic). CORS isolation is achieved by splitting the single FastAPI `app` into two independent FastAPI apps — `main_app` (existing, unchanged CORS) and `public_app` (new, `allow_origins=["*"]`) — dispatched by a plain `Starlette` router with no middleware of its own, so the public app's permissive CORS truly is independent rather than nested inside the existing restrictive middleware.

**Tech Stack:** FastAPI 0.139, Starlette (`Mount`-based app-of-apps), Pydantic 2.13, `requests`, slowapi, Powabase (PostgREST + GoTrue + `/api/*`), React 19 + Vite 8 + react-router-dom 7 (frontend), a second Vite lib-mode build for the vanilla-JS embed widget.

**Spec:** This document — the user's phase-by-phase spec is reproduced inline at the top of each task group below; there is no separate spec file.

## Global Constraints

- Keep the `(data, status_code)` tuple return pattern for every new function in `app/powabase_client.py` — matches every existing function in that file.
- Every call touching `public_shares` (insert only) uses the **anon key + the owner's own access token**, so RLS enforces `owner_user_id = auth.uid()` — same defense-in-depth convention as `agents_registry`/`chat_sessions`.
- Every call touching `public_share_sessions`, `public_share_usage`, and every **read** of `public_shares` after creation uses the **service-role key** exclusively — there is no end-user identity on these calls, matching the existing deliberate pattern in `get_chat_session_by_token` (`app/powabase_client.py:364-377`).
- No test framework is installed (no `pytest`, no `tests/`). Every verification step in this plan runs direct `requests` calls (or plain Python function calls) against a locally running `uvicorn` server, matching every prior plan in this directory.
- The existing `main_app`'s CORS origin list, credentials setting, and every existing router's behavior must be provably unchanged after this plan — Task 3's verification checks this explicitly, not just the new behavior.
- The fixed system prompt for publicly-shared agents (Task 3) must be reproduced **exactly** as specified, character-for-character.
- The hardcoded global cap is **100,000 tokens total**, shared across every owner's public agents combined — not per-visitor, not per-owner. Precision under concurrent races is explicitly not required (rough safety net only).

## Decisions made during planning (flagging for your review)

1. **`session_context_search` stays a single tool/single endpoint.** Rather than registering a second tool or a second HTTP endpoint for publicly-shared agents, `POST /tools/session-context` (Task 6) is extended to check `public_share_sessions` as a fallback when a `session_token` isn't found in `chat_sessions`. Every agent — authenticated or public — keeps using the exact same `session_context_search` tool `ensure_session_context_tool()` already registers. This avoids a second tool registration path entirely and is the smallest change that satisfies "MUST use the existing session_context_search / lazy-KB-creation pattern." Token collision risk between the two tables is negligible (both are independent 256-bit `secrets.token_urlsafe(32)` values).
2. **The publicly-shared agent is also registered in the owner's normal `agents_registry`** (Task 3), not just in `public_shares`. This means it shows up in the owner's dashboard like any other agent, and — critically — the *existing* `DELETE /agents/{agent_id}` route is the one place agent+KB cleanup logic lives. Task 7 extends that existing route to also clean up the `public_shares`/`public_share_sessions` rows and their session KBs, so deleting the agent from the normal UI fully tears down its public share too, rather than leaving a dangling `share_id` that 404s.
3. **The "Get shareable link" button creates a brand-new, separate agent** — not a public mirror of the agent whose detail page you clicked from. This is what the spec literally describes ("creates a new standard agent with this system prompt... its own isolated permanent knowledge base"), and it's necessary: the fixed system prompt is different from whatever prompt the viewed agent has, and giving anonymous strangers tool access to an agent that already has the owner's other content in its KB would defeat the isolation this plan is otherwise built around. The button pre-fills the new agent's name as `"{current agent's name} (Public)"` for a discoverable label, but the KB and system prompt are fresh. **Confirm this matches your intent** — flagged in the final summary too.
4. **Public-route error copy never mentions the owner's billing state to the anonymous visitor.** Owner-credits-exhausted returns `503` with generic "temporarily unavailable" copy (not chat.py's `402 "Token balance exhausted. You have no tokens remaining."`, which would confusingly address "you" — the stranger — about someone else's balance). The global 100k cap returns `429`. Both are distinguishable by status code for testing but never leak billing specifics.
5. **The widget JS is built via a second Vite config in lib/IIFE mode** (`frontend/vite.widget.config.ts`) and served by a dedicated `GET /public/widget.js` route on the new public app (`FileResponse`, not `StaticFiles`, since it's a single file) — keeping the whole feature deployable from the one existing backend without standing up separate static hosting. Both the widget and the React public-share page import one shared, framework-agnostic TS module (`frontend/src/lib/publicShareClient.ts`) for the fetch/localStorage logic, so the "same experience" requirement in Phase 3 is enforced by sharing code, not by keeping two implementations in sync by hand.

---

### Task 1: Public-sharing database schema (manual Studio SQL step)

Per this project's established convention (see `docs/superpowers/plans/2026-07-23-per-user-agent-isolation.md` Task 2), DDL has no automated migration path here — it's a manual step in the Powabase Studio SQL editor, verified live afterward.

**Files:** none (pure database change)

**Interfaces:**
- Produces: `public.public_shares` (`share_id text primary key`, `owner_user_id uuid`, `agent_id uuid`, `kb_id uuid`, `source_agent_id uuid` nullable, `created_at`), RLS enabled with owner-scoped insert/select policies. `source_agent_id` is the id of the agent whose detail page the "Get shareable link" button was clicked from — Task 3 uses it to make link creation idempotent per source agent.
- Produces: `public.public_share_sessions` (`id uuid pk`, `share_id text` FK → `public_shares.share_id` `on delete cascade`, `anon_session_id text`, `session_token text`, `powabase_session_id text` nullable, `kb_id uuid` nullable, `created_at`, unique on `(share_id, anon_session_id)`), RLS enabled with **no** policies (service-role-only, matching `session_documents`-style lockdown).
- Produces: `public.public_share_usage` (single row, `id integer primary key check (id = 1)`, `tokens_used_total integer`) and RPC `public.increment_public_share_usage(p_tokens integer) returns integer`, seeded with one row `(1, 0)`. Task 2 reads/writes all three via `/rest/v1/*` and `/rest/v1/rpc/increment_public_share_usage`.

- [ ] **Step 1: Ask the user to run this SQL in the Powabase Studio SQL editor**

Project → **Studio** → **SQL Editor**, paste and run:

```sql
create table public.public_shares (
  share_id text primary key,
  owner_user_id uuid not null references auth.users,
  agent_id uuid not null,
  kb_id uuid not null,
  source_agent_id uuid,
  created_at timestamptz not null default now()
);

alter table public.public_shares enable row level security;

create policy "public_shares_insert_own" on public.public_shares
  for insert to authenticated with check (owner_user_id = auth.uid());

create policy "public_shares_select_own" on public.public_shares
  for select to authenticated using (owner_user_id = auth.uid());

create table public.public_share_sessions (
  id uuid primary key default gen_random_uuid(),
  share_id text not null references public.public_shares (share_id) on delete cascade,
  anon_session_id text not null,
  session_token text not null,
  powabase_session_id text,
  kb_id uuid,
  created_at timestamptz not null default now(),
  unique (share_id, anon_session_id)
);

alter table public.public_share_sessions enable row level security;

create table public.public_share_usage (
  id integer primary key check (id = 1),
  tokens_used_total integer not null default 0
);

insert into public.public_share_usage (id, tokens_used_total) values (1, 0);

alter table public.public_share_usage enable row level security;

create or replace function public.increment_public_share_usage(p_tokens integer)
returns integer
language sql
as $$
  update public.public_share_usage
  set tokens_used_total = tokens_used_total + p_tokens
  where id = 1
  returning tokens_used_total;
$$;

notify pgrst, 'reload schema';
```

Wait for the user to confirm they've run it before continuing to Step 2.

- [ ] **Step 2: Verify tables, RLS, and the RPC all work as intended**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key

fake_share = {
    "share_id": "verify-task1-share",
    "owner_user_id": "00000000-0000-0000-0000-000000000000",
    "agent_id": "00000000-0000-0000-0000-000000000001",
    "kb_id": "00000000-0000-0000-0000-000000000002",
}
r = requests.post(f"{BASE}/rest/v1/public_shares",
    headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"},
    json=fake_share)
print("insert public_shares via service key:", r.status_code)
assert r.status_code in (200, 201), r.text

r = requests.get(f"{BASE}/rest/v1/public_shares", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}"}, params={"share_id": "eq.verify-task1-share"})
print("read public_shares via anon key, no user token (RLS should block):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == []

fake_session = {"share_id": "verify-task1-share", "anon_session_id": "anon-abc", "session_token": "tok-abc"}
r = requests.post(f"{BASE}/rest/v1/public_share_sessions",
    headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"},
    json=fake_session)
print("insert public_share_sessions via service key:", r.status_code)
assert r.status_code in (200, 201), r.text

r = requests.post(f"{BASE}/rest/v1/rpc/increment_public_share_usage",
    headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"},
    json={"p_tokens": 42})
print("increment_public_share_usage(42):", r.status_code, r.json())
assert r.status_code == 200 and r.json() == 42

r = requests.get(f"{BASE}/rest/v1/public_share_usage", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"id": "eq.1", "select": "tokens_used_total"})
print("public_share_usage row:", r.json())
assert r.json()[0]["tokens_used_total"] == 42

# cascade delete check
r = requests.delete(f"{BASE}/rest/v1/public_shares", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"share_id": "eq.verify-task1-share"})
print("delete public_shares (should cascade sessions):", r.status_code)
r = requests.get(f"{BASE}/rest/v1/public_share_sessions", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"}, params={"share_id": "eq.verify-task1-share"})
print("orphaned sessions after cascade (expect empty):", r.json())
assert r.json() == []

# reset usage counter back to 0 so later tasks start clean
requests.patch(f"{BASE}/rest/v1/public_share_usage", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}, params={"id": "eq.1"}, json={"tokens_used_total": 0})

print("\nSCHEMA + RLS + RPC VERIFIED")
EOF
```

Expected output ends with `SCHEMA + RLS + RPC VERIFIED`. If the first insert 404s, re-run `notify pgrst, 'reload schema';` and retry.

- [ ] **Step 3:** No code changed in this task — proceed to Task 2.

---

### Task 2: `powabase_client.py` helpers for public shares, sessions, and the usage counter

**Files:**
- Modify: `app/powabase_client.py` — append all functions below.

**Interfaces:**
- Consumes: `settings.powabase_service_key`, `settings.powabase_anon_key` (existing).
- Produces: `insert_public_share_row(access_token, owner_user_id, share_id, agent_id, kb_id, source_agent_id=None) -> tuple[dict, int]`, `get_public_share(share_id) -> tuple[list, int]`, `get_public_share_by_source_agent_id(access_token, source_agent_id) -> tuple[list, int]`, `get_public_shares_for_agent(agent_id) -> tuple[list, int]`, `delete_public_share(share_id) -> tuple[dict, int]`, `get_or_create_public_share_session(share_id, anon_session_id) -> dict`, `get_public_share_session(share_id, anon_session_id) -> tuple[list, int]`, `get_public_share_session_by_token(session_token) -> tuple[list, int]`, `get_public_share_session_kb_ids(share_id) -> tuple[list, int]`, `update_public_share_session_powabase_id(share_id, anon_session_id, powabase_session_id) -> None`, `update_public_share_session_kb_id(share_id, anon_session_id, kb_id) -> None`, `get_public_share_usage_total() -> int`, `increment_public_share_usage(tokens) -> None`. Tasks 3–7 import these.

- [ ] **Step 1: Append to `app/powabase_client.py`**

```python
def insert_public_share_row(
    access_token: str, owner_user_id: str, share_id: str, agent_id: str, kb_id: str, source_agent_id: str | None = None
) -> tuple[dict, int]:
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/public_shares",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json={
            "share_id": share_id,
            "owner_user_id": owner_user_id,
            "agent_id": agent_id,
            "kb_id": kb_id,
            "source_agent_id": source_agent_id,
        },
    )
    data = response.json()
    if isinstance(data, list):
        data = data[0] if data else {}
    return data, response.status_code


def get_public_share_by_source_agent_id(access_token: str, source_agent_id: str) -> tuple[list, int]:
    """
    Owner-scoped (anon key + the CALLING owner's own access token, not the
    service key) -- RLS's existing public_shares_select_own policy
    (owner_user_id = auth.uid()) does the ownership filtering for free, the
    same way list_agent_registry_rows/get_agent_registry_entry already rely
    on RLS rather than an app-level ownership check. Used both by Task 3's
    idempotent-create check and by the GET /public/agents/by-source/{id}
    lookup route.
    """
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_shares",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"source_agent_id": f"eq.{source_agent_id}", "select": "share_id,agent_id,created_at"},
    )
    return response.json(), response.status_code


def get_public_share(share_id: str) -> tuple[list, int]:
    # Service key, deliberately: an anonymous visitor's request carries no
    # end-user identity to scope this with, same reasoning as
    # get_chat_session_by_token.
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_shares",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"share_id": f"eq.{share_id}", "select": "agent_id,kb_id,owner_user_id"},
    )
    return response.json(), response.status_code


def get_public_shares_for_agent(agent_id: str) -> tuple[list, int]:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_shares",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"agent_id": f"eq.{agent_id}", "select": "share_id"},
    )
    return response.json(), response.status_code


def delete_public_share(share_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/rest/v1/public_shares",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"share_id": f"eq.{share_id}"},
    )
    if response.status_code >= 400:
        return response.json(), response.status_code
    return {}, response.status_code


def get_public_share_session(share_id: str, anon_session_id: str) -> tuple[list, int]:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={
            "share_id": f"eq.{share_id}",
            "anon_session_id": f"eq.{anon_session_id}",
            "select": "id,session_token,powabase_session_id,kb_id",
        },
    )
    return response.json(), response.status_code


def get_or_create_public_share_session(share_id: str, anon_session_id: str) -> dict:
    """
    Get-or-create keyed by the (share_id, anon_session_id) unique constraint --
    same ignore-duplicates-then-reselect race handling as ensure_user_credits_row,
    since two concurrent first requests from the same freshly-generated
    anon_session_id (e.g. a double-click) must not create two rows with two
    different session_tokens for the same visitor.
    """
    existing, status_code = get_public_share_session(share_id, anon_session_id)
    if status_code < 400 and existing:
        return existing[0]

    session_token = secrets.token_urlsafe(32)
    response = requests.post(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=ignore-duplicates,return=representation",
        },
        json={"share_id": share_id, "anon_session_id": anon_session_id, "session_token": session_token},
    )
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]

    existing, status_code = get_public_share_session(share_id, anon_session_id)
    return existing[0]


def get_public_share_session_by_token(session_token: str) -> tuple[list, int]:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"session_token": f"eq.{session_token}", "select": "kb_id"},
    )
    return response.json(), response.status_code


def get_public_share_session_kb_ids(share_id: str) -> tuple[list, int]:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"share_id": f"eq.{share_id}", "select": "kb_id", "kb_id": "not.is.null"},
    )
    return response.json(), response.status_code


def update_public_share_session_powabase_id(share_id: str, anon_session_id: str, powabase_session_id: str) -> None:
    requests.patch(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        params={"share_id": f"eq.{share_id}", "anon_session_id": f"eq.{anon_session_id}"},
        json={"powabase_session_id": powabase_session_id},
    )


def update_public_share_session_kb_id(share_id: str, anon_session_id: str, kb_id: str) -> None:
    requests.patch(
        f"{settings.powabase_url}/rest/v1/public_share_sessions",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        params={"share_id": f"eq.{share_id}", "anon_session_id": f"eq.{anon_session_id}"},
        json={"kb_id": kb_id},
    )


def get_public_share_usage_total() -> int:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/public_share_usage",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        params={"id": "eq.1", "select": "tokens_used_total"},
    )
    rows = response.json()
    return rows[0]["tokens_used_total"] if rows else 0


def increment_public_share_usage(tokens: int) -> None:
    requests.post(
        f"{settings.powabase_url}/rest/v1/rpc/increment_public_share_usage",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"p_tokens": tokens},
    )
```

`secrets` is already imported at the top of `chat.py` but not `powabase_client.py` — add `import secrets` to the existing import block at the top of the file (alongside `import json`, `import logging`, `import time`).

- [ ] **Step 2: Verify directly against the tables from Task 1**

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
from app.powabase_client import (
    insert_public_share_row, get_public_share, get_or_create_public_share_session,
    get_public_share_session_by_token, update_public_share_session_kb_id,
    get_public_share_usage_total, increment_public_share_usage,
)
from app.config import settings
import requests

BASE, ANON = settings.powabase_url, settings.powabase_anon_key
creds = {"email": "task2-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
body = r.json()
token, user_id = body["access_token"], body["user"]["id"]

row, status = insert_public_share_row(token, user_id, "task2-share", "00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")
print("insert_public_share_row:", status, row)
assert status in (200, 201)

fetched, status = get_public_share("task2-share")
print("get_public_share:", status, fetched)
assert status == 200 and fetched[0]["owner_user_id"] == user_id

sess1 = get_or_create_public_share_session("task2-share", "anon-1")
sess2 = get_or_create_public_share_session("task2-share", "anon-1")
print("get_or_create idempotent:", sess1["session_token"] == sess2["session_token"])
assert sess1["session_token"] == sess2["session_token"]

sess_other = get_or_create_public_share_session("task2-share", "anon-2")
print("different anon_session_id -> different token:", sess1["session_token"] != sess_other["session_token"])
assert sess1["session_token"] != sess_other["session_token"]

by_token, status = get_public_share_session_by_token(sess1["session_token"])
print("lookup by token:", status, by_token)
assert status == 200 and len(by_token) == 1

update_public_share_session_kb_id("task2-share", "anon-1", "00000000-0000-0000-0000-000000000003")
refetched, _ = get_public_share_session_by_token(sess1["session_token"])
assert refetched[0]["kb_id"] == "00000000-0000-0000-0000-000000000003"
print("kb_id update persisted:", refetched[0]["kb_id"])

before = get_public_share_usage_total()
increment_public_share_usage(10)
after = get_public_share_usage_total()
print("usage counter:", before, "->", after)
assert after == before + 10

requests.delete(f"{BASE}/rest/v1/public_shares", headers={"apikey": settings.powabase_service_key, "Authorization": f"Bearer {settings.powabase_service_key}"}, params={"share_id": "eq.task2-share"})
requests.patch(f"{BASE}/rest/v1/public_share_usage", headers={"apikey": settings.powabase_service_key, "Authorization": f"Bearer {settings.powabase_service_key}", "Content-Type": "application/json"}, params={"id": "eq.1"}, json={"tokens_used_total": 0})

print("\nTASK 2 HELPERS VERIFIED")
EOF
```

Expected output ends with `TASK 2 HELPERS VERIFIED`.

- [ ] **Step 3: Commit**

```bash
git add app/powabase_client.py
git commit -m "feat: add public-share DB helper functions"
```

---

### Task 3: CORS-isolated public app + `POST /public/agents`

**Files:**
- Modify: `app/main.py` — split into `create_app()` (unchanged) + new `create_public_app()`, dispatched via `Starlette`/`Mount`.
- Create: `app/routes/public.py` — the public router, starting with `POST /public/agents`.
- Modify: `app/powabase_client.py` — none needed (Task 2 already covers this route's needs; `create_knowledge_base`, `create_agent`, `link_agent_knowledge_base`, `ensure_session_context_tool`, `assign_tool_to_agent`, `insert_agent_registry_row` all already exist).

**Interfaces:**
- Consumes: `app.deps.get_current_user`, `app.deps.AuthedUser`; `insert_public_share_row`, `get_public_share`, `get_public_share_by_source_agent_id` (Task 2); every function listed above from `powabase_client.py` (all pre-existing).
- Produces: `PUBLIC_SHARE_SYSTEM_PROMPT: str` (module constant in `app/routes/public.py`) and `router` (`APIRouter(tags=["public"])`, **no path prefix** — the prefix comes from where it's mounted). `POST /public/agents` request body `{name: str, source_agent_id?: str}`, response `{share_id, agent_id, name, created_at}` — idempotent per `source_agent_id` (see Step 2). `GET /public/agents/by-source/{source_agent_id}` (authenticated), response `{share_id, agent_id, created_at}` or `404` if none exists yet. Tasks 4–7 add more routes to this same `router`.

- [ ] **Step 1: Rewrite `app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.applications import Starlette
from starlette.routing import Mount

from app.rate_limit import limiter
from app.routes.agents import router as agents_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.chatbots import router as chatbots_router
from app.routes.credits import router as credits_router
from app.routes.ingest import router as ingest_router
from app.routes.public import router as public_router
from app.routes.sessions import router as sessions_router
from app.routes.tools import router as tools_router


def create_app() -> FastAPI:
    app = FastAPI(title="Powabase RAG Chatbot", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://ec2-3-128-189-163.us-east-2.compute.amazonaws.com",],
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


def create_public_app() -> FastAPI:
    """
    A fully separate FastAPI app for /public/* -- not a router mounted onto
    the main app. Starlette middleware wraps the whole ASGI app it's added
    to, including anything mounted beneath it, and intercepts CORS
    preflight before routing even runs -- so a second CORSMiddleware on a
    sub-router mounted under `app` would still be gated by `app`'s own
    restrictive origin list first. Two independent FastAPI apps, dispatched
    by a bare Starlette router with no middleware of its own (see `app`
    below), is the only way to give /public/* a genuinely independent CORS
    policy without touching main_app's.
    """
    public_app = FastAPI(title="Powabase RAG Chatbot -- Public Sharing", version="1.0.0")

    public_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    public_app.state.limiter = limiter
    public_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    public_app.add_middleware(SlowAPIMiddleware)

    public_app.include_router(public_router)
    return public_app


main_app = create_app()
public_app = create_public_app()

# Order matters: /public must be matched before the catch-all "/" mount.
app = Starlette(routes=[
    Mount("/public", app=public_app),
    Mount("/", app=main_app),
])
```

- [ ] **Step 2: Create `app/routes/public.py`**

```python
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    ensure_session_context_tool,
    get_public_share_by_source_agent_id,
    insert_agent_registry_row,
    insert_public_share_row,
    link_agent_knowledge_base,
)
from app.validation import NonEmptyStr

router = APIRouter(tags=["public"])

PUBLIC_SHARE_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's questions clearly and directly.\n\n"
    "If the user asks about a topic that might be covered by your knowledge base, always "
    "search it before answering -- do not assume you lack the answer without checking first.\n\n"
    "If the user has uploaded a document to this specific conversation, always search it "
    "when their question could plausibly relate to that document's contents -- do not ask "
    "them to re-paste or re-upload it if it may already be available to you.\n\n"
    "Never claim you don't have access to something without first attempting to search for "
    "it using your available tools."
)


class CreatePublicAgentRequest(BaseModel):
    name: NonEmptyStr
    source_agent_id: str | None = None


@router.post("/agents")
def create_public_agent_route(req: CreatePublicAgentRequest, user: AuthedUser = Depends(get_current_user)):
    """
    The ONLY authenticated call in the public-sharing feature. Creates a
    brand-new agent -- its own fresh KB, the fixed public-share system
    prompt -- not a public mirror of any existing agent, so a stranger
    chatting via the share link never gets tool access to the owner's other
    agents' content. Registered in agents_registry too (same as every other
    agent) so it appears in the owner's normal dashboard and DELETE
    /agents/{agent_id} (extended in a later task) is the one place its
    full lifecycle -- including the public share -- gets torn down.

    Idempotent per source_agent_id: if the caller already has a public
    share whose source_agent_id matches, that share is returned as-is
    instead of spinning up a second live Agent+KB every time the "Get
    shareable link" button is clicked (or the page is reloaded). Only
    creates fresh resources the first time a given source agent is shared.
    """
    if req.source_agent_id:
        existing, status_code = get_public_share_by_source_agent_id(user.access_token, req.source_agent_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=existing)
        if existing:
            share = existing[0]
            # `name` reflects this request, not necessarily the name stored
            # at original creation time -- callers that need the
            # authoritative name already have it locally (it's the agent
            # they're viewing), so this isn't worth an extra registry fetch.
            return {"share_id": share["share_id"], "agent_id": share["agent_id"], "name": req.name, "created_at": share["created_at"]}

    kb_data, status_code = create_knowledge_base(f"{req.name}-{user.id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(req.name, PUBLIC_SHARE_SYSTEM_PROMPT, None)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_data)
    agent_id = agent_data["id"]

    _, status_code = link_agent_knowledge_base(agent_id, kb_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to link knowledge base to new public agent")

    tool_id = ensure_session_context_tool()
    _, status_code = assign_tool_to_agent(agent_id, tool_id, SESSION_CONTEXT_TOOL_NAME)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to attach session-context tool to new public agent")

    registry_row, status_code = insert_agent_registry_row(user.access_token, user.id, agent_id, kb_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)

    share_id = secrets.token_urlsafe(16)
    share_row, status_code = insert_public_share_row(user.access_token, user.id, share_id, agent_id, kb_id, req.source_agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=share_row)

    return {"share_id": share_id, "agent_id": agent_id, "name": req.name, "created_at": registry_row["created_at"]}


@router.get("/agents/by-source/{source_agent_id}")
def get_public_share_by_source_route(source_agent_id: str, user: AuthedUser = Depends(get_current_user)):
    """Lets the agent detail page find an already-created share for the
    agent it's viewing, without creating a new one."""
    rows, status_code = get_public_share_by_source_agent_id(user.access_token, source_agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=rows)
    if not rows:
        raise HTTPException(status_code=404, detail="No public share exists for this agent yet")
    share = rows[0]
    return {"share_id": share["share_id"], "agent_id": share["agent_id"], "created_at": share["created_at"]}
```

- [ ] **Step 3: Restart the server and verify both CORS policies and the new route**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

APP = "http://127.0.0.1:8000"
BASE, ANON = settings.powabase_url, settings.powabase_anon_key

# 1. Existing route's CORS is untouched: an origin NOT on the fixed allowlist
#    gets no Access-Control-Allow-Origin header on a preflight to an existing route.
r = requests.options(f"{APP}/agents", headers={
    "Origin": "https://evil.example.com",
    "Access-Control-Request-Method": "GET",
})
print("existing-route preflight from disallowed origin, ACAO header:", r.headers.get("access-control-allow-origin"))
assert r.headers.get("access-control-allow-origin") is None

# 2. Existing route's CORS still allows the known dev origin.
r = requests.options(f"{APP}/agents", headers={
    "Origin": "http://localhost:5173",
    "Access-Control-Request-Method": "GET",
})
print("existing-route preflight from allowed origin, ACAO header:", r.headers.get("access-control-allow-origin"))
assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

# 3. New public route allows ANY origin.
r = requests.options(f"{APP}/public/agents", headers={
    "Origin": "https://some-random-site.example.com",
    "Access-Control-Request-Method": "POST",
})
print("public-route preflight from arbitrary origin, ACAO header:", r.headers.get("access-control-allow-origin"))
assert r.headers.get("access-control-allow-origin") == "https://some-random-site.example.com"

# 4. POST /public/agents requires auth.
r = requests.post(f"{APP}/public/agents", json={"name": "no-auth-test"})
print("POST /public/agents with no auth:", r.status_code)
assert r.status_code == 401

# 5. POST /public/agents works when authenticated, creates share + registry row.
creds = {"email": "task3-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task3 Public Agent"})
print("POST /public/agents authenticated:", r.status_code, r.json())
assert r.status_code == 200
body = r.json()
assert body["share_id"] and body["agent_id"] and body["name"] == "Task3 Public Agent"

r = requests.get(f"{APP}/agents", headers={"Authorization": f"Bearer {token}"})
names = [a["name"] for a in r.json()]
print("appears in owner's normal agent list:", "Task3 Public Agent" in names)
assert "Task3 Public Agent" in names

# 6. Idempotency: calling POST /public/agents again with the same
#    source_agent_id returns the SAME share/agent instead of creating new ones.
source_agent_id = body["agent_id"]
r2 = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task3 Public Agent", "source_agent_id": source_agent_id})
print("second call with same source_agent_id:", r2.status_code, r2.json())
assert r2.status_code == 200
assert r2.json()["share_id"] == body["share_id"]
assert r2.json()["agent_id"] == body["agent_id"]

r3 = requests.get(f"{APP}/agents", headers={"Authorization": f"Bearer {token}"})
assert len([a for a in r3.json() if a["name"] == "Task3 Public Agent"]) == 1, "idempotent call must not create a second agent"

# 7. GET /public/agents/by-source/{id} finds the same share.
r4 = requests.get(f"{APP}/public/agents/by-source/{source_agent_id}", headers={"Authorization": f"Bearer {token}"})
print("GET by-source:", r4.status_code, r4.json())
assert r4.status_code == 200 and r4.json()["share_id"] == body["share_id"]

# 8. GET /public/agents/by-source/{id} for an agent with no share yet -> 404.
r5 = requests.get(f"{APP}/public/agents/by-source/00000000-0000-0000-0000-000000000099", headers={"Authorization": f"Bearer {token}"})
print("GET by-source, no share exists:", r5.status_code)
assert r5.status_code == 404

print("\nTASK 3 CORS SPLIT + ROUTE VERIFIED")
EOF
```

Expected output ends with `TASK 3 CORS SPLIT + ROUTE VERIFIED`. If step 1 fails (an ACAO header appears), the CORS split didn't take — re-check `Mount` ordering in `app/main.py`.

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/routes/public.py
git commit -m "feat: split app into CORS-isolated main/public apps, add POST /public/agents"
```

---

### Task 4: `POST /public/{share_id}/chat`

**Files:**
- Modify: `app/routes/public.py` — add the chat route and its context-override builder.

**Interfaces:**
- Consumes: `get_public_share`, `get_or_create_public_share_session`, `update_public_share_session_powabase_id`, `get_public_share_usage_total`, `increment_public_share_usage` (Task 2); `run_agent`, `get_session_messages`, `ensure_user_credits_row`, `deduct_user_credits` from `powabase_client.py`; `user_credit_lock`, `deduct_credits_logged` from `app/credit_lock.py`; `limiter` from `app.rate_limit`; `get_remote_address` from `slowapi.util` (all pre-existing, called with the service-role key in place of a real access token).
- Produces: `PUBLIC_TOKEN_CAP = 100_000` (module constant); `POST /public/{share_id}/chat`, body `{message: str, anon_session_id: str}`, response `{content: str}`. `404` unknown share, `429` global cap reached **or** IP rate-limited, `503` owner's balance exhausted. Rate-limited at `10/minute` per IP (see below — the existing `limiter`'s default key function reads the `Authorization` header, which anonymous public requests never send, so every visitor would otherwise share one bucket keyed on `None`; this route needs its own explicit IP-keyed limit).

- [ ] **Step 1: Add to `app/routes/public.py`**

```python
from fastapi import Request
from slowapi.util import get_remote_address

from app.credit_lock import deduct_credits_logged, user_credit_lock
from app.powabase_client import (
    ensure_user_credits_row,
    get_or_create_public_share_session,
    get_public_share,
    get_public_share_usage_total,
    get_session_messages,
    increment_public_share_usage,
    run_agent,
    update_public_share_session_powabase_id,
)
from app.config import settings
from app.rate_limit import limiter

PUBLIC_TOKEN_CAP = 100_000


class PublicChatRequest(BaseModel):
    message: NonEmptyStr
    anon_session_id: NonEmptyStr


def _build_public_context_override(powabase_session_id: str | None, session_token: str) -> str:
    parts = [
        "[Session tool context]\n"
        f"Your session_token for the session_context_search tool in this conversation is: {session_token}\n"
        "Always pass this exact value as the session_token argument when calling session_context_search. "
        "Never invent, guess, or omit it."
    ]

    if powabase_session_id:
        messages_data, status_code = get_session_messages(powabase_session_id)
        if status_code < 400:
            transcript = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages_data.get("messages", []))
            if transcript:
                parts.append(f"[Prior conversation in this session]\n{transcript}")

    return "\n\n".join(parts)


@router.post("/{share_id}/chat")
@limiter.limit("10/minute", key_func=get_remote_address)
def public_chat_route(request: Request, share_id: str, req: PublicChatRequest):
    share_rows, status_code = get_public_share(share_id)
    if status_code >= 400 or not share_rows:
        raise HTTPException(status_code=404, detail="Public share not found")
    share = share_rows[0]
    agent_id, owner_user_id = share["agent_id"], share["owner_user_id"]

    if get_public_share_usage_total() >= PUBLIC_TOKEN_CAP:
        raise HTTPException(status_code=429, detail="This public sharing feature has reached its usage limit for now.")

    session = get_or_create_public_share_session(share_id, req.anon_session_id)
    context_override = _build_public_context_override(session.get("powabase_session_id"), session["session_token"])

    # Charges land on the AGENT OWNER's balance, not the anonymous visitor's --
    # these functions take access_token as a plain parameter rather than
    # hardcoding the caller's own token, so passing the service-role key here
    # (which bypasses the `auth.uid() = user_id` RLS check entirely) lets them
    # act "as" the owner without the owner being present in this request at all.
    service_key = settings.powabase_service_key

    # This call outside the lock looks redundant with the one right below it
    # inside the lock, but it isn't: acquire_credit_lock (in user_credit_lock)
    # acquires by conditionally UPDATE-ing the user_credits row WHERE
    # user_id = owner_user_id -- a public share for an owner who has never
    # triggered row creation any other way (never called their own /chat or
    # /me/credits) has zero matching rows, so the lock would have nothing to
    # match and acquire_credit_lock would return False on every attempt until
    # it times out and raises 429. This mirrors chat.py's identical
    # pre-lock ensure_user_credits_row call and comment -- do not remove it.
    ensure_user_credits_row(service_key, owner_user_id)

    with user_credit_lock(service_key, owner_user_id):
        credits_row = ensure_user_credits_row(service_key, owner_user_id)
        if credits_row["tokens_remaining"] <= 0:
            raise HTTPException(status_code=503, detail="This assistant is temporarily unavailable. Please try again later.")

        data, status_code = run_agent(
            agent_id, req.message,
            session_id=session.get("powabase_session_id"),
            context_override=context_override,
        )
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=data)

        if not session.get("powabase_session_id"):
            update_public_share_session_powabase_id(share_id, req.anon_session_id, data["session_id"])

        usage = data.get("usage")
        if usage and usage.get("total_tokens"):
            deduct_credits_logged(service_key, owner_user_id, usage["total_tokens"])
            increment_public_share_usage(usage["total_tokens"])

    return {"content": data["content"]}
```

- [ ] **Step 2: Restart and verify**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests
from app.config import settings

APP = "http://127.0.0.1:8000"
BASE, ANON = settings.powabase_url, settings.powabase_anon_key

creds = {"email": "task4-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task4 Public Agent"})
share_id = r.json()["share_id"]

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "Say the word banana and nothing else.", "anon_session_id": "anon-task4-1"})
print("first message:", r.status_code, r.json())
assert r.status_code == 200 and "content" in r.json() and "session_id" not in r.json()

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "What word did I just ask you to say?", "anon_session_id": "anon-task4-1"})
print("second message (continuity check):", r.status_code, r.json())
assert r.status_code == 200 and "banana" in r.json()["content"].lower()

r = requests.post(f"{APP}/public/unknown-share-id/chat", json={"message": "hi", "anon_session_id": "anon-x"})
print("unknown share_id:", r.status_code)
assert r.status_code == 404

# --- credit deduction check: usage actually moves the OWNER's balance, not the visitor's ---
r = requests.get(f"{APP}/me/credits", headers={"Authorization": f"Bearer {token}"})
credits_before = r.json()
print("owner credits before:", credits_before)

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "Say the word pineapple and nothing else.", "anon_session_id": "anon-task4-credits"})
assert r.status_code == 200

r = requests.get(f"{APP}/me/credits", headers={"Authorization": f"Bearer {token}"})
credits_after = r.json()
print("owner credits after:", credits_after)
assert credits_after["tokens_remaining"] < credits_before["tokens_remaining"], "public chat usage must deduct from the OWNER's balance"
assert credits_after["tokens_used_total"] > credits_before["tokens_used_total"]

# --- global 100k cap: force it, confirm 429 with the generic message, then reset ---
SVC = settings.powabase_service_key
requests.patch(f"{BASE}/rest/v1/public_share_usage", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}, params={"id": "eq.1"}, json={"tokens_used_total": 100_000})

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "hi", "anon_session_id": "anon-task4-cap"})
print("chat call once global cap is hit:", r.status_code, r.json())
assert r.status_code == 429
assert r.json()["detail"] == "This public sharing feature has reached its usage limit for now."

requests.patch(f"{BASE}/rest/v1/public_share_usage", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}, params={"id": "eq.1"}, json={"tokens_used_total": 0})
r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "hi", "anon_session_id": "anon-task4-cap"})
print("chat call after cap reset:", r.status_code)
assert r.status_code == 200

# --- owner's own balance exhausted: 503, generic message, no billing specifics leaked to the visitor ---
zero_creds = {"email": "task4-zero-balance-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=zero_creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=zero_creds)
zero_token = r.json()["access_token"]

r = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {zero_token}"}, json={"name": "Task4 Zero Balance Agent"})
zero_share_id = r.json()["share_id"]

# Establish the user_credits row (same way the rest of the app does, via
# /me/credits) then zero it out directly with the service key.
requests.get(f"{APP}/me/credits", headers={"Authorization": f"Bearer {zero_token}"})
zero_user_id = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {zero_token}"}).json()["id"]
requests.patch(f"{BASE}/rest/v1/user_credits", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}, params={"user_id": f"eq.{zero_user_id}"}, json={"tokens_remaining": 0})

r = requests.post(f"{APP}/public/{zero_share_id}/chat", json={"message": "hi", "anon_session_id": "anon-task4-zero"})
print("chat call when owner's balance is 0:", r.status_code, r.json())
assert r.status_code == 503
detail = r.json()["detail"]
assert detail == "This assistant is temporarily unavailable. Please try again later."
detail_lower = detail.lower()
assert "credit" not in detail_lower and "balance" not in detail_lower and "token" not in detail_lower, "must not leak billing specifics to an anonymous visitor"

print("\nTASK 4 PUBLIC CHAT VERIFIED")
EOF
```

Expected output ends with `TASK 4 PUBLIC CHAT VERIFIED`. (The continuity assertion depends on the model actually remembering — if it fails only on wording, re-run once before treating it as a real bug; the important structural checks are the status codes and the missing `session_id` key.)

- [ ] **Step 3: Commit**

```bash
git add app/routes/public.py
git commit -m "feat: add POST /public/{share_id}/chat, charged to the agent owner"
```

---

### Task 5: `POST /public/{share_id}/sessions/{anon_session_id}/attach-document`

**Files:**
- Modify: `app/routes/public.py` — add the attach-document route.

**Interfaces:**
- Consumes: `get_public_share`, `get_or_create_public_share_session`, `update_public_share_session_kb_id` (Task 2); `create_knowledge_base`, `upload_and_resolve_source_id`, `wait_for_source_extraction`, `add_source_to_kb` (pre-existing, same functions `sessions.py`'s `attach_document_route` already uses); `limiter`, `get_remote_address` (Task 4 — same IP-keyed rate limit rationale applies here).
- Produces: `POST /public/{share_id}/sessions/{anon_session_id}/attach-document`, multipart `file`, response `{kb_id, source_id, filename, ...}` — same shape as the existing authenticated attach-document routes. Rate-limited at `10/minute` per IP, same as Task 4's chat route.

- [ ] **Step 1: Add to `app/routes/public.py`**

```python
from fastapi import File, UploadFile
from app.powabase_client import (
    add_source_to_kb,
    update_public_share_session_kb_id,
    upload_and_resolve_source_id,
    wait_for_source_extraction,
)


@router.post("/{share_id}/sessions/{anon_session_id}/attach-document")
@limiter.limit("10/minute", key_func=get_remote_address)
def public_attach_document_route(request: Request, share_id: str, anon_session_id: str, file: UploadFile = File(...)):
    """
    Mirrors sessions.py's attach_document_route exactly, but keyed by
    anon_session_id instead of a real user's session row -- this is what
    isolates one anonymous visitor's document from a different visitor
    using the same public share_id (see Task 6's live cross-session
    verification).
    """
    share_rows, status_code = get_public_share(share_id)
    if status_code >= 400 or not share_rows:
        raise HTTPException(status_code=404, detail="Public share not found")

    session = get_or_create_public_share_session(share_id, anon_session_id)
    kb_id = session.get("kb_id")
    if not kb_id:
        kb_data, status_code = create_knowledge_base(f"public-session-{share_id}-{anon_session_id}")
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_data)
        kb_id = kb_data["id"]
        update_public_share_session_kb_id(share_id, anon_session_id, kb_id)

    file_bytes = file.file.read()

    source_id, error = upload_and_resolve_source_id(file_bytes, file.filename)
    if error:
        error_data, error_status = error
        raise HTTPException(status_code=error_status, detail=error_data)

    data, status_code = wait_for_source_extraction(source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    extraction_status = data["extraction_status"]
    if extraction_status != "extracted":
        raise HTTPException(
            status_code=422,
            detail=f"Document extraction ended in status '{extraction_status}', cannot index",
        )

    index_data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=index_data)

    return {"kb_id": kb_id, "source_id": source_id, "filename": file.filename, **index_data}
```

- [ ] **Step 2: Restart and verify**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests, io
from app.config import settings

APP = "http://127.0.0.1:8000"
BASE, ANON = settings.powabase_url, settings.powabase_anon_key

creds = {"email": "task5-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task5 Public Agent"})
share_id = r.json()["share_id"]

doc = io.BytesIO(b"The verification codeword for task 5 is ZEBRA-QUARTZ-77.")
r = requests.post(f"{APP}/public/{share_id}/sessions/anon-task5-1/attach-document", files={"file": ("codeword.txt", doc, "text/plain")})
print("attach-document:", r.status_code, r.json())
assert r.status_code == 200 and r.json()["kb_id"]

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "What is the verification codeword mentioned in my uploaded document?", "anon_session_id": "anon-task5-1"})
print("chat referencing attached doc:", r.status_code, r.json())
assert r.status_code == 200 and "zebra" in r.json()["content"].lower() and "quartz" in r.json()["content"].lower()

print("\nTASK 5 ATTACH-DOCUMENT VERIFIED")
EOF
```

Expected output ends with `TASK 5 ATTACH-DOCUMENT VERIFIED`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/public.py
git commit -m "feat: add POST /public/{share_id}/sessions/{anon_session_id}/attach-document"
```

---

### Task 6: Extend `session_context_search` to resolve public sessions + live cross-visitor isolation verification

This is the task the user flagged as needing the same rigor as every prior isolation feature — the live verification in Step 3 is the load-bearing part of this task, not a formality.

**Files:**
- Modify: `app/routes/tools.py` — fall back to `public_share_sessions` when a token isn't found in `chat_sessions`.

**Interfaces:**
- Consumes: `get_public_share_session_by_token` (Task 2).
- Produces: `POST /tools/session-context` now resolves tokens from either table transparently — no change to its request/response contract.

- [ ] **Step 1: Modify `app/routes/tools.py`**

```python
from app.powabase_client import get_chat_session_by_token, get_public_share_session_by_token, query_context_handler

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
        # Not a real user's chat session -- check whether it's an anonymous
        # public-share session instead. One tool, one endpoint, two tables:
        # see Decision 1 at the top of this plan for why this isn't a
        # second tool/endpoint.
        rows, status_code = get_public_share_session_by_token(session_token)

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

- [ ] **Step 2: Restart the server**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

- [ ] **Step 3: Live verification — two anonymous visitors, one share_id, fabricated distinctive facts, no cross-contamination**

This plants a different, made-up fact in each of two anonymous sessions on the *same* public share link, then confirms each session's answers only ever surface its own fact — never the other session's — using the fact content itself as the check, not just status codes.

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests, io
from app.config import settings

APP = "http://127.0.0.1:8000"
BASE, ANON = settings.powabase_url, settings.powabase_anon_key

creds = {"email": "task6-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]

r = requests.post(f"{APP}/public/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": "Task6 Isolation Agent"})
share_id = r.json()["share_id"]
print("share_id:", share_id)

# Two DIFFERENT anonymous visitors on the SAME share link.
visitor_a, visitor_b = "anon-visitor-A", "anon-visitor-B"

doc_a = io.BytesIO(b"CONFIDENTIAL PROJECT CODENAME: The secret project codename is FALCON-INDIGO-91.")
doc_b = io.BytesIO(b"CONFIDENTIAL PROJECT CODENAME: The secret project codename is OTTER-CRIMSON-42.")

r = requests.post(f"{APP}/public/{share_id}/sessions/{visitor_a}/attach-document", files={"file": ("secret-a.txt", doc_a, "text/plain")})
assert r.status_code == 200, r.text
r = requests.post(f"{APP}/public/{share_id}/sessions/{visitor_b}/attach-document", files={"file": ("secret-b.txt", doc_b, "text/plain")})
assert r.status_code == 200, r.text

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "What is the secret project codename in my uploaded document?", "anon_session_id": visitor_a})
answer_a = r.json()["content"].lower()
print("visitor A's answer:", answer_a)
assert "falcon" in answer_a and "indigo" in answer_a, "visitor A should know their own codename"
assert "otter" not in answer_a and "crimson" not in answer_a, "LEAK: visitor A can see visitor B's codename"

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "What is the secret project codename in my uploaded document?", "anon_session_id": visitor_b})
answer_b = r.json()["content"].lower()
print("visitor B's answer:", answer_b)
assert "otter" in answer_b and "crimson" in answer_b, "visitor B should know their own codename"
assert "falcon" not in answer_b and "indigo" not in answer_b, "LEAK: visitor B can see visitor A's codename"

# A third, brand-new visitor on the SAME share link has no document at all.
r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "What is the secret project codename in my uploaded document?", "anon_session_id": "anon-visitor-C-fresh"})
answer_c = r.json()["content"].lower()
print("fresh visitor C's answer:", answer_c)
assert "falcon" not in answer_c and "otter" not in answer_c, "LEAK: a brand-new visitor can see either prior visitor's codename"

print("\nTASK 6 CROSS-VISITOR DOCUMENT ISOLATION VERIFIED -- no leakage in either direction")
EOF
```

Expected output ends with `TASK 6 CROSS-VISITOR DOCUMENT ISOLATION VERIFIED -- no leakage in either direction`. If any `assert` with `LEAK` in its message fires, **stop and treat it as a real isolation bug** — do not proceed to Task 7 until it's fixed and this script passes clean.

- [ ] **Step 4: Commit**

```bash
git add app/routes/tools.py
git commit -m "feat: resolve session_context_search tokens against public share sessions too"
```

---

### Task 7: Clean up public shares when their agent is deleted

**Files:**
- Modify: `app/routes/agents.py:80-114` (`delete_agent_route`) — clean up any public share before deleting the agent. No new `powabase_client.py` functions are needed — `get_public_shares_for_agent`, `get_public_share_session_kb_ids`, and `delete_public_share` were all already added in Task 2.

**Interfaces:**
- Consumes: `get_public_shares_for_agent`, `get_public_share_session_kb_ids`, `delete_public_share` (Task 2), `delete_knowledge_base` (existing).
- Produces: deleting an agent via the existing `DELETE /agents/{agent_id}` now also deletes its `public_shares` row (cascading its `public_share_sessions` rows per Task 1's `on delete cascade`) and every session KB those anonymous visitors created — no dangling `share_id` left pointing at a deleted agent.

- [ ] **Step 1: Modify `app/routes/agents.py`**

Add to the existing import block:

```python
from app.powabase_client import (
    ...  # existing imports
    delete_public_share,
    get_public_share_session_kb_ids,
    get_public_shares_for_agent,
)
```

In `delete_agent_route`, insert this block right after the existing `kb_id = agent.get("kb_id")` cleanup and before `session_kb_rows, status_code = get_agent_session_kb_ids(...)`:

```python
    share_rows, status_code = get_public_shares_for_agent(agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to look up agent's public shares")
    for share_row in share_rows:
        share_id = share_row["share_id"]
        share_session_kb_rows, sc = get_public_share_session_kb_ids(share_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to look up sessions for public share {share_id}")
        for row in share_session_kb_rows:
            _, sc = delete_knowledge_base(row["kb_id"])
            if sc >= 400:
                raise HTTPException(status_code=sc, detail=f"Failed to delete session knowledge base {row['kb_id']}")
        _, sc = delete_public_share(share_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete public share {share_id}")
```

- [ ] **Step 2: Restart and verify**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
```

```bash
cd /home/william/powabase-chatbot && .venv/bin/python3 - <<'EOF'
import requests, io
from app.config import settings

APP = "http://127.0.0.1:8000"
BASE, ANON = settings.powabase_url, settings.powabase_anon_key

creds = {"email": "task7-verify@example.com", "password": "TestPass123!"}
r = requests.post(f"{BASE}/auth/v1/signup", headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
if r.status_code >= 400:
    r = requests.post(f"{BASE}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"}, json=creds)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

r = requests.post(f"{APP}/public/agents", headers=headers, json={"name": "Task7 Public Agent"})
agent_id, share_id = r.json()["agent_id"], r.json()["share_id"]

doc = io.BytesIO(b"cleanup test document")
r = requests.post(f"{APP}/public/{share_id}/sessions/anon-task7/attach-document", files={"file": ("doc.txt", doc, "text/plain")})
assert r.status_code == 200

r = requests.delete(f"{APP}/agents/{agent_id}", headers=headers)
print("delete agent with a live public share:", r.status_code)
assert r.status_code == 200

r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": "hi", "anon_session_id": "anon-task7"})
print("chat against the now-deleted share:", r.status_code)
assert r.status_code == 404

r = requests.get(f"{BASE}/rest/v1/public_share_sessions", headers={"apikey": settings.powabase_service_key, "Authorization": f"Bearer {settings.powabase_service_key}"}, params={"share_id": f"eq.{share_id}"})
print("orphaned sessions after agent delete (expect empty):", r.json())
assert r.json() == []

print("\nTASK 7 CLEANUP-ON-DELETE VERIFIED")
EOF
```

Expected output ends with `TASK 7 CLEANUP-ON-DELETE VERIFIED`.

- [ ] **Step 3: Commit**

```bash
git add app/routes/agents.py
git commit -m "feat: clean up public shares and their session KBs when the owning agent is deleted"
```

---

### Task 8: Frontend — shared public-share client module

Framework-agnostic (no React import) so both the React public-share page (Task 10) and the vanilla-JS widget (Task 11) use the exact same fetch/localStorage logic instead of two hand-kept-in-sync copies.

**Files:**
- Create: `frontend/src/lib/publicShareClient.ts`

**Interfaces:**
- Produces: `type PublicChatMessage = { role: 'user' | 'assistant'; content: string }`; `getOrCreateAnonSessionId(shareId: string): string`; `loadCachedMessages(shareId: string): PublicChatMessage[]`; `saveCachedMessages(shareId: string, messages: PublicChatMessage[]): void`; `clearPublicSession(shareId: string): void`; `sendPublicChatMessage(apiBase: string, shareId: string, message: string): Promise<string>`; `attachPublicDocument(apiBase: string, shareId: string, file: File): Promise<{ filename: string }>`. Tasks 10 and 11 import all of these.

- [ ] **Step 1: Create the file**

```typescript
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
```

- [ ] **Step 2: Type-check**

```bash
cd /home/william/powabase-chatbot/frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/publicShareClient.ts
git commit -m "feat: add framework-agnostic public-share client module"
```

---

### Task 9: Frontend — "Get shareable link" button on `AgentDetailPage`

**Files:**
- Create: `frontend/src/api/publicShare.ts`
- Modify: `frontend/src/pages/AgentDetailPage.tsx`
- No CSS changes needed — reuses the existing `.section` and `.uploadTile` classes already in `AgentDetailPage.module.css`.

**Interfaces:**
- Consumes: `api` from `../api/client` (existing, authenticated).
- Produces: `createPublicShare(name: string, sourceAgentId: string): Promise<PublicShareCreated>`, `getPublicShareBySource(sourceAgentId: string): Promise<PublicShareCreated>` (`PublicShareCreated = { share_id: string; agent_id: string; name: string; created_at: string }`). Sets `shareId`/`shareUrl` state in `AgentDetailPage` — **both together, from either code path** (the auto-lookup on load, or the button's create handler), which is exactly what lets Task 12 render the embed snippet correctly regardless of which path populated it. Task 12 extends the same panel this task adds.

- [ ] **Step 1: Create `frontend/src/api/publicShare.ts`**

```typescript
import { api } from './client';

export interface PublicShareCreated {
  share_id: string;
  agent_id: string;
  name: string;
  created_at: string;
}

export function createPublicShare(name: string, sourceAgentId: string) {
  return api.post<PublicShareCreated>('/public/agents', { name, source_agent_id: sourceAgentId });
}

export function getPublicShareBySource(sourceAgentId: string) {
  return api.get<PublicShareCreated>(`/public/agents/by-source/${sourceAgentId}`);
}
```

- [ ] **Step 2: Modify `frontend/src/pages/AgentDetailPage.tsx`**

Add imports:

```typescript
import { useEffect, useState } from 'react';
import { createPublicShare, getPublicShareBySource } from '../api/publicShare';
```

(`useState` is already imported at the top of this file — add `useEffect` alongside it, and add the `../api/publicShare` import alongside the other `../api/*` imports.)

Add state, an auto-lookup effect, and a create handler inside the `AgentDetailPage` function body, near the other `useState` calls (`agentId` is already in scope from the existing `useParams` call at the top of this component):

```typescript
  const [shareId, setShareId] = useState<string | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [shareChecked, setShareChecked] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    if (!agentId) return;
    getPublicShareBySource(agentId)
      .then((result) => {
        setShareId(result.share_id);
        setShareUrl(`${window.location.origin}/share/${result.share_id}`);
      })
      .catch(() => {
        // 404 -- no public share exists for this agent yet, which is the
        // normal case. Nothing to restore, nothing to show as an error.
      })
      .finally(() => setShareChecked(true));
  }, [agentId]);

  async function handleCreateShareableLink() {
    setSharing(true);
    setShareError(null);
    try {
      const result = await createPublicShare(`${agent!.name} (Public)`, agentId!);
      setShareId(result.share_id);
      setShareUrl(`${window.location.origin}/share/${result.share_id}`);
    } catch (err) {
      setShareError(describeError(err));
    } finally {
      setSharing(false);
    }
  }
```

Add a new section, right after the existing `<section className={styles.section}><h2>Documents</h2>...</section>` block. The button only renders once the lookup has resolved (`shareChecked`) and found nothing (`!shareUrl`) — if a share already exists, the link panel below appears instead, immediately, with no click required:

```tsx
      <section className={styles.section}>
        <h2>Public sharing</h2>
        <p>
          Creates a brand-new, separate agent with a fixed assistant prompt and its own knowledge
          base — anyone with the link can chat with it, no account required. This is not the same
          agent or knowledge base as the one above.
        </p>
        {shareChecked && !shareUrl && (
          <button type="button" className="btn btn-primary" onClick={handleCreateShareableLink} disabled={sharing}>
            {sharing ? 'Creating…' : 'Get shareable link'}
          </button>
        )}
        {shareError && <ErrorBanner message={shareError} />}
        {shareUrl && shareId && (
          <div className={styles.uploadTile}>
            <p className="mono">{shareUrl}</p>
          </div>
        )}
      </section>
```

- [ ] **Step 3: Verify in a browser**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
cd /home/william/powabase-chatbot/frontend && npm run dev &
sleep 3
```

Open the app, sign in, open any agent's detail page. First visit: confirm the **Get shareable link** button shows (no share yet), click it, and confirm a `http://localhost:5173/share/<share_id>`-shaped URL appears in place of the button (the `/share/:shareId` route itself doesn't exist until Task 10 — a 404 on visiting it is expected for now). **Then reload the page** and confirm the same URL appears immediately with no button click needed — this is the idempotent-lookup path (Fix 3), not the create path, and it must show the identical `share_id` as before (check the Task 3 verification if this doesn't hold — it means the by-source lookup isn't matching).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/publicShare.ts frontend/src/pages/AgentDetailPage.tsx
git commit -m "feat: add Get shareable link button to agent detail page"
```

---

### Task 10: Frontend — standalone public share page

**Files:**
- Create: `frontend/src/pages/PublicSharePage.tsx`
- Create: `frontend/src/pages/PublicSharePage.module.css`
- Modify: `frontend/src/App.tsx` — add the route **outside** `ProtectedRoute`/`AppShell`.

**Interfaces:**
- Consumes: everything from `frontend/src/lib/publicShareClient.ts` (Task 8).
- Produces: route `/share/:shareId`, no auth, no app chrome.

- [ ] **Step 1: Create `frontend/src/pages/PublicSharePage.module.css`**

```css
.page {
  max-width: 640px;
  margin: 0 auto;
  padding: 2rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 100vh;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.messages {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  overflow-y: auto;
}

.message {
  padding: 0.6rem 0.9rem;
  border-radius: 0.6rem;
  max-width: 80%;
}

.user {
  align-self: flex-end;
  background: var(--color-accent, #2563eb);
  color: white;
}

.assistant {
  align-self: flex-start;
  background: var(--color-surface, #f1f1f1);
}

.inputRow {
  display: flex;
  gap: 0.5rem;
}

.inputRow input[type='text'] {
  flex: 1;
}
```

- [ ] **Step 2: Create `frontend/src/pages/PublicSharePage.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  attachPublicDocument,
  clearPublicSession,
  loadCachedMessages,
  saveCachedMessages,
  sendPublicChatMessage,
  type PublicChatMessage,
} from '../lib/publicShareClient';
import styles from './PublicSharePage.module.css';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

export function PublicSharePage() {
  const { shareId } = useParams<{ shareId: string }>();
  const [messages, setMessages] = useState<PublicChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!shareId) return;
    setMessages(loadCachedMessages(shareId));
  }, [shareId]);

  async function handleSend() {
    if (!shareId || !input.trim() || sending) return;
    const userMessage: PublicChatMessage = { role: 'user', content: input };
    const next = [...messages, userMessage];
    setMessages(next);
    saveCachedMessages(shareId, next);
    setInput('');
    setSending(true);
    setError(null);
    try {
      const content = await sendPublicChatMessage(API_BASE_URL, shareId, userMessage.content);
      const withReply = [...next, { role: 'assistant', content } as PublicChatMessage];
      setMessages(withReply);
      saveCachedMessages(shareId, withReply);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setSending(false);
    }
  }

  function handleNewSession() {
    if (!shareId) return;
    clearPublicSession(shareId);
    setMessages([]);
    setError(null);
    setUploadStatus(null);
  }

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !shareId) return;
    setUploadStatus('Uploading…');
    try {
      const result = await attachPublicDocument(API_BASE_URL, shareId, file);
      setUploadStatus(`Attached: ${result.filename}`);
    } catch (err) {
      setUploadStatus(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  if (!shareId) return null;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1>Chat</h1>
        <button type="button" className="btn" onClick={handleNewSession}>
          New Session
        </button>
      </div>

      <div className={styles.messages}>
        {messages.map((m, i) => (
          <div key={i} className={`${styles.message} ${m.role === 'user' ? styles.user : styles.assistant}`}>
            {m.content}
          </div>
        ))}
      </div>

      {error && <p role="alert">{error}</p>}

      <div>
        <input ref={fileInputRef} type="file" onChange={handleFileChange} />
        {uploadStatus && <p>{uploadStatus}</p>}
      </div>

      <div className={styles.inputRow}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Type a message…"
          disabled={sending}
        />
        <button type="button" className="btn btn-primary" onClick={handleSend} disabled={sending || !input.trim()}>
          {sending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Modify `frontend/src/App.tsx`**

Add the import:

```typescript
import { PublicSharePage } from './pages/PublicSharePage';
```

Add a new top-level route, **outside** the `<ProtectedRoute>` block (alongside `/signin` and `/signup`):

```tsx
      <Route path="/share/:shareId" element={<PublicSharePage />} />
```

- [ ] **Step 4: Verify in a browser**

With the backend and `npm run dev` still running from Task 9, visit the share URL captured earlier (`http://localhost:5173/share/<share_id>`). Confirm: no login prompt, no app chrome/nav, sending a message gets a reply, refreshing the page keeps the conversation (localStorage restore), and **New Session** clears it and starts fresh (verify by checking `localStorage` in devtools before/after — the two keys named `powabase-public-session:<share_id>` and `powabase-public-messages:<share_id>` should disappear).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/PublicSharePage.tsx frontend/src/pages/PublicSharePage.module.css frontend/src/App.tsx
git commit -m "feat: add standalone public share chat page"
```

---

### Task 11: Embeddable widget

**Files:**
- Create: `frontend/src/widget/embed.ts`
- Create: `frontend/vite.widget.config.ts`
- Modify: `frontend/package.json` — add a `build:widget` script.
- Create: `app/routes/public.py` addition — `GET /public/widget.js`.

**Interfaces:**
- Consumes: `frontend/src/lib/publicShareClient.ts` (Task 8, same module the React page uses).
- Produces: a single self-executing `frontend/dist-widget/widget.js`, configured via `<script src=".../widget.js" data-share-id="..." data-api-base="..."></script>`. Served by the backend at `GET /public/widget.js`.

- [ ] **Step 1: Create `frontend/src/widget/embed.ts`**

```typescript
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
```

- [ ] **Step 2: Create `frontend/vite.widget.config.ts`**

```typescript
import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: 'src/widget/embed.ts',
      name: 'PowabaseWidget',
      formats: ['iife'],
      fileName: () => 'widget.js',
    },
    outDir: 'dist-widget',
    emptyOutDir: true,
  },
});
```

- [ ] **Step 3: Add the build script to `frontend/package.json`**

In the `"scripts"` block, add:

```json
    "build:widget": "vite build --config vite.widget.config.ts",
```

- [ ] **Step 4: Build the widget**

```bash
cd /home/william/powabase-chatbot/frontend && npm run build:widget
```

Expected: `frontend/dist-widget/widget.js` is created.

- [ ] **Step 5: Serve it from the backend — add to `app/routes/public.py`**

```python
from pathlib import Path
from fastapi.responses import FileResponse

WIDGET_JS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist-widget" / "widget.js"


@router.get("/widget.js")
def serve_widget_js():
    if not WIDGET_JS_PATH.exists():
        raise HTTPException(status_code=404, detail="Widget bundle not built yet -- run `npm run build:widget` in frontend/")
    return FileResponse(WIDGET_JS_PATH, media_type="application/javascript")
```

- [ ] **Step 6: Verify**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://127.0.0.1:8000/public/widget.js
```

Expected: `200 application/javascript` (or `text/javascript`, depending on the platform's mimetypes DB — either is fine).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/widget/embed.ts frontend/vite.widget.config.ts frontend/package.json app/routes/public.py
git commit -m "feat: add embeddable chat widget, built and served as a standalone script"
```

---

### Task 12: Embed snippet on the agent detail page

**Files:**
- Modify: `frontend/src/pages/AgentDetailPage.tsx` — extend the "Public sharing" section from Task 9.

**Interfaces:**
- Consumes: `shareId`/`shareUrl` state (Task 9 — already tracks both, set together by both the auto-lookup effect and the create handler, per Fix 3). No new state needed here.

- [ ] **Step 1: Modify the share panel in `frontend/src/pages/AgentDetailPage.tsx`**

Replace Task 9's `{shareUrl && shareId && (...)}` block entirely with this (same location, same `styles.uploadTile` wrapper — this is not a second block alongside the old one, it fully supersedes it, adding the embed snippet under the URL):

```tsx
        {shareUrl && shareId && (
          <div className={styles.uploadTile}>
            <p className="mono">{shareUrl}</p>
            <p>Embed on another site:</p>
            <pre className="mono">
{`<script src="${import.meta.env.VITE_API_BASE_URL}/public/widget.js" data-share-id="${shareId}" data-api-base="${import.meta.env.VITE_API_BASE_URL}"></script>`}
            </pre>
          </div>
        )}
```

- [ ] **Step 2: Verify in a browser**

Reload the agent detail page (whether or not a share already exists — both the freshly-created and the auto-looked-up path render this same block) and confirm a `<script src="...">` snippet appears below the URL with the correct `data-share-id`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/AgentDetailPage.tsx
git commit -m "feat: show embed snippet alongside the shareable link"
```

---

### Task 13: Bare-bones test website + cross-origin live verification

**Files:**
- Create: `frontend/test-embed-site/index.html`

**Interfaces:** none — this is a standalone static page with no build step, served from a different port to genuinely be a different origin than both the backend (`8000`) and the main app's dev server (`5173`).

- [ ] **Step 1: Create `frontend/test-embed-site/index.html`**

Replace `SHARE_ID_HERE` with a real `share_id` from a share you created in Task 9/12 before running this.

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Third-party test site</title>
</head>
<body>
  <h1>This is an unrelated website</h1>
  <p>It has nothing to do with the chatbot app. The chat bubble in the corner is the embedded widget.</p>

  <script
    src="http://127.0.0.1:8000/public/widget.js"
    data-share-id="SHARE_ID_HERE"
    data-api-base="http://127.0.0.1:8000"
  ></script>
</body>
</html>
```

- [ ] **Step 2: Serve it on a third port and verify live, cross-origin**

```bash
pkill -f "uvicorn app.main:app" 2>/dev/null; sleep 1
cd /home/william/powabase-chatbot && (nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &)
sleep 2
cd /home/william/powabase-chatbot/frontend/test-embed-site && (nohup python3 -m http.server 9999 > /tmp/test-embed-site.log 2>&1 &)
sleep 1
```

Open `http://127.0.0.1:9999/` in a browser (a genuinely different origin from both `127.0.0.1:8000` and `localhost:5173`). Confirm:
- The chat bubble renders in the bottom-right corner.
- Clicking it opens the panel.
- Sending a message gets a real reply (network tab shows a successful cross-origin `POST` to `http://127.0.0.1:8000/public/{share_id}/chat` with no CORS error in the console).
- Uploading a file via the widget's file input succeeds.
- **New Session** clears the widget's messages.
- Refreshing `127.0.0.1:9999` restores the conversation (localStorage, scoped to that browser + `share_id`).

- [ ] **Step 3: Commit**

```bash
git add frontend/test-embed-site/index.html
git commit -m "test: add bare-bones third-party site for embed widget verification"
```

---

## Explicitly out of scope (flagging, not building)

- **Revoking/expiring a share** — `DELETE /public/agents/{share_id}` or similar isn't in the spec; the only way to kill a public share today is deleting its (dedicated) agent via the normal agent UI, which Task 7 wires up correctly.
- **Per-owner or per-visitor token accounting** — only the flat global 100k cap exists, exactly as specified ("rough safety net, not precise accounting").
- **Rate-limiting beyond the explicit `10/minute`-per-IP limit on the two public routes** (Tasks 4/5) — nothing beyond that flat per-IP limit (e.g. per-share-id limits) was requested.
- **Production static hosting for `widget.js`** — served from the FastAPI backend itself (Task 11) rather than a CDN, which is adequate for this dev/test environment but worth revisiting before a real production embed.
