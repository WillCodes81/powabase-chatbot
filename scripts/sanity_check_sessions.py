import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-sessions-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-sessions-user-b@example.com", "password": "SanityTest123!"}


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


def chat(token, agent_id, message, session_id=None, label=None):
    body = {"agent_id": agent_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    if label:
        body["label"] = label
    return requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity Sessions Agent A")
    agent_b = create_agent(token_b, "Sanity Sessions Agent B")
    print("agent A:", agent_a["agent_id"])
    print("agent B:", agent_b["agent_id"])

    # --- Feature 1: multi-turn history ---
    r = chat(token_a, agent_a["agent_id"], "Remember this: my favorite number is 8842. Just say OK.", label="numbers chat")
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    print("turn 1 ok, session:", session_id)

    r = chat(token_a, agent_a["agent_id"], "What's my favorite number?", session_id=session_id)
    assert r.status_code == 200 and "8842" in r.json()["content"], r.text
    print("turn 2 ok: history recalled ->", r.json()["content"])

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and any(s["session_id"] == session_id and s["label"] == "numbers chat" for s in r.json())
    print("session listed with label ok")

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/messages", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and len(r.json()["messages"]) == 4
    print("message transcript ok:", len(r.json()["messages"]), "messages")

    # --- Feature 2: per-session document, not in the KB ---
    doc = b"SESSION-ONLY FACT: the launch codename is PLUM-VORTEX-77."
    r = requests.post(
        f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token_a}"},
        files={"file": ("memo.txt", doc)},
    )
    assert r.status_code == 200, r.text
    print("document attached ok")

    r = chat(token_a, agent_a["agent_id"], "What is the launch codename mentioned in the attached memo?", session_id=session_id)
    assert r.status_code == 200 and "PLUM-VORTEX-77" in r.json()["content"], r.text
    print("document visible in its own session ok")

    r = chat(token_a, agent_a["agent_id"], "What is the launch codename?")  # fresh session, no attachment
    assert r.status_code == 200 and "PLUM-VORTEX-77" not in r.json()["content"], r.text
    print("document correctly absent from a different session ok")

    # --- Cross-user isolation still holds for the new endpoints ---
    r = chat(token_b, agent_a["agent_id"], "hi", session_id=session_id)
    assert r.status_code == 403
    print("cross-user session continuation blocked ok")

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user session listing blocked ok")

    r = requests.post(
        f"{APP}/agents/{agent_a['agent_id']}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token_b}"},
        files={"file": ("hack.txt", b"nope")},
    )
    assert r.status_code == 403
    print("cross-user attach-document blocked ok")

    print("\nALL SESSION + DOCUMENT SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
