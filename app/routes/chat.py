import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.credit_lock import deduct_credits_logged, user_credit_lock
from app.deps import AuthedUser, get_current_user
from app.rate_limit import limiter
from app.powabase_client import (
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
@limiter.limit("20/minute")
def chat_route(request: Request, req: ChatRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, req.agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    context_override = None
    if req.session_id:
        session_rows, status_code = get_chat_session_entry(user.access_token, req.agent_id, req.session_id)
        if status_code >= 400 or not session_rows:
            raise HTTPException(status_code=403, detail="Session not found or not owned by this user for this agent")
        context_override = _build_context_override(req.session_id, session_rows[0].get("session_token"))

    # Holds the balance check, the run, and the deduction under one lock so
    # two concurrent requests from the same user can't both pass the check
    # before either deducts -- deduct_credits itself is already atomic per
    # call, but the pre-run balance read is a stale snapshot without this.
    with user_credit_lock(user.id):
        credits_row = ensure_user_credits_row(user.access_token, user.id)
        if credits_row["tokens_remaining"] <= 0:
            raise HTTPException(status_code=402, detail="Token balance exhausted. You have no tokens remaining.")

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
            deduct_credits_logged(user.access_token, user.id, usage["total_tokens"])

    return data
