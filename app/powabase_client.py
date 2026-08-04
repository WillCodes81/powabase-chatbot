import json

import requests
from app.config import settings


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
