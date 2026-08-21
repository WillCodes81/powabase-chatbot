from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.powabase_client import get_authenticated_user


@dataclass
class AuthedUser:
    id: str
    access_token: str


def get_current_user(authorization: str | None = Header(default=None)) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    token = authorization.removeprefix("Bearer ")
    data, status_code = get_authenticated_user(token)
    if status_code >= 400:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return AuthedUser(id=data["id"], access_token=token)
