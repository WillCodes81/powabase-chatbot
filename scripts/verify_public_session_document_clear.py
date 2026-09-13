import requests

from app.config import settings
from app.powabase_client import get_public_share_session

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key
APP = "http://127.0.0.1:8000"

USER = {"email": "verify-doc-clear-user@example.com", "password": "SanityTest123!"}


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


def get_kb(kb_id):
    r = requests.get(
        f"{settings.powabase_url}/api/knowledge-bases/{kb_id}",
        headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"},
    )
    return r.status_code


def main():
    print("--- Setup: owner, source agent, public share, one visitor session with a chat + a document ---")
    token = signup_or_signin(USER)

    source_agent = create_agent(token, "Verify Doc Clear Source")
    source_agent_id = source_agent["agent_id"]

    share = create_public_share(token, "Verify Doc Clear Share", source_agent_id)
    share_id = share["share_id"]
    print(f"source agent: {source_agent_id}  share: {share_id}")

    anon_session_id = "anon-doc-clear-session-1"
    public_chat(share_id, "Hello, this is a test message before New Session.", anon_session_id)
    public_attach_document(share_id, anon_session_id, "test.pdf")
    print("chat + document created for one anonymous session")

    rows, sc = get_public_share_session(share_id, anon_session_id)
    assert sc < 400 and rows, f"expected session row to exist, got {sc}: {rows}"
    session_before = rows[0]
    kb_id = session_before["kb_id"]
    powabase_session_id = session_before["powabase_session_id"]
    print(f"session row before: kb_id={kb_id} powabase_session_id={powabase_session_id}")
    assert kb_id, "expected kb_id to be set after attaching a document"
    assert powabase_session_id, "expected powabase_session_id to be set after chatting"
    assert get_kb(kb_id) == 200, "session KB should exist before New Session"

    print("\n--- Call the new document-clear route (what 'New Session' now triggers) ---")
    r = requests.delete(f"{APP}/public/{share_id}/sessions/{anon_session_id}/document")
    print(f"status: {r.status_code} body: {r.text}")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    assert r.json() == {"deleted": True, "kb_deleted": True}

    print("\n--- Verify: KB gone, kb_id cleared, but session row/powabase_session_id/transcript intact ---")
    kb_status = get_kb(kb_id)
    print(f"KB lookup after clear: status={kb_status}")
    assert kb_status >= 400, f"expected KB to be deleted, got status {kb_status}"
    print("PASS: document's knowledge base deleted")

    rows, sc = get_public_share_session(share_id, anon_session_id)
    assert sc < 400 and rows, f"expected session row to still exist, got {sc}: {rows}"
    session_after = rows[0]
    print(f"session row after: kb_id={session_after['kb_id']} powabase_session_id={session_after['powabase_session_id']}")
    assert session_after["kb_id"] is None, "expected kb_id to be cleared to null"
    assert session_after["powabase_session_id"] == powabase_session_id, "powabase_session_id must survive untouched"
    print("PASS: session row survives with kb_id cleared and powabase_session_id intact")

    print("\n--- Verify: owner's session history still shows this session (transcript preserved) ---")
    r = requests.get(f"{APP}/agents/{source_agent_id}/public-share/sessions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    sessions = r.json()
    print(f"sessions: {sessions}")
    matching = next((s for s in sessions if s["anon_session_id"] == anon_session_id), None)
    assert matching is not None, "session must still appear in owner's Session History"
    assert matching["has_conversation"] is True, "transcript must still be marked present"
    assert matching["has_document"] is False, "document must no longer be marked present"
    print("PASS: Session History still shows the session with its transcript, document flag now false")

    r = requests.get(
        f"{APP}/agents/{source_agent_id}/public-share/sessions/{matching['id']}/transcript",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    transcript = r.json()
    print(f"transcript messages: {transcript['messages']}")
    assert len(transcript["messages"]) >= 2, "expected the original chat messages to still be fetchable"
    print("PASS: transcript content itself is still intact and fetchable")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
