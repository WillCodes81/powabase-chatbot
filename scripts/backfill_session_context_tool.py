import requests

from app.config import settings
from app.powabase_client import SESSION_CONTEXT_TOOL_NAME, assign_tool_to_agent, ensure_session_context_tool

BASE = settings.powabase_url
SVC = settings.powabase_service_key


def main():
    tool_id = ensure_session_context_tool()
    print("session-context tool id:", tool_id)

    r = requests.get(
        f"{BASE}/rest/v1/agents_registry",
        headers={"apikey": SVC, "Authorization": f"Bearer {SVC}"},
        params={"select": "agent_id,name"},
    )
    r.raise_for_status()
    rows = r.json()
    print(f"found {len(rows)} existing agents")

    for row in rows:
        _, status_code = assign_tool_to_agent(row["agent_id"], tool_id, SESSION_CONTEXT_TOOL_NAME)
        if status_code >= 400:
            print(f"  agent {row['agent_id']} ({row['name']}): skipped (status {status_code} — likely already assigned)")
        else:
            print(f"  agent {row['agent_id']} ({row['name']}): tool attached")


if __name__ == "__main__":
    main()
