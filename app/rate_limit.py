from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    # Key on the raw bearer token, not a verified user id -- resolving the
    # token to a user requires a live call to Powabase's /auth/v1/user, and
    # doing that a second time here (on top of the get_current_user
    # dependency) would double the auth round-trips on every chat request.
    # A bad/expired token still gets its own bucket; get_current_user rejects
    # it with 401 before the route body runs regardless of rate-limit status.
    auth = request.headers.get("authorization")
    return auth if auth else get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
