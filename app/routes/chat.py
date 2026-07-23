from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.powabase_client import run_agent

router = APIRouter(tags=["chat"])

AGENT_ID = "afd58ad9-c115-4baf-a07d-cefcb6455668"


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat_route(req: ChatRequest):
    data, status_code = run_agent(AGENT_ID, req.message)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
