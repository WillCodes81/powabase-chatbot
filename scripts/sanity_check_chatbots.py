import time

import requests

from app.config import settings

BASE = settings.powabase_url
SVC = settings.powabase_service_key
ANON = settings.powabase_anon_key
APP = "http://127.0.0.1:8000"
SVC_H = {"apikey": SVC, "Authorization": f"Bearer {SVC}"}

USER_A = {"email": "sanity-chatbot-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-chatbot-user-b@example.com", "password": "SanityTest123!"}


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


def create_chatbot(token, name, agent_name, role_description):
    r = requests.post(
        f"{APP}/chatbots",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "agent_name": agent_name, "role_description": role_description},
    )
    r.raise_for_status()
    return r.json()


def add_agent(token, chatbot_id, name, role_description):
    r = requests.post(
        f"{APP}/chatbots/{chatbot_id}/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "role_description": role_description},
    )
    r.raise_for_status()
    return r.json()


def ingest(token, agent_id, content, filename):
    r = requests.post(
        f"{APP}/ingest/file",
        headers={"Authorization": f"Bearer {token}"},
        data={"agent_id": agent_id},
        files={"file": (filename, content)},
    )
    r.raise_for_status()
    return r.json()


def wait_for_kb_indexed(kb_id, source_id, timeout=90):
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}/sources", headers=SVC_H)
        r.raise_for_status()
        items = r.json()["items"]
        match = next((i for i in items if i["source_id"] == source_id), None)
        if match and match["index_status"] == "indexed":
            return
        if match and match["index_status"] == "failed":
            raise AssertionError(f"indexing failed: {match}")
        time.sleep(2)
        elapsed += 2
    raise AssertionError(f"timed out waiting for source {source_id} to index into kb {kb_id}")


def chat(token, chatbot_id, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    return requests.post(f"{APP}/chatbots/{chatbot_id}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    # --- 1. Two-subagent chatbot, each with its own fabricated fact ---
    result = create_chatbot(token_a, "Sanity Chatbot", "Sanity WiFi Agent", "Answers office WiFi questions.")
    chatbot_id = result["chatbot"]["id"]
    orchestrator_id = result["chatbot"]["orchestrator_id"]
    agent_wifi = result["agent"]

    agent_parking = add_agent(token_a, chatbot_id, "Sanity Parking Agent", "Answers parking garage questions.")

    doc_wifi = ingest(token_a, agent_wifi["agent_id"], b"OFFICE FACT: the WiFi password is TRIDENT-OWL-88.", "wifi.txt")
    wait_for_kb_indexed(agent_wifi["kb_id"], doc_wifi["source_id"])

    doc_parking = ingest(token_a, agent_parking["agent_id"], b"OFFICE FACT: the parking code is 3307.", "parking.txt")
    wait_for_kb_indexed(agent_parking["kb_id"], doc_parking["source_id"])

    r = chat(token_a, chatbot_id, "What is the WiFi password and the parking code? Give me both, verbatim.")
    assert r.status_code == 200, r.text
    content = r.json()["content"]
    session_id = r.json()["session_id"]
    assert "TRIDENT-OWL-88" in content, f"missing wifi fact: {content}"
    assert "3307" in content, f"missing parking fact: {content}"
    print("chatbot correctly drew on both subagents' isolated KBs:", content)

    # --- 2. Delete one of two subagents; the other survives untouched ---
    r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_parking['agent_id']}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json()["chatbot_deleted"] is False, r.text
    print("deleted parking agent, chatbot survives:", r.json())

    rk = requests.get(f"{BASE}/api/knowledge-bases/{agent_wifi['kb_id']}", headers=SVC_H)
    assert rk.status_code == 200, "surviving agent's KB must be untouched"
    print("surviving agent's KB confirmed intact via Powabase API")

    r = chat(token_a, chatbot_id, "What is the WiFi password?", session_id=session_id)
    assert r.status_code == 200 and "TRIDENT-OWL-88" in r.json()["content"], r.text
    print("chatbot still functions correctly with the remaining agent:", r.json()["content"])

    r = requests.get(f"{BASE}/api/orchestrations/{orchestrator_id}", headers=SVC_H)
    assert r.status_code == 200 and len(r.json()["entities"]) == 1
    print("orchestrator confirmed still alive with exactly 1 entity")

    # --- 3. Single-agent chatbot: delete its one agent -> orchestrator actually gone ---
    solo = create_chatbot(token_a, "Sanity Solo Chatbot", "Sanity Solo Agent", "Handles everything.")
    solo_chatbot_id = solo["chatbot"]["id"]
    solo_orchestrator_id = solo["chatbot"]["orchestrator_id"]
    solo_agent_id = solo["agent"]["agent_id"]

    r = requests.delete(f"{APP}/chatbots/{solo_chatbot_id}/agents/{solo_agent_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json() == {"deleted": True, "chatbot_deleted": True}, r.text
    print("deleted the only agent on a single-agent chatbot:", r.json())

    r = requests.get(f"{BASE}/api/orchestrations/{solo_orchestrator_id}", headers=SVC_H)
    assert r.status_code == 404, f"orchestrator must be actually gone, got {r.status_code}"
    print("CONFIRMED via Powabase API: no orphaned orchestrator survives single-agent deletion")

    # --- 4. Full chatbot deletion with multiple agents: verify every KB is gone via Powabase's API ---
    multi = create_chatbot(token_a, "Sanity Multi Chatbot", "Sanity Multi Agent One", "Handles topic one.")
    multi_chatbot_id = multi["chatbot"]["id"]
    multi_orchestrator_id = multi["chatbot"]["orchestrator_id"]
    kb_one = multi["agent"]["kb_id"]

    agent_two = add_agent(token_a, multi_chatbot_id, "Sanity Multi Agent Two", "Handles topic two.")
    kb_two = agent_two["kb_id"]

    r = requests.delete(f"{APP}/chatbots/{multi_chatbot_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200 and r.json() == {"deleted": True, "agents_deleted": 2}, r.text
    print("full chatbot deletion:", r.json())

    for kb_id, label in [(kb_one, "one"), (kb_two, "two")]:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}", headers=SVC_H)
        assert r.status_code == 404, f"kb {label} must be gone, got {r.status_code}"
    print("CONFIRMED via Powabase API: every subagent KB is actually gone after full deletion")

    r = requests.get(f"{BASE}/api/orchestrations/{multi_orchestrator_id}", headers=SVC_H)
    assert r.status_code == 404
    print("CONFIRMED: orchestrator gone after full deletion")

    # --- 5. Cross-user: user B cannot touch user A's remaining chatbot ---
    r = requests.post(f"{APP}/chatbots/{chatbot_id}/agents", headers={"Authorization": f"Bearer {token_b}"}, json={
        "name": "hostile", "role_description": "hostile"
    })
    assert r.status_code == 403
    print("cross-user add-agent blocked")

    r = requests.delete(f"{APP}/chatbots/{chatbot_id}/agents/{agent_wifi['agent_id']}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user remove-agent blocked")

    r = chat(token_b, chatbot_id, "hi")
    assert r.status_code == 403
    print("cross-user chat blocked")

    r = requests.delete(f"{APP}/chatbots/{chatbot_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user full delete blocked")

    print("\nALL CHATBOT ORCHESTRATION SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
