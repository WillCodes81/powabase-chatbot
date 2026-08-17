from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.ownership import get_owned_agent
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    ensure_session_context_tool,
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
