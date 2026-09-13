import requests

from app.config import settings
from app.powabase_client import get_agent_registry_entry, get_public_share_by_source_agent_id

BASE = settings.powabase_url
ANON = settings.powabase_anon_key
SVC = settings.powabase_service_key
APP = "http://127.0.0.1:8000"

USER = {"email": "verify-mirror-cascade-user@example.com", "password": "SanityTest123!"}


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


def get_kb(kb_id):
    r = requests.get(
        f"{settings.powabase_url}/api/knowledge-bases/{kb_id}",
        headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"},
    )
    return r.status_code


def main():
    print("--- Setup: one owner, one source agent, one public share (mirror) ---")
    token = signup_or_signin(USER)

    source_agent = create_agent(token, "Verify Mirror Cascade Source")
    source_agent_id = source_agent["agent_id"]
    print(f"source agent: {source_agent_id}")

    share = create_public_share(token, "Verify Mirror Cascade Share", source_agent_id)
    share_id = share["share_id"]
    mirror_agent_id = share["agent_id"]
    print(f"share: {share_id}  mirror agent: {mirror_agent_id}")

    rows, sc = get_public_share_by_source_agent_id(token, source_agent_id)
    assert sc < 400 and rows, f"expected share row to exist before deletion, got {sc}: {rows}"
    mirror_kb_id = rows[0]["kb_id"]
    print(f"mirror kb_id: {mirror_kb_id}")
    assert get_kb(mirror_kb_id) == 200, "mirror KB should exist before deletion"

    mirror_registry, sc = get_agent_registry_entry(token, mirror_agent_id)
    assert sc < 400 and mirror_registry, f"expected mirror registry row to exist before deletion, got {sc}: {mirror_registry}"
    print("PASS: mirror agent, its registry row, its KB, and the public_shares row all exist before deletion")

    print("\n--- Delete the SOURCE agent (not the mirror) ---")
    r = requests.delete(f"{APP}/agents/{source_agent_id}", headers={"Authorization": f"Bearer {token}"})
    print(f"delete source status: {r.status_code} body: {r.text}")
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"

    print("\n--- Verify the mirror was fully cascaded away ---")
    rows, sc = get_public_share_by_source_agent_id(token, source_agent_id)
    print(f"public_shares row lookup after delete: status={sc} rows={rows}")
    assert sc < 400 and not rows, f"expected public_shares row to be gone, got {sc}: {rows}"
    print("PASS: public_shares row deleted")

    mirror_registry_after, sc = get_agent_registry_entry(token, mirror_agent_id)
    print(f"mirror registry lookup after delete: status={sc} rows={mirror_registry_after}")
    assert sc < 400 and not mirror_registry_after, f"expected mirror registry row to be gone, got {sc}: {mirror_registry_after}"
    print("PASS: mirror agents_registry row deleted")

    kb_status = get_kb(mirror_kb_id)
    print(f"mirror KB lookup after delete: status={kb_status}")
    assert kb_status >= 400, f"expected mirror KB to be gone, got status {kb_status}"
    print("PASS: mirror's own KB deleted")

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
