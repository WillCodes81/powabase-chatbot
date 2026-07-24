import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.deps import AuthedUser, get_current_user
from app.powabase_client import add_source_to_kb, get_agent_registry_entry, get_source, upload_source

router = APIRouter(prefix="/ingest", tags=["ingest"])

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


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
            detail=f"Source extraction ended in status '{extraction_status}', cannot index",
        )

    data, status_code = add_source_to_kb(kb_id, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
