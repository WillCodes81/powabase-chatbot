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


def run_agent(agent_id: str, message: str) -> dict:
    with requests.post(
        f"{settings.powabase_url}/api/agents/{agent_id}/run/stream",
        headers={
            "apikey": settings.powabase_service_key,
            "Authorization": f"Bearer {settings.powabase_service_key}",
            "Content-Type": "application/json",
        },
        json={"message": message},
        stream=True,
    ) as response:
        if response.status_code >= 400:
            return response.json(), response.status_code

        session_id = None
        for raw in response.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8")
            if line.startswith(":") or not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            kind = event.get("event")
            if kind == "start":
                session_id = event.get("session_id")
            elif kind == "complete":
                return {
                    "content": event["content"],
                    "session_id": session_id,
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
