from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.powabase_client import signup, signin

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
def signup_route(req: AuthRequest):
    data, status_code = signup(req.email, req.password)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.post("/signin")
def signin_route(req: AuthRequest):
    data, status_code = signin(req.email, req.password)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
