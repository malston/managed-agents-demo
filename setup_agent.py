"""One-time setup: create the environment and the agent, then save their IDs.

Run this once. It writes .agent.json. If that file already exists, the script
reuses the saved IDs and creates nothing. Pass --update to push changes to the
system prompt or tools as a new agent version.
"""

import argparse
import json
from pathlib import Path

import anthropic
from anthropic.types.beta import BetaManagedAgentsAgentToolset20260401Params

STATE_FILE = Path(".agent.json")
MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a log triage engineer.

You get one application log file. Your job:
1. Read the log with the bash and file tools. Use grep, awk, sort and uniq to count things.
   Do not guess numbers; compute them.
2. Group errors and warnings by service and by message pattern.
3. Find the time windows where errors spike.
4. Write a short Markdown report to /mnt/session/outputs/report.md with these sections:
   Summary, Top issues (a table with service, pattern, count, first seen, last seen),
   Error spikes, Suggested next steps.
Keep the report under one page. Use plain, simple language.
When the report is written, reply with a two-sentence summary and stop."""

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

    client = anthropic.Anthropic()

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
