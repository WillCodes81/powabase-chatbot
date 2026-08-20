from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.credit_lock import deduct_credits_logged, user_credit_lock
from app.deps import AuthedUser, get_current_user
from app.ownership import get_owned_chatbot, get_owned_chatbot_session
from app.rate_limit import limiter
from app.powabase_client import (
    SESSION_CONTEXT_TOOL_NAME,
    add_orchestration_entity,
    add_source_to_kb,
    assign_tool_to_agent,
    create_agent,
    create_knowledge_base,
    create_orchestration,
    delete_agent,
    delete_agent_registry_row,
    delete_chatbot_row,
    delete_chatbot_session_rows,
    delete_knowledge_base,
    delete_orchestration,
    ensure_session_context_tool,
    ensure_user_credits_row,
    get_chatbot_agent_entry,
    get_chatbot_session_entry,
    get_chatbot_session_kb_ids,
    get_session_messages,
    insert_agent_registry_row,
    insert_chatbot_row,
    insert_chatbot_session_row,
    link_agent_knowledge_base,
    list_chatbot_agent_rows,
    list_chatbot_rows,
    list_chatbot_sessions,
    remove_orchestration_entity,
    run_orchestration,
    update_chatbot_name,
    update_chatbot_session_kb_id,
    update_chatbot_session_label,
    upload_and_resolve_source_id,
    wait_for_source_extraction,
)
from app.validation import NonEmptyStr

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
    name: NonEmptyStr
    agent_name: NonEmptyStr
    role_description: NonEmptyStr
    system_prompt: str | None = None
    model: str | None = None


def _create_subagent(name: str, system_prompt: str | None, user_id: str, model: str | None = None) -> tuple[str, str]:
    """Agent + its own isolated KB + session-context tool -- same recipe as POST /agents."""
    kb_data, status_code = create_knowledge_base(f"{name}-{user_id}")
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=kb_data)
    kb_id = kb_data["id"]

    agent_data, status_code = create_agent(name, system_prompt, model)
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
    agent_id, kb_id = _create_subagent(req.agent_name, req.system_prompt, user.id, req.model)

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
def get_chatbot_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    agent_rows, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_rows)

    return {**chatbot, "agents": agent_rows}


@router.get("/{chatbot_id}/sessions")
def list_chatbot_sessions_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    data, status_code = list_chatbot_sessions(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{chatbot_id}/sessions/{session_id}/messages")
def get_chatbot_session_messages_route(chatbot_id: str, session_id: str, session: dict = Depends(get_owned_chatbot_session)):
    data, status_code = get_session_messages(session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.post("/{chatbot_id}/sessions/{session_id}/attach-document")
def attach_chatbot_session_document_route(
    chatbot_id: str,
    session_id: str,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(get_current_user),
    session: dict = Depends(get_owned_chatbot_session),
):
    """
    Attaches a document scoped to this one conversation, available to
    whichever subagent(s) the orchestrator delegates to on each turn --
    not to a specific subagent's permanent KB, and not visible from any
    other conversation with this chatbot (see run_orchestration's kb_id ->
    runtime_knowledge_bases wiring). Mirrors sessions.py's
    attach_document_route for standalone agents.
    """
    kb_id = session.get("kb_id")
    if not kb_id:
        kb_data, status_code = create_knowledge_base(f"chatbot-session-{session_id}")
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_data)
        kb_id = kb_data["id"]
        _, status_code = update_chatbot_session_kb_id(user.access_token, chatbot_id, session_id, kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail="Failed to save session's knowledge base id")

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


class AddAgentRequest(BaseModel):
    name: NonEmptyStr
    role_description: NonEmptyStr
    system_prompt: str | None = None
    model: str | None = None


@router.post("/{chatbot_id}/agents")
def add_chatbot_agent_route(chatbot_id: str, req: AddAgentRequest, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    orchestrator_id = chatbot["orchestrator_id"]

    agent_id, kb_id = _create_subagent(req.name, req.system_prompt, user.id, req.model)

    entity_data, status_code = add_orchestration_entity(orchestrator_id, agent_id, req.role_description)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=entity_data)
    entity_id = entity_data["id"]

    registry_row, status_code = insert_agent_registry_row(
        user.access_token,
        user.id,
        agent_id,
        kb_id,
        req.name,
        chatbot_id=chatbot_id,
        orchestration_entity_id=entity_id,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=registry_row)
    return registry_row


@router.delete("/{chatbot_id}/agents/{agent_id}")
def delete_chatbot_agent_route(chatbot_id: str, agent_id: str, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    orchestrator_id = chatbot["orchestrator_id"]

    agent_rows, status_code = get_chatbot_agent_entry(user.access_token, chatbot_id, agent_id)
    if status_code >= 400 or not agent_rows:
        raise HTTPException(status_code=404, detail="Agent not found on this chatbot")
    agent_row = agent_rows[0]

    all_agents, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=all_agents)

    if len(all_agents) == 1:
        # Last agent on this chatbot: the whole orchestration must go too (mentor
        # requirement -- never leave a zero-entity orchestrator alive).
        _, sc = delete_orchestration(orchestrator_id)
        if sc >= 400 and sc != 404:
            raise HTTPException(status_code=sc, detail="Failed to delete orchestrator")

        kb_id = agent_row.get("kb_id")
        if kb_id:
            _, sc = delete_knowledge_base(kb_id)
            if sc >= 400:
                raise HTTPException(status_code=sc, detail="Failed to delete agent's knowledge base")

        _, sc = delete_agent(agent_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent")

        _, sc = delete_agent_registry_row(user.access_token, agent_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent registry row")

        session_kb_rows, sc = get_chatbot_session_kb_ids(user.access_token, chatbot_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to look up chatbot's session knowledge bases")
        for row in session_kb_rows:
            _, sc = delete_knowledge_base(row["kb_id"])
            if sc >= 400:
                raise HTTPException(status_code=sc, detail=f"Failed to delete session knowledge base {row['kb_id']}")

        _, sc = delete_chatbot_session_rows(user.access_token, chatbot_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete chatbot's session history")

        _, sc = delete_chatbot_row(user.access_token, chatbot_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete chatbot row")

        return {"deleted": True, "chatbot_deleted": True}

    # Other agents remain: remove just this one's orchestration entity link, then
    # the agent and its KB. The chatbot and orchestrator stay alive.
    entity_id = agent_row.get("orchestration_entity_id")
    if entity_id:
        _, sc = remove_orchestration_entity(orchestrator_id, entity_id)
        if sc >= 400 and sc != 404:
            raise HTTPException(status_code=sc, detail="Failed to remove agent from orchestrator")

    kb_id = agent_row.get("kb_id")
    if kb_id:
        _, sc = delete_knowledge_base(kb_id)
        if sc >= 400:
            raise HTTPException(status_code=sc, detail="Failed to delete agent's knowledge base")

    _, sc = delete_agent(agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent")

    _, sc = delete_agent_registry_row(user.access_token, agent_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete agent registry row")

    return {"deleted": True, "chatbot_deleted": False}


@router.delete("/{chatbot_id}")
def delete_chatbot_route(chatbot_id: str, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    orchestrator_id = chatbot["orchestrator_id"]

    agent_rows, status_code = list_chatbot_agent_rows(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=agent_rows)

    _, sc = delete_orchestration(orchestrator_id)
    if sc >= 400 and sc != 404:
        raise HTTPException(status_code=sc, detail="Failed to delete orchestrator")

    for row in agent_rows:
        kb_id = row.get("kb_id")
        if kb_id:
            _, sc = delete_knowledge_base(kb_id)
            if sc >= 400:
                raise HTTPException(status_code=sc, detail=f"Failed to delete knowledge base for agent {row['agent_id']}")

        _, sc = delete_agent(row["agent_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete agent {row['agent_id']}")

        _, sc = delete_agent_registry_row(user.access_token, row["agent_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete registry row for agent {row['agent_id']}")

    session_kb_rows, status_code = get_chatbot_session_kb_ids(user.access_token, chatbot_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to look up chatbot's session knowledge bases")
    for row in session_kb_rows:
        _, sc = delete_knowledge_base(row["kb_id"])
        if sc >= 400:
            raise HTTPException(status_code=sc, detail=f"Failed to delete session knowledge base {row['kb_id']}")

    _, sc = delete_chatbot_session_rows(user.access_token, chatbot_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete chatbot's session history")

    _, sc = delete_chatbot_row(user.access_token, chatbot_id)
    if sc >= 400:
        raise HTTPException(status_code=sc, detail="Failed to delete chatbot row")

    return {"deleted": True, "agents_deleted": len(agent_rows)}


class ChatbotChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    label: str | None = None


@router.post("/{chatbot_id}/chat")
@limiter.limit("20/minute")
def chatbot_chat_route(
    chatbot_id: str,
    request: Request,
    req: ChatbotChatRequest,
    user: AuthedUser = Depends(get_current_user),
    chatbot: dict = Depends(get_owned_chatbot),
):
    orchestrator_id = chatbot["orchestrator_id"]

    # session_id is optional and comes from the request body, not the URL
    # path, so it can't be resolved via a path-param-based dependency the
    # way chatbot ownership above is -- stays a manual, conditional check.
    session_kb_id = None
    if req.session_id:
        session_rows, status_code = get_chatbot_session_entry(user.access_token, chatbot_id, req.session_id)
        if status_code >= 400 or not session_rows:
            raise HTTPException(status_code=403, detail="Session not found or not owned by this user for this chatbot")
        session_kb_id = session_rows[0].get("kb_id")

    # See chat.py's chat_route for why this whole span is locked per-user.
    with user_credit_lock(user.id):
        credits_row = ensure_user_credits_row(user.access_token, user.id)
        if credits_row["tokens_remaining"] <= 0:
            raise HTTPException(status_code=402, detail="Token balance exhausted. You have no tokens remaining.")

        data, status_code = run_orchestration(orchestrator_id, req.message, session_id=req.session_id, kb_id=session_kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=data)

        if not req.session_id:
            _, status_code = insert_chatbot_session_row(user.access_token, user.id, chatbot_id, data["session_id"], req.label)
            if status_code >= 400:
                raise HTTPException(status_code=status_code, detail="Failed to save chat session")

        usage = data.get("usage")
        if usage and usage.get("total_tokens"):
            deduct_credits_logged(user.access_token, user.id, usage["total_tokens"])

    return data


class UpdateChatbotRequest(BaseModel):
    name: NonEmptyStr


@router.patch("/{chatbot_id}")
def update_chatbot_route(chatbot_id: str, req: UpdateChatbotRequest, user: AuthedUser = Depends(get_current_user), chatbot: dict = Depends(get_owned_chatbot)):
    data, status_code = update_chatbot_name(user.access_token, chatbot_id, req.name)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


class UpdateChatbotSessionRequest(BaseModel):
    label: NonEmptyStr


@router.patch("/{chatbot_id}/sessions/{session_id}")
def update_chatbot_session_route(
    chatbot_id: str,
    session_id: str,
    req: UpdateChatbotSessionRequest,
    user: AuthedUser = Depends(get_current_user),
    session: dict = Depends(get_owned_chatbot_session),
):
    data, status_code = update_chatbot_session_label(user.access_token, chatbot_id, session_id, req.label)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
