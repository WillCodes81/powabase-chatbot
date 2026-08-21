from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

from app.powabase_client import get_chat_session_by_token, query_context_handler

router = APIRouter(prefix="/tools", tags=["tools"])


class SessionContextToolBody(BaseModel):
    query: str
    session_token: str | None = None


@router.post("/session-context")
def session_context_tool_route(body: SessionContextToolBody):
    session_token = (body.session_token or "").strip()
    if not session_token:
        return PlainTextResponse("No session context available: missing session token.")

    rows, status_code = get_chat_session_by_token(session_token)
    if status_code >= 400 or not rows:
        return PlainTextResponse("No session context available: invalid session token.")

    kb_id = rows[0].get("kb_id")
    if not kb_id:
        return PlainTextResponse("No document has been attached to this session yet. There is nothing to search.")

    data, status_code = query_context_handler(kb_id, body.query)
    if status_code >= 400:
        return PlainTextResponse("Unable to search the session's document right now.")

    formatted = data.get("formatted_context") or "No relevant content found for that query."
    return PlainTextResponse(formatted)
