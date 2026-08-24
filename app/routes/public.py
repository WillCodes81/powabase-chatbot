import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slowapi.util import get_remote_address

from app.config import settings
from app.credit_lock import deduct_credits_logged, user_credit_lock
from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_source_to_kb,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    ensure_session_context_tool,
    ensure_user_credits_row,
    get_or_create_public_share_session,
    get_public_share,
    get_public_share_by_source_agent_id,
    get_public_share_usage_total,
    get_session_messages,
    increment_public_share_usage,
    insert_agent_registry_row,
    insert_public_share_row,
    link_agent_knowledge_base,
    run_agent,
    update_public_share_session_kb_id,
    update_public_share_session_powabase_id,
    upload_and_resolve_source_id,
    wait_for_source_extraction,
)
from app.rate_limit import limiter
from app.validation import NonEmptyStr

router = APIRouter(tags=["public"])

WIDGET_JS_PATH = Path(__file__).resolve().parents[2] / "frontend" / "dist-widget" / "widget.js"

PUBLIC_TOKEN_CAP = 100_000

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


@router.get("/widget.js")
def serve_widget_js():
    if not WIDGET_JS_PATH.exists():
        raise HTTPException(status_code=404, detail="Widget bundle not built yet -- run `npm run build:widget` in frontend/")
    return FileResponse(WIDGET_JS_PATH, media_type="application/javascript")


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

    if get_public_share_usage_total() >= PUBLIC_TOKEN_CAP:
        raise HTTPException(status_code=429, detail="This public sharing feature has reached its usage limit for now.")

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
