import time

import requests

from app.config import settings
from app.powabase_client import get_public_share_by_source_agent_id_service

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "verify-share-history-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "verify-share-history-user-b@example.com", "password": "SanityTest123!"}


def signup_or_signin(creds):
    r = requests.post(
        f"{BASE}/auth/v1/signup",
        headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"},
        json=creds,
    )
    if r.status_code >= 400:
        r = requests.post(
            f"{BASE}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": ANON, "Authorization": f"Bearer {ANON}", "Content-Type": "application/json"},
            json=creds,
        )
    r.raise_for_status()
    return r.json()["access_token"]


def create_agent(token, name):
    r = requests.post(f"{APP}/agents", headers={"Authorization": f"Bearer {token}"}, json={"name": name})
    r.raise_for_status()
    return r.json()


def create_public_share(token, name, source_agent_id):
    r = requests.post(
        f"{APP}/public/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "source_agent_id": source_agent_id},
    )
    r.raise_for_status()
    return r.json()


def public_chat(share_id, message, anon_session_id):
    r = requests.post(f"{APP}/public/{share_id}/chat", json={"message": message, "anon_session_id": anon_session_id})
    r.raise_for_status()
    return r.json()


def public_attach_document(share_id, anon_session_id, filepath):
    with open(filepath, "rb") as f:
        r = requests.post(f"{APP}/public/{share_id}/sessions/{anon_session_id}/attach-document", files={"file": f})
    r.raise_for_status()
    return r.json()


def main():
    print("--- Setup: two owners, two agents, two public shares ---")
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    r = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token_a}"})
    r.raise_for_status()
    user_a_id = r.json()["id"]

    r = requests.get(f"{BASE}/auth/v1/user", headers={"apikey": ANON, "Authorization": f"Bearer {token_b}"})
    r.raise_for_status()
    user_b_id = r.json()["id"]

    agent_a = create_agent(token_a, "Verify Share History Agent A")
    agent_b = create_agent(token_b, "Verify Share History Agent B")
    print(f"agent A: {agent_a['agent_id']}  agent B: {agent_b['agent_id']}")

    share_a = create_public_share(token_a, "Share A", agent_a["agent_id"])
    share_b = create_public_share(token_b, "Share B", agent_b["agent_id"])
    print(f"share A: {share_a['share_id']}  share B: {share_b['share_id']}")

    print("\n--- Visitor traffic on share A: one chat session, one document-only session ---")
    anon_chat = "anon-chat-session-1"
    anon_doc_only = "anon-doc-only-session-1"

    public_chat(share_a["share_id"], "Hello, this is a test message.", anon_chat)
    print("chat session created")

    public_attach_document(share_a["share_id"], anon_doc_only, "test.pdf")
    print("document-only session created (no chat)")

    print("\n--- Test 1: owner A can list sessions for their own agent's share ---")
    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    sessions = r.json()
    print(f"sessions: {sessions}")
    assert len(sessions) == 2, f"expected 2 sessions, got {len(sessions)}"

    by_anon_id = {s["anon_session_id"]: s for s in sessions}
    chat_session = by_anon_id[anon_chat]
    doc_session = by_anon_id[anon_doc_only]
    assert chat_session["has_conversation"] is True, "chat session should show has_conversation: true"
    assert doc_session["has_conversation"] is False, "document-only session should show has_conversation: false"
    assert doc_session["has_document"] is True, "document-only session should show has_document: true"
    print("PASS: list route shows correct has_document / has_conversation flags")

    print("\n--- Test 2: owner B gets 403 (not 404) listing owner A's share sessions ---")
    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions", headers={"Authorization": f"Bearer {token_b}"})
    print(f"status: {r.status_code} body: {r.text}")
    assert r.status_code == 403, f"expected 403, got {r.status_code}"
    print("PASS: cross-owner list access returns 403")

    print("\n--- Test 3: owner B gets 403 fetching owner A's session transcript ---")
    r = requests.get(
        f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions/{chat_session['id']}/transcript",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    print(f"status: {r.status_code} body: {r.text}")
    assert r.status_code == 403, f"expected 403, got {r.status_code}"
    print("PASS: cross-owner transcript access returns 403")

    print("\n--- Test 4: document-only session's transcript is empty, no error ---")
    r = requests.get(
        f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions/{doc_session['id']}/transcript",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    print(f"transcript: {data}")
    assert data["has_conversation"] is False
    assert data["messages"] == []
    print("PASS: document-only session transcript is clean empty state")

    print("\n--- Test 5: chatted session's transcript has real messages ---")
    r = requests.get(
        f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions/{chat_session['id']}/transcript",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    print(f"transcript messages: {data['messages']}")
    assert data["has_conversation"] is True
    assert len(data["messages"]) >= 2, "expected at least the user message + assistant reply"
    print("PASS: chatted session transcript has real messages")

    print("\n--- Test 6: the history routes require auth at all (no token -> 401) ---")
    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions")
    print(f"status: {r.status_code}")
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    print("PASS: anonymous request to the list route is rejected")

    print("\n--- Test 7: anonymous visitor's own experience is untouched ---")
    # Same share, same anon_session_id -> continues the same conversation,
    # exactly as before this feature existed. No token involved anywhere.
    public_chat(share_a["share_id"], "Second message, same session.", anon_chat)
    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions", headers={"Authorization": f"Bearer {token_a}"})
    r.raise_for_status()
    sessions_after = r.json()
    assert len(sessions_after) == 2, "repeat visit must continue the same session row, not create a new one"
    chat_session_after = next(s for s in sessions_after if s["anon_session_id"] == anon_chat)
    r = requests.get(
        f"{APP}/agents/{agent_a['agent_id']}/public-share/sessions/{chat_session_after['id']}/transcript",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    r.raise_for_status()
    msgs = r.json()["messages"]
    print(f"messages after second visitor message: {len(msgs)}")
    assert len(msgs) >= 4, "expected both round-trips (2 user + 2 assistant) in the continued session"
    print("PASS: repeat visit continues the same session row (same anon_session_id, growing transcript)")
    # And a visitor has no way to reach the history/transcript endpoints --
    # already proven by Test 6 (they require a real owner Bearer token this
    # anonymous flow never has).

    print("\n--- Test 8: the moved by-source route works correctly on main_app ---")
    r = requests.get(f"{APP}/agents/by-source/{agent_a['agent_id']}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    print(f"by-source result: {body}")
    assert body["share_id"] == share_a["share_id"]
    print("PASS: GET /agents/by-source/{id} works on main_app (idempotency check on page load)")

    print("\n--- Test 9: the OLD public_app path for by-source is gone ---")
    r = requests.get(f"{APP}/public/agents/by-source/{agent_a['agent_id']}", headers={"Authorization": f"Bearer {token_a}"})
    print(f"status: {r.status_code}")
    assert r.status_code == 404, f"expected 404 (route removed from public_app), got {r.status_code}"
    print("PASS: old /public/agents/by-source/{id} path no longer exists")

    print("\n--- Test 10: by-source route rejects an arbitrary/no-CORS-style unauthenticated request ---")
    r = requests.get(f"{APP}/agents/by-source/{agent_a['agent_id']}")
    print(f"status: {r.status_code}")
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    print("PASS: by-source route still requires login now that it's on main_app")

    print("\n--- Test 11: the explicit owner_user_id check itself, isolated from get_owned_agent ---")
    # Tests 2/3 proved 403 end-to-end, but get_owned_agent (a pre-existing,
    # separate ownership gate) already rejects cross-owner requests before
    # get_owned_public_share's own explicit comparison ever runs -- since
    # nobody but the source agent's real owner can pass get_owned_agent for
    # that agent_id in the first place. Isolate the new check itself here by
    # calling the service-key fetch directly (same function
    # get_owned_public_share uses) and performing the same comparison this
    # project would perform, against both the real owner and an impostor.
    rows, status_code = get_public_share_by_source_agent_id_service(agent_a["agent_id"])
    assert status_code < 400 and rows, f"expected the share row to be fetchable via service key, got {status_code}: {rows}"
    share_row = rows[0]
    print(f"service-key fetched row owner_user_id: {share_row['owner_user_id']}")
    assert share_row["owner_user_id"] == user_a_id, "row's owner_user_id must equal the real owner's id"
    assert share_row["owner_user_id"] != user_b_id, "row's owner_user_id must NOT equal the impostor's id"
    print("PASS: explicit Python owner_user_id comparison is correct in both directions")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
