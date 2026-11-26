"""One-time setup for option 5: a self-hosted environment and its agent.

Creates an environment of type self_hosted and the same log triage agent as
option 4, with a prompt that points at the worker's working folder. Saves the
IDs to .agent.json. Run it again with --update to push prompt changes.

After this, generate an environment key for the new environment in the
Console (environment page, "Generate environment key") and start a worker.
See README.md.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic.types.beta import BetaManagedAgentsAgentToolset20260401Params

from common import MODEL_CLAUDE_API, REPORT_SPEC
from common.cma import hosted_client

STATE_FILE = Path(__file__).resolve().parent / ".agent.json"

SYSTEM_PROMPT = f"""You are a log triage engineer. The log is app.log in your
current working directory. Read it with the bash and file tools, and count
things with grep, awk, sort and uniq.

{REPORT_SPEC}

Write the report to report.md in your current working directory, then reply
with a two-sentence summary and stop."""

# The agent declares the toolset. With a self-hosted environment, your worker
# runs these tools on your machine instead of Anthropic's container.
TOOLS: list[BetaManagedAgentsAgentToolset20260401Params] = [
    {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": True, "permission_policy": {"type": "auto"}},
        # Web tools run on Anthropic's servers even with a self-hosted sandbox. Off.
        "configs": [
            {"name": "web_fetch", "enabled": False},
            {"name": "web_search", "enabled": False},
        ],
    }
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update", action="store_true", help="push prompt/tool changes as a new agent version")
    args = parser.parse_args()

    client = hosted_client()

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        if not args.update:
            print(f"Already set up. Agent {state['agent_id']}, environment {state['environment_id']}.")
            return
        agent = client.beta.agents.update(
            state["agent_id"], version=state["agent_version"], system=SYSTEM_PROMPT, tools=TOOLS
        )
        state["agent_version"] = agent.version
        STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
        print(f"Agent {agent.id} is now at version {agent.version}.")
        return

    # The whole config. No networking or packages here: your worker host decides those.
    environment = client.beta.environments.create(name="log-triage-self-hosted", config={"type": "self_hosted"})
    print(f"Created environment {environment.id}")

    agent = client.beta.agents.create(
        name="Log Triage Agent (self-hosted sandbox)",
        model=MODEL_CLAUDE_API,
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
    print(f"Saved IDs to {STATE_FILE.name}")
    print("Next: generate an environment key in the Console, then start a worker (see README.md).")


if __name__ == "__main__":
    main()
