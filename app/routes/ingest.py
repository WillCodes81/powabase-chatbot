import time

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.powabase_client import add_source_to_kb, get_source, upload_source

router = APIRouter(prefix="/ingest", tags=["ingest"])

KNOWLEDGE_BASE_ID = "35ab71c9-a1e5-4034-a99c-c6eae2dd41b3"

TERMINAL_EXTRACTION_STATUSES = {"extracted", "attention_required", "failed", "cancelled"}
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 120


@router.post("/file")
def ingest_file_route(file: UploadFile = File(...)):
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

    data, status_code = add_source_to_kb(KNOWLEDGE_BASE_ID, source_id)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
