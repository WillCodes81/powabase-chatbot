import time

import requests

from app.config import settings

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key
APP = "http://127.0.0.1:8000"

USER_A = {"email": "sanity-kb-user-a@example.com", "password": "SanityTest123!"}
USER_B = {"email": "sanity-kb-user-b@example.com", "password": "SanityTest123!"}


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


def chat(token, agent_id, message, session_id=None):
    body = {"agent_id": agent_id, "message": message}
    if session_id:
        body["session_id"] = session_id
    return requests.post(f"{APP}/chat", headers={"Authorization": f"Bearer {token}"}, json=body)


def attach_document(token, agent_id, session_id, content_bytes, filename):
    return requests.post(
        f"{APP}/agents/{agent_id}/sessions/{session_id}/attach-document",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (filename, content_bytes)},
    )


def delete_session(token, agent_id, session_id):
    return requests.delete(f"{APP}/agents/{agent_id}/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"})


def latest_run_tool_calls(session_id):
    r = requests.get(f"{BASE}/api/sessions/{session_id}/runs", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
    r.raise_for_status()
    runs = r.json()["runs"]
    latest = sorted(runs, key=lambda run: run["created_at"])[-1]
    return latest.get("tool_calls") or []


def wait_for_kb_indexed(kb_id, source_id, timeout=60):
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id}/sources", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
        r.raise_for_status()
        items = r.json()["items"]
        match = next((i for i in items if i["source_id"] == source_id), None)
        if match and match["index_status"] == "indexed":
            return
        if match and match["index_status"] == "failed":
            raise AssertionError(f"indexing failed for source {source_id}: {match}")
        time.sleep(2)
        elapsed += 2
    raise AssertionError(f"timed out waiting for source {source_id} to index into kb {kb_id}")


def main():
    token_a = signup_or_signin(USER_A)
    token_b = signup_or_signin(USER_B)

    agent_a = create_agent(token_a, "Sanity KB Agent A")
    print("agent A:", agent_a["agent_id"])

    # --- 1. No document attached: normal chat + tool reports nothing to search ---
    r = chat(token_a, agent_a["agent_id"], "Say OK, nothing else.")
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    print("turn 1 (no doc) ok, session:", session_id)

    r = chat(token_a, agent_a["agent_id"], "Is there a document attached to this conversation? If you're unsure, check.", session_id=session_id)
    assert r.status_code == 200, r.text
    print("turn 2 (no doc, tool-checking question) ok:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    for call in tool_calls:
        if call["tool_name"] == "session_context_search":
            assert "nothing to search" in call["result"].lower() or "no document" in call["result"].lower(), call
            print("  tool correctly reported nothing to search:", call["result"])

    # --- 2. Attach a document, ask something requiring it ---
    doc1 = b"CLASSIFIED PROJECT FACT: the reactor override code is NEON-7734."
    r = attach_document(token_a, agent_a["agent_id"], session_id, doc1, "doc1.txt")
    assert r.status_code == 200, r.text
    kb_id_1 = r.json()["kb_id"]
    source_id_1 = r.json()["source_id"]
    print("attach doc1 ok, kb_id:", kb_id_1)
    wait_for_kb_indexed(kb_id_1, source_id_1)

    r = chat(token_a, agent_a["agent_id"], "What is the reactor override code mentioned in the attached document?", session_id=session_id)
    assert r.status_code == 200 and "NEON-7734" in r.json()["content"], r.text
    print("doc1 fact correctly answered:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    assert any(c["tool_name"] == "session_context_search" for c in tool_calls), "expected the tool to be called for a doc-requiring question"
    print("  confirmed: tool was called for the doc-requiring question")

    # --- 3. Same session, unrelated question: tool should NOT be pulled in unnecessarily ---
    r = chat(token_a, agent_a["agent_id"], "What is 17 times 4? Answer with just the number.", session_id=session_id)
    assert r.status_code == 200, r.text
    print("unrelated question answered:", r.json()["content"])
    tool_calls = latest_run_tool_calls(session_id)
    called = any(c["tool_name"] == "session_context_search" for c in tool_calls)
    print(f"  session_context_search called for unrelated question: {called} (expected False)")
    assert not called, "efficiency fix failed: tool was called for a question unrelated to the document"

    # --- 4. Second document, same session: both searchable via the same session KB ---
    doc2 = b"SECOND FACT: the evacuation rally point is GATE-ORCHID-12."
    r = attach_document(token_a, agent_a["agent_id"], session_id, doc2, "doc2.txt")
    assert r.status_code == 200, r.text
    kb_id_2 = r.json()["kb_id"]
    source_id_2 = r.json()["source_id"]
    assert kb_id_2 == kb_id_1, f"expected the SAME session kb reused, got {kb_id_2} vs {kb_id_1}"
    print("attach doc2 ok, reused same kb_id:", kb_id_2)
    wait_for_kb_indexed(kb_id_2, source_id_2)

    r = chat(token_a, agent_a["agent_id"], "What is the reactor override code?", session_id=session_id)
    assert r.status_code == 200 and "NEON-7734" in r.json()["content"], r.text
    print("doc1 fact still answerable after doc2 attached:", r.json()["content"])

    r = chat(token_a, agent_a["agent_id"], "What is the evacuation rally point?", session_id=session_id)
    assert r.status_code == 200 and "GATE-ORCHID-12" in r.json()["content"], r.text
    print("doc2 fact answerable:", r.json()["content"])

    # --- 5. Delete the session: confirm the KB is actually gone via Powabase's API directly ---
    r = delete_session(token_a, agent_a["agent_id"], session_id)
    assert r.status_code == 200 and r.json()["kb_deleted"] is True, r.text
    print("session delete ok:", r.json())

    r = requests.get(f"{BASE}/api/knowledge-bases/{kb_id_1}", headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"})
    assert r.status_code == 404, f"expected the kb to be gone (404), got {r.status_code}: {r.text}"
    print("confirmed via Powabase API: session kb is actually deleted")

    # --- 6. Cross-user isolation ---
    r2 = chat(token_a, agent_a["agent_id"], "Say OK.")
    assert r2.status_code == 200
    session_id_2 = r2.json()["session_id"]
    doc3 = b"USER A PRIVATE FACT: the vault combination is 91-42-83."
    r = attach_document(token_a, agent_a["agent_id"], session_id_2, doc3, "doc3.txt")
    assert r.status_code == 200, r.text
    kb_id_3 = r.json()["kb_id"]
    source_id_3 = r.json()["source_id"]
    wait_for_kb_indexed(kb_id_3, source_id_3)

    r = requests.get(f"{APP}/agents/{agent_a['agent_id']}/sessions", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 403
    print("cross-user session listing blocked ok")

    r = delete_session(token_b, agent_a["agent_id"], session_id_2)
    assert r.status_code == 403
    print("cross-user session delete blocked ok")

    # No legitimate way for an attacker to learn User A's real session_token --
    # confirm a fabricated one gets the same graceful "invalid" response and
    # leaks nothing, hitting the tool endpoint directly (bypassing the LLM
    # entirely -- the strongest form of this test).
    r = requests.post(f"{APP}/tools/session-context", json={"query": "vault combination", "session_token": "guessed-token-does-not-exist"})
    assert r.status_code == 200
    assert "91-42-83" not in r.text
    assert "invalid session token" in r.text.lower()
    print("cross-user tool probe with a fabricated token correctly returned nothing:", r.text)

    print("\nALL LAZY-SESSION-KB SANITY CHECKS PASSED")


if __name__ == "__main__":
    main()
