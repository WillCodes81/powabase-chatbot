import logging
import time
from contextlib import contextmanager

from fastapi import HTTPException

from app.powabase_client import acquire_credit_lock, deduct_user_credits, release_credit_lock

logger = logging.getLogger("app.credits")

LOCK_POLL_INTERVAL_SECONDS = 0.2
LOCK_WAIT_TIMEOUT_SECONDS = 90


@contextmanager
def user_credit_lock(access_token: str, user_id: str):
    """
    Serializes the check-run-deduct sequence in chat.py/chatbots.py per user,
    across ALL app processes and machines -- backed by a database-level
    mutex (see acquire_credit_lock/release_credit_lock in powabase_client.py),
    not an in-process threading.Lock.

    An in-process Lock previously stood in for this and only protected a
    single worker process: confirmed live that running this app with
    multiple uvicorn workers let N concurrent requests each pass the
    pre-run balance check (N == worker count) before any of their
    deductions landed, driving the balance deeply negative. This replaces
    that with a real cross-process lock so the check-run-deduct span is
    genuinely atomic regardless of deployment topology.

    Polls to acquire (Postgres/PostgREST has no long-poll/blocking-wait
    primitive reachable over REST) up to LOCK_WAIT_TIMEOUT_SECONDS, then
    fails closed with 429 rather than proceeding unprotected -- silently
    skipping the lock on contention would reintroduce the exact race this
    replaces. Always releases on the way out, including on error, so one
    failed request can't lock a user out of their own account (a stale
    lock is also independently reclaimable after CREDIT_LOCK_LEASE_SECONDS
    as a second line of defense against a crash between acquire/release).
    """
    deadline = time.monotonic() + LOCK_WAIT_TIMEOUT_SECONDS
    acquired = acquire_credit_lock(access_token, user_id)
    while not acquired and time.monotonic() < deadline:
        time.sleep(LOCK_POLL_INTERVAL_SECONDS)
        acquired = acquire_credit_lock(access_token, user_id)

    if not acquired:
        raise HTTPException(status_code=429, detail="Too many concurrent requests on this account. Try again shortly.")

    try:
        yield
    finally:
        release_credit_lock(access_token, user_id)


def deduct_credits_logged(access_token: str, user_id: str, tokens: int) -> None:
    """
    Best-effort credit deduction that never raises (a deduction failure
    must not cost the user their already-generated response), but -- unlike
    the bare `except Exception: pass` this replaces -- actually records
    what happened. Call this only while holding user_credit_lock(access_token, user_id).
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
            "credit balance went negative after deduction (single request cost exceeded remaining balance) user_id=%s tokens_deducted=%s tokens_remaining=%s",
            user_id,
            tokens,
            remaining,
        )
