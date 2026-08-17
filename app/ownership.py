from fastapi import Depends, HTTPException

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_chatbot_entry,
    get_chatbot_session_entry,
)


def get_owned_agent(agent_id: str, user: AuthedUser = Depends(get_current_user)) -> dict:
    rows, status_code = get_agent_registry_entry(user.access_token, agent_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=403, detail="Agent not found or not owned by this user")
    return rows[0]


def get_owned_session(
    agent_id: str,
    session_id: str,
    user: AuthedUser = Depends(get_current_user),
    agent: dict = Depends(get_owned_agent),
) -> dict:
    rows, status_code = get_chat_session_entry(user.access_token, agent_id, session_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=404, detail="Session not found for this agent")
    return rows[0]


def get_owned_chatbot(chatbot_id: str, user: AuthedUser = Depends(get_current_user)) -> dict:
    rows, status_code = get_chatbot_entry(user.access_token, chatbot_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=403, detail="Chatbot not found or not owned by this user")
    return rows[0]


def get_owned_chatbot_session(
    chatbot_id: str,
    session_id: str,
    user: AuthedUser = Depends(get_current_user),
    chatbot: dict = Depends(get_owned_chatbot),
) -> dict:
    rows, status_code = get_chatbot_session_entry(user.access_token, chatbot_id, session_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=404, detail="Session not found for this chatbot")
    return rows[0]
