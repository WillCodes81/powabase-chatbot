from fastapi import Depends, HTTPException

from app.deps import AuthedUser, get_current_user
from app.powabase_client import (
    get_agent_registry_entry,
    get_chat_session_entry,
    get_chatbot_entry,
    get_chatbot_session_entry,
    get_public_share_by_source_agent_id_service,
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


def get_owned_public_share(agent_id: str, user: AuthedUser = Depends(get_current_user), agent: dict = Depends(get_owned_agent)) -> dict:
    """
    public_share_sessions has no RLS policies at all, so unlike every other
    get_owned_* dependency here, RLS can't be relied on to scope this. The
    row is fetched with the service key (bypassing RLS entirely) and
    owner_user_id is compared against the caller's id explicitly, in Python,
    before any session data behind this share is touched.
    """
    rows, status_code = get_public_share_by_source_agent_id_service(agent_id)
    if status_code >= 400 or not rows:
        raise HTTPException(status_code=404, detail="No public share exists for this agent")
    share = rows[0]
    if share["owner_user_id"] != user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this public share")
    return share


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
