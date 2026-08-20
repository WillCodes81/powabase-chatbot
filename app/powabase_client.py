import json
import logging
import time

import requests
from app.config import settings

logger = logging.getLogger("app.orchestration")

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


def signup(email: str, password: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/auth/v1/signup",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {settings.powabase_anon_key}",
            "Content-Type": "application/json",
        },
        json={"email": email, "password": password},
    )
    return response.json(), response.status_code


def signin(email: str, password: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/auth/v1/token",
        params={"grant_type": "password"},
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {settings.powabase_anon_key}",
            "Content-Type": "application/json",
        },
        json={"email": email, "password": password},
    )
    return response.json(), response.status_code


def upload_source(file_bytes: bytes, filename: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/sources/upload",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
        files={"file": (filename, file_bytes)},
    )
    return response.json(), response.status_code


def get_source(source_id: str) -> dict:
    response = requests.get(
        f"{settings.powabase_url}/api/sources/{source_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def upload_and_resolve_source_id(file_bytes: bytes, filename: str) -> tuple[str, None] | tuple[None, tuple[dict, int]]:
    """
    Upload a source and resolve its id, handling the "duplicate content"
    case the same way every caller needs to: on a 409, the real id lives
    under data["duplicate"]["id"] instead of data["id"].

    Returns (source_id, None) on success, or (None, (error_data, status_code))
    on failure -- the caller raises HTTPException(status_code, detail=error_data).
    """
    data, status_code = upload_source(file_bytes, filename)
    if status_code == 409:
        return data["duplicate"]["id"], None
    if status_code < 400:
        return data["id"], None
    return None, (data, status_code)


def wait_for_source_extraction(source_id: str) -> tuple[dict, int]:
    """
    Poll a Source until extraction reaches a terminal status.

    Returns (data, status_code): a >=400 status_code means the poll itself
    failed (network/API error, or timeout as a synthetic 504) and data is
    the error body to surface. A 200 means polling succeeded and the
    caller must still check data["extraction_status"] -- reaching a
    terminal status doesn't mean extraction succeeded, just that it's done.
    """
    elapsed = 0
    extraction_status = None
    while extraction_status not in TERMINAL_EXTRACTION_STATUSES:
        if elapsed >= POLL_TIMEOUT_SECONDS:
            return {"error": "Timed out waiting for source extraction"}, 504

        data, status_code = get_source(source_id)
        if status_code >= 400:
            return data, status_code

        extraction_status = data["extraction_status"]
        if extraction_status in TERMINAL_EXTRACTION_STATUSES:
            return data, 200

        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS


def add_source_to_kb(kb_id: str, source_id: str) -> dict:
    response = requests.post(
        f"{settings.powabase_url}/api/knowledge-bases/{kb_id}/sources",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"source_id": source_id},
    )
    return response.json(), response.status_code


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


def get_authenticated_user(access_token: str) -> dict:
    response = requests.get(
        f"{settings.powabase_url}/auth/v1/user",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
    )
    return response.json(), response.status_code


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
        "Search a document the user attached to THIS specific chat session -- separate from "
        "knowledge_search, which searches the agent's permanent knowledge base. "
        "Before calling this tool, check whether a session_token value has been given to you "
        "verbatim, in plain text, earlier in this conversation's context. If one has been given: "
        "call this tool and pass that exact value as session_token. If none has been given: this "
        "session has no attached document, so call knowledge_search instead of this tool, and do "
        "not invent, guess, or fabricate a session_token."
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
                    "The session_token value given to you verbatim earlier in this conversation's "
                    "context. Never invent or guess this value."
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

    needs_update = existing.get("config", {}).get("endpoint") != endpoint or existing.get("description") != description
    if needs_update:
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


def get_agent_registry_entry(access_token: str, agent_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"agent_id": f"eq.{agent_id}", "select": "kb_id,chatbot_id,orchestration_entity_id"},
    )
    return response.json(), response.status_code


def list_agent_registry_rows(access_token: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/agents_registry",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"select": "id,agent_id,name,created_at", "order": "created_at.desc", "chatbot_id": "is.null"},
    )
    return response.json(), response.status_code


def get_session_messages(session_id: str) -> dict:
    response = requests.get(
        f"{settings.powabase_url}/api/sessions/{session_id}/messages",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


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


def get_orchestration(orchestration_id: str) -> tuple[dict, int]:
    response = requests.get(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
        },
    )
    return response.json(), response.status_code


def update_orchestration_entity_role(orchestration_id: str, entity_id: str, role_description: str) -> tuple[dict, int]:
    response = requests.put(
        f"{settings.powabase_url}/api/orchestrations/{orchestration_id}/entities/{entity_id}",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"role_description": role_description},
    )
    return response.json(), response.status_code


DOCUMENT_DELEGATION_CLAUSE = (
    " This agent has documents uploaded to its knowledge base -- delegate any question "
    "about documents, files, uploaded content, or their contents to it."
)


def ensure_document_delegation_clause(access_token: str, chatbot_id: str, entity_id: str) -> None:
    """
    The orchestrator's coordinator decides whether to delegate at all based
    solely on each entity's role_description text -- confirmed live: a
    role_description that doesn't mention documents/knowledge makes the
    coordinator answer "I don't have the document" itself, 0/8 times,
    without ever calling delegate_to_*, even though the subagent's KB has
    the answer. Since role_description is free text a user writes once at
    creation time (often before any document exists), keep it in sync here
    at ingest time instead of relying on wording alone.

    Best-effort and non-fatal like deduct_credits_logged in credit_lock.py --
    the document has already been successfully ingested by the time this is
    called, so a failure here must not fail the upload request.
    """
    chatbot_rows, status_code = get_chatbot_entry(access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        logger.error("could not resolve chatbot for delegation-clause sync chatbot_id=%s status=%s", chatbot_id, status_code)
        return
    orchestrator_id = chatbot_rows[0]["orchestrator_id"]

    orch_data, status_code = get_orchestration(orchestrator_id)
    if status_code >= 400:
        logger.error("could not fetch orchestration for delegation-clause sync orchestrator_id=%s status=%s", orchestrator_id, status_code)
        return

    entity = next((e for e in orch_data.get("entities", []) if e.get("id") == entity_id), None)
    if entity is None:
        logger.error("orchestration entity not found for delegation-clause sync orchestrator_id=%s entity_id=%s", orchestrator_id, entity_id)
        return

    current_role = entity.get("role_description") or ""
    if DOCUMENT_DELEGATION_CLAUSE.strip() in current_role:
        return

    _, status_code = update_orchestration_entity_role(orchestrator_id, entity_id, current_role + DOCUMENT_DELEGATION_CLAUSE)
    if status_code >= 400:
        logger.error("failed to update role_description for delegation-clause sync orchestrator_id=%s entity_id=%s status=%s", orchestrator_id, entity_id, status_code)


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


def list_chatbot_sessions(access_token: str, chatbot_id: str) -> list:
    response = requests.get(
        f"{settings.powabase_url}/rest/v1/chatbot_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "chatbot_id": f"eq.{chatbot_id}",
            "select": "id,session_id:powabase_session_id,label,created_at",
            "order": "created_at.desc",
        },
    )
    return response.json(), response.status_code


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


def delete_chatbot_session_rows(access_token: str, chatbot_id: str) -> tuple[dict, int]:
    response = requests.delete(
        f"{settings.powabase_url}/rest/v1/chatbot_sessions",
        headers={
            "apikey": settings.powabase_anon_key,
            "Authorization": f"Bearer {access_token}",
        },
        params={"chatbot_id": f"eq.{chatbot_id}"},
    )
    if response.status_code >= 400:
        return response.json(), response.status_code
    return {}, response.status_code
