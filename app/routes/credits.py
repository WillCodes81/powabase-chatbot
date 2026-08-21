from fastapi import APIRouter, Depends

from app.deps import AuthedUser, get_current_user
from app.powabase_client import ensure_user_credits_row

router = APIRouter(tags=["credits"])


@router.get("/me/credits")
def get_my_credits_route(user: AuthedUser = Depends(get_current_user)):
    row = ensure_user_credits_row(user.access_token, user.id)
    return {"tokens_remaining": row["tokens_remaining"], "tokens_used_total": row["tokens_used_total"]}
