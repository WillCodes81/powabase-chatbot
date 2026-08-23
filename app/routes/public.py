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
