from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    add_source_to_kb,
    ensure_document_delegation_clause,
    get_agent_registry_entry,
    upload_and_resolve_source_id,
    wait_for_source_extraction,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/file")
def ingest_file_route(
    file: UploadFile = File(...),
    agent_id_form: str | None = Form(default=None, alias="agent_id"),
    agent_id_query: str | None = Query(default=None, alias="agent_id"),
    user: AuthedUser = Depends(get_current_user),
):
    agent_id = agent_id_form or agent_id_query
    if not agent_id:
        raise HTTPException(status_code=422, detail="agent_id is required (form field or query param)")

    registry_rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")
    kb_id = registry_rows[0]["kb_id"]
    chatbot_id = registry_rows[0].get("chatbot_id")
    orchestration_entity_id = registry_rows[0].get("orchestration_entity_id")

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
            detail=f"Source extraction ended in status '{extraction_status}', cannot index",
        )

    data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)

    if chatbot_id and orchestration_entity_id:
        ensure_document_delegation_clause(user.access_token, chatbot_id, orchestration_entity_id)

    return data
