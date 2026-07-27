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
        context_override = _build_context_override(user.access_token, req.agent_id, req.session_id)

    data, status_code = run_agent(req.agent_id, req.message, session_id=req.session_id, context_override=context_override)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    if not req.session_id:
        registry_row, status_code = insert_chat_session_row(user.access_token, user.id, req.agent_id, data["session_id"], req.label)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=registry_row)

    return data
