from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_orchestration_entity,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    create_orchestration,
    ensure_session_context_tool,
    get_chatbot_entry,
    insert_agent_registry_row,
    insert_chatbot_row,
    link_agent_knowledge_base,
    list_chatbot_agent_rows,
    list_chatbot_rows,
)

router = APIRouter(prefix="/chatbots", tags=["chatbots"])

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the coordinator of a multi-agent assistant. Your job is to route each "
    "user request to the specialist agent(s) whose role best matches it, using the "
    "role descriptions provided for each agent. If a request spans multiple agents' "
    "roles, delegate to each relevant agent and synthesize their results into a single, "
    "coherent reply. If no agent's role matches the request, answer directly using your "
    "own general knowledge, or say plainly that you don't have a specialist for that. "
    "Never fabricate information a delegated agent didn't provide."
)


class CreateChatbotRequest(BaseModel):
    name: str
    agent_name: str
    role_description: str
    system_prompt: str | None = None


def _create_subagent(name: str, system_prompt: str | None, user_id: str) -> tuple[str, str]:
    """Agent + its own isolated KB + session-context tool -- same recipe as POST /agents."""
    kb_data, status_code = create_knowledge_base(f"{name}-{user_id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(name, system_prompt)
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

    return agent_id, kb_id


@router.post("")
def create_chatbot_route(req: CreateChatbotRequest, user: AuthedUser = Depends(get_current_user)):
    agent_id, kb_id = _create_subagent(req.agent_name, req.system_prompt, user.id)

    orch_data, status_code = create_orchestration(req.name, {"additional_instructions": ORCHESTRATOR_SYSTEM_PROMPT})
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=orch_data)
    orchestrator_id = orch_data["id"]

    entity_data, status_code = add_orchestration_entity(orchestrator_id, agent_id, req.role_description)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=entity_data)
    entity_id = entity_data["id"]

    chatbot_row, status_code = insert_chatbot_row(user.access_token, user.id, orchestrator_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=chatbot_row)
    chatbot_id = chatbot_row["id"]

    registry_row, status_code = insert_agent_registry_row(
        user.access_token,
        user.id,
        agent_id,
        kb_id,
        req.agent_name,
        chatbot_id=chatbot_id,
        orchestration_entity_id=entity_id,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)

    return {"chatbot": chatbot_row, "agent": registry_row}


@router.get("")
def list_chatbots_route(user: AuthedUser = Depends(get_current_user)):
    data, status_code = list_chatbot_rows(user.access_token)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{chatbot_id}")
def get_chatbot_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user)):
    chatbot_rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not chatbot_rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")

    agent_rows, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_rows)

    return {**chatbot_rows[0], "agents": agent_rows}
