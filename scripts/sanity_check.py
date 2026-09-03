import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-user-b@example.com", "password": "SanityTest123!"}

DOC_A = (b"The secret code for Project Aurora is BLUE-42.", "docA.txt")
DOC_B = (b"The secret code for Project Titan is RED-99.", "docB.txt")


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


def ingest(token, agent_id, file_bytes, filename):
    return requests.post(
        f"{APP}/ingest/file",
        headers={"Authorization": f"Bearer {token}"},
        data={"agent_id": agent_id},
        files={"file": (filename, file_bytes)},
    )


def chat(token, agent_id, message):
    return requests.post(
        f"{APP}/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_id": agent_id, "message": message},
    )


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity Agent A")
    agent_b = create_agent(token_b, "Sanity Agent B")
    print("agent A:", agent_a["agent_id"])
    print("agent B:", agent_b["agent_id"])

    r = ingest(token_a, agent_a["agent_id"], *DOC_A)
    assert r.status_code < 400, f"ingest A failed: {r.status_code} {r.text}"
    print("ingest A ok")

    r = ingest(token_b, agent_b["agent_id"], *DOC_B)
    assert r.status_code < 400, f"ingest B failed: {r.status_code} {r.text}"
    print("ingest B ok")

    r = chat(token_a, agent_a["agent_id"], "What is the secret code for Project Aurora?")
    assert r.status_code == 200, f"chat A failed: {r.status_code} {r.text}"
    content_a = r.json()["content"]
    assert "BLUE-42" in content_a, f"agent A answer missing its own doc's fact: {content_a}"
    assert "RED-99" not in content_a, f"agent A leaked agent B's fact: {content_a}"
    print("chat A ok:", content_a)

    r = chat(token_b, agent_b["agent_id"], "What is the secret code for Project Titan?")
    assert r.status_code == 200, f"chat B failed: {r.status_code} {r.text}"
    content_b = r.json()["content"]
    assert "RED-99" in content_b, f"agent B answer missing its own doc's fact: {content_b}"
    assert "BLUE-42" not in content_b, f"agent B leaked agent A's fact: {content_b}"
    print("chat B ok:", content_b)

    r = chat(token_a, agent_b["agent_id"], "What is the secret code for Project Titan?")
    assert r.status_code == 403, f"expected 403 for cross-user chat, got {r.status_code} {r.text}"
    print("cross-user chat blocked with 403 as expected")

    r = ingest(token_a, agent_b["agent_id"], b"malicious content", "hack.txt")
    assert r.status_code == 403, f"expected 403 for cross-user ingest, got {r.status_code} {r.text}"
    print("cross-user ingest blocked with 403 as expected")

    print("\nALL SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
