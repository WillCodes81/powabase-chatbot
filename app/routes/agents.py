from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.ownership import get_owned_agent, get_owned_public_share
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    delete_agent,
    delete_agent_registry_row,
    delete_agent_session_rows,
    delete_knowledge_base,
    delete_public_share,
    ensure_session_context_tool,
    get_agent_session_kb_ids,
    get_public_share_by_source_agent_id,
    get_public_share_session_kb_ids,
    get_public_share_session_by_id,
    get_public_share_sessions,
    get_public_shares_for_agent,
    get_session_messages,
    insert_agent_registry_row,
    link_agent_knowledge_base,
    list_agent_registry_rows,
    update_agent_registry_name,
)
from app.validation import NonEmptyStr

router = APIRouter(prefix="/agents", tags=["agents"])


class CreateAgentRequest(BaseModel):
    name: NonEmptyStr
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


@router.get("")
def list_agents_route(user: AuthedUser = Depends(get_current_user)):
    data, status_code = list_agent_registry_rows(user.access_token)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


class UpdateAgentRequest(BaseModel):
    name: NonEmptyStr


@router.patch("/{agent_id}")
def update_agent_route(agent_id: str, req: UpdateAgentRequest, user: AuthedUser = Depends(get_current_user), agent: dict = Depends(get_owned_agent)):
    data, status_code = update_agent_registry_name(user.access_token, agent_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.delete("/{agent_id}")
def delete_agent_route(agent_id: str, user: AuthedUser = Depends(get_current_user), agent: dict = Depends(get_owned_agent)):
    if agent.get("chatbot_id"):
        raise HTTPException(
            status_code=400,
            detail="This agent belongs to a chatbot -- remove it via DELETE /chatbots/{chatbot_id}/agents/{agent_id} instead.",
        )

    kb_id = agent.get("kb_id")
    if kb_id:
        _, sc = delete_knowledge_base(kb_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent's knowledge base")

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

    session_kb_rows, status_code = get_agent_session_kb_ids(user.access_token, agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to look up agent's session knowledge bases")
    for row in session_kb_rows:
        _, sc = delete_knowledge_base(row["kb_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete session knowledge base {row['kb_id']}")

    _, sc = delete_agent_session_rows(user.access_token, agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent's session history")

    _, sc = delete_agent(agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent")

    _, sc = delete_agent_registry_row(user.access_token, agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent registry row")

    return {"deleted": True}


@router.get("/by-source/{source_agent_id}")
def get_public_share_by_source_route(source_agent_id: str, user: AuthedUser = Depends(get_current_user)):
    """
    Lets the agent detail page find an already-created share for the agent
    it's viewing, without creating a new one. Requires login -- moved here
    from public.py (which is mounted on public_app, the permissive-CORS app
    built for anonymous visitors) since an authenticated-only route has no
    business being reachable from an arbitrary origin.
    """
    rows, status_code = get_public_share_by_source_agent_id(user.access_token, source_agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=rows)
    if not rows:
        raise HTTPException(status_code=404, detail="No public share exists for this agent yet")
    share = rows[0]
    return {"share_id": share["share_id"], "agent_id": share["agent_id"], "created_at": share["created_at"]}


@router.get("/{agent_id}/public-share/sessions")
def list_public_share_sessions_route(agent_id: str, share: dict = Depends(get_owned_public_share)):
    rows, status_code = get_public_share_sessions(share["share_id"])
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=rows)
    return [
        {
            "id": row["id"],
            "anon_session_id": row["anon_session_id"],
            "created_at": row["created_at"],
            "has_document": bool(row.get("kb_id")),
            "has_conversation": bool(row.get("powabase_session_id")),
        }
        for row in rows
    ]


@router.get("/{agent_id}/public-share/sessions/{session_id}/transcript")
def get_public_share_session_transcript_route(agent_id: str, session_id: str, share: dict = Depends(get_owned_public_share)):
    rows, status_code = get_public_share_session_by_id(share["share_id"], session_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=404, detail="Session not found for this public share")

    session = rows[0]
    powabase_session_id = session.get("powabase_session_id")
    if not powabase_session_id:
        return {"has_conversation": False, "messages": []}

    data, status_code = get_session_messages(powabase_session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return {"has_conversation": True, "messages": data.get("messages", [])}
