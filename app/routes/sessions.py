import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    add_source_to_kb,
    create_knowledge_base,
    delete_chat_session_row,
    delete_knowledge_base,
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    get_source,
    list_chat_sessions,
    update_chat_session_kb_id,
    upload_source,
)

router = APIRouter(prefix="/agents", tags=["sessions"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


@router.get("/{agent_id}/sessions")
def list_sessions_route(agent_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    data, status_code = list_chat_sessions(user.access_token, agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{agent_id}/sessions/{session_id}/messages")
def get_session_messages_route(agent_id: str, session_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    data, status_code = get_session_messages(session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.post("/{agent_id}/sessions/{session_id}/attach-document")
def attach_document_route(
    agent_id: str,
    session_id: str,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(get_current_user),
):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    kb_id = session_rows[0].get("kb_id")
    if not kb_id:
        kb_data, status_code = create_knowledge_base(f"session-{session_id}")
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_data)
        kb_id = kb_data["id"]
        _, status_code = update_chat_session_kb_id(user.access_token, agent_id, session_id, kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail="Failed to save session's knowledge base id")

    file_bytes = file.file.read()

    data, status_code = upload_source(file_bytes, file.filename)
    if status_code == 409:
        source_id = data["duplicate"]["id"]
    elif status_code < 400:
        source_id = data["id"]
    else:
        raise HTTPException(status_code=status_code, detail=data)

    elapsed = 0
    extraction_status = None
    while extraction_status not in TERMINAL_EXTRACTION_STATUSES:
        if elapsed >= POLL_TIMEOUT_SECONDS:
            raise HTTPException(status_code=504, detail="Timed out waiting for source extraction")

        data, status_code = get_source(source_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=data)

        extraction_status = data["extraction_status"]
        if extraction_status in TERMINAL_EXTRACTION_STATUSES:
            break

        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS

    if extraction_status != "extracted":
        raise HTTPException(
            status_code=422,
            detail=f"Document extraction ended in status '{extraction_status}', cannot index",
        )

    index_data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=index_data)

    return {"kb_id": kb_id, "source_id": source_id, "filename": file.filename, **index_data}


@router.delete("/{agent_id}/sessions/{session_id}")
def delete_session_route(agent_id: str, session_id: str, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    session_rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not session_rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")

    kb_id = session_rows[0].get("kb_id")
    if kb_id:
        kb_result, status_code = delete_knowledge_base(kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_result)

    _, status_code = delete_chat_session_row(user.access_token, agent_id, session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to delete session")

    return {"deleted": True, "kb_deleted": bool(kb_id)}
