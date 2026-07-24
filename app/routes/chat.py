from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.deps import AuthedUser, get_current_user
from app.powabase_client import get_agent_registry_entry, run_agent

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    agent_id: str
    message: str


@router.post("/chat")
def chat_route(req: ChatRequest, user: AuthedUser = Depends(get_current_user)):
    registry_rows, status_code = get_agent_registry_entry(user.access_token, req.agent_id)
    if status_code >= 400 or not registry_rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")

    data, status_code = run_agent(req.agent_id, req.message)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
