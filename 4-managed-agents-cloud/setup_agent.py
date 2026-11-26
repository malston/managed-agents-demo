"""One-time setup: create the environment and the agent, then save their IDs.

Run this once. It writes .agent.json. If that file already exists, the script
reuses the saved IDs and creates nothing. Pass --update to push changes to the
system prompt or tools as a new agent version.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic.types.beta import BetaManagedAgentsAgentToolset20260401Params

from common import MODEL_CLAUDE_API as MODEL
from common import REPORT_SPEC
from common.cma import hosted_client

STATE_FILE = Path(__file__).resolve().parent / ".agent.json"

SYSTEM_PROMPT = f"""You are a log triage engineer. The log is at
/mnt/session/uploads/app.log. Read it with the bash and file tools, and count
things with grep, awk, sort and uniq.

{REPORT_SPEC}

Write the report to /mnt/session/outputs/report.md, then reply with a
two-sentence summary and stop."""

TOOLS: list[BetaManagedAgentsAgentToolset20260401Params] = [
    {
        "type": "agent_toolset_20260401",
        # "auto": the server approves low-risk calls and asks you about unclear ones.
        "default_config": {"enabled": True, "permission_policy": {"type": "auto"}},
        # The job only needs the local file, so web tools are off.
        "configs": [
            {"name": "web_fetch", "enabled": False},
            {"name": "web_search", "enabled": False},
        ],
    }
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="push prompt/tool changes as a new agent version")
    args = parser.parse_args()

    client = hosted_client()

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if not args.update:
            print(f"Already set up. Agent {state['agent_id']}, environment {state['environment_id']}.")
            print("Use --update to push prompt or tool changes.")
            return
        agent = client.beta.agents.update(
            state["agent_id"],
            version=state["agent_version"],
            system=SYSTEM_PROMPT,
            tools=TOOLS,
        )
        state["agent_version"] = agent.version
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
        print(f"Agent {agent.id} is now at version {agent.version}.")
        return

    environment = client.beta.environments.create(
        name="log-triage-env",
        config={
            "type": "cloud",
            # Limited egress: no open internet, package managers allowed.
            "networking": {"type": "limited", "allow_package_managers": True},
        },
    )
    print(f"Created environment {environment.id}")

    agent = client.beta.agents.create(
        name="Log Triage Agent",
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
    )
    print(f"Created agent {agent.id} (version {agent.version})")

    STATE_FILE.write_text(
        json.dumps(
            {"environment_id": environment.id, "agent_id": agent.id, "agent_version": agent.version},
            indent=2,
        )
        + "\n"
    )
    print(f"Saved IDs to {STATE_FILE}")


if __name__ == "__main__":
    main()
