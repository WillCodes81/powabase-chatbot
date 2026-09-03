from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.ownership import get_owned_agent, get_owned_session
from app.powabase_client import (
    add_source_to_kb,
    create_knowledge_base,
    delete_chat_session_row,
    delete_knowledge_base,
    get_session_messages,
    list_chat_sessions,
    update_chat_session_kb_id,
    update_chat_session_label,
    upload_and_resolve_source_id,
    wait_for_source_extraction,
)
from app.validation import NonEmptyStr

router = APIRouter(prefix="/agents", tags=["sessions"])


@router.get("/{agent_id}/sessions")
def list_sessions_route(agent_id: str, user: AuthedUser = Depends(get_current_user), agent: dict = Depends(get_owned_agent)):
    data, status_code = list_chat_sessions(user.access_token, agent_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.get("/{agent_id}/sessions/{session_id}/messages")
def get_session_messages_route(agent_id: str, session_id: str, session: dict = Depends(get_owned_session)):
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
    session: dict = Depends(get_owned_session),
):
    kb_id = session.get("kb_id")
    if not kb_id:
        kb_data, status_code = create_knowledge_base(f"session-{session_id}")
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_data)
        kb_id = kb_data["id"]
        _, status_code = update_chat_session_kb_id(user.access_token, agent_id, session_id, kb_id)
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


@router.delete("/{agent_id}/sessions/{session_id}")
def delete_session_route(agent_id: str, session_id: str, user: AuthedUser = Depends(get_current_user), session: dict = Depends(get_owned_session)):
    kb_id = session.get("kb_id")
    if kb_id:
        kb_result, status_code = delete_knowledge_base(kb_id)
        if status_code >= 400:
            raise HTTPException(status_code=status_code, detail=kb_result)

    _, status_code = delete_chat_session_row(user.access_token, agent_id, session_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail="Failed to delete session")

    return {"deleted": True, "kb_deleted": bool(kb_id)}


class UpdateSessionRequest(BaseModel):
    label: NonEmptyStr


@router.patch("/{agent_id}/sessions/{session_id}")
def update_session_route(
    agent_id: str,
    session_id: str,
    req: UpdateSessionRequest,
    user: AuthedUser = Depends(get_current_user),
    session: dict = Depends(get_owned_session),
):
    data, status_code = update_chat_session_label(user.access_token, agent_id, session_id, req.label)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
