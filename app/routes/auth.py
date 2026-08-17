from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.powabase_client import signup, signin
from app.rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRequest(BaseModel):
    email: str
    password: str


@router.post("/signup")
@limiter.limit("5/minute")
def signup_route(request: Request, req: AuthRequest):
    data, status_code = signup(req.email, req.password)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data


@router.post("/signin")
@limiter.limit("5/minute")
def signin_route(request: Request, req: AuthRequest):
    data, status_code = signin(req.email, req.password)
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=data)
    return data
