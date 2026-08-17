import logging
import threading
from collections import defaultdict

from app.powabase_client import deduct_user_credits

logger = logging.getLogger("app.credits")

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def user_credit_lock(user_id: str) -> threading.Lock:
    """
    Per-user lock serializing the check-run-deduct sequence in chat.py/
    chatbots.py, so two concurrent requests from the same user can't both
    pass the balance check before either deducts.

    Holds only within this process. deduct_credits itself is already
    atomic per-call (a single Postgres UPDATE), so concurrent deductions
    never corrupt the balance -- the race is in the pre-run balance check,
    which reads a stale snapshot before the (variable-cost, only-known-
    after-the-fact) run completes. Serializing per user closes that gap
    for this single-process deployment. If this app is ever run with
    multiple uvicorn workers or scaled across machines, this needs to
    move to a DB-level lock (e.g. a Postgres advisory lock keyed on
    user_id) instead -- an in-process lock can't coordinate across
    processes.
    """
    with _locks_guard:
        return _locks[user_id]


def deduct_credits_logged(access_token: str, user_id: str, tokens: int) -> None:
    """
    Best-effort credit deduction that never raises (a deduction failure
    must not cost the user their already-generated response), but -- unlike
    the bare `except Exception: pass` this replaces -- actually records
    what happened. Call this only while holding user_credit_lock(user_id).
    """
    try:
        data, status_code = deduct_user_credits(access_token, user_id, tokens)
    except Exception:
        logger.exception("credit deduction request failed user_id=%s tokens=%s", user_id, tokens)
        return

    if status_code >= 400:
        logger.error("credit deduction rejected user_id=%s tokens=%s status=%s body=%s", user_id, tokens, status_code, data)
        return

    remaining = data.get("tokens_remaining")
    if remaining is not None and remaining < 0:
        logger.warning(
            "credit balance went negative after deduction (concurrent-request overspend) user_id=%s tokens_deducted=%s tokens_remaining=%s",
            user_id,
            tokens,
            remaining,
        )
