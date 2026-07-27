import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_session_messages,
    get_source,
    get_source_text_derivative,
    insert_session_document_row,
    list_chat_sessions,
    upload_source,
)

router = APIRouter(prefix="/agents", tags=["sessions"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120
MAX_DOCUMENT_TOKENS = 6000


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
            detail=f"Document extraction ended in status '{extraction_status}', cannot attach to session",
        )

    text, status_code = get_source_text_derivative(source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=text)

    token_estimate = len(text) // 4
    if token_estimate > MAX_DOCUMENT_TOKENS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Document is too large to attach to a session: ~{token_estimate} estimated tokens "
                f"(limit is {MAX_DOCUMENT_TOKENS} tokens, ~{MAX_DOCUMENT_TOKENS * 4} characters). "
                "Use POST /ingest/file to add it to the agent's knowledge base instead."
            ),
        )

    row, status_code = insert_session_document_row(
        user.access_token, user.id, agent_id, session_id, source_id, file.filename, text, token_estimate
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=row)

    row.pop("extracted_text", None)
    return row
