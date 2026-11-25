"""Run the log triage agent on one log file and download its report.

Each run starts a new session from the agent saved by setup_agent.py:
upload the log, stream the agent's work, then download report.md.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import anthropic
from anthropic.types.beta.sessions import BetaManagedAgentsAgentToolUseEvent

STATE_FILE = Path(".agent.json")
LOG_MOUNT = "/app.log"  # mounted at /mnt/session/uploads/app.log
BUDGET_CENTS = "200"  # hard cap per session: $2.00 at list price


def approve(event: BetaManagedAgentsAgentToolUseEvent) -> bool:
    """Ask the person at the terminal about a tool call the server could not decide on."""
    print(f"\n[approval needed] {event.name}: {json.dumps(event.input)[:300]}")
    try:
        return input("Allow? [y/N] ").strip().lower() == "y"
    except EOFError:  # no terminal attached: deny
        return False


def stream_session(client: anthropic.Anthropic, session_id: str, task: str) -> str:
    """Send the task, print events until the agent stops, and return the stop reason."""
    # Open the stream first, then send, so no early events are missed.
    with client.beta.sessions.events.stream(session_id) as stream:
        client.beta.sessions.events.send(
            session_id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": task}]}],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)
            elif event.type == "agent.tool_use":
                cmd = event.input.get("command") or event.input.get("path") or ""
                print(f"\n[tool] {event.name} {str(cmd)[:120]}", flush=True)
                if event.evaluated_permission == "ask":
                    client.beta.sessions.events.send(
                        session_id,
                        events=[{
                            "type": "user.tool_confirmation",
                            "tool_use_id": event.id,
                            "result": "allow" if approve(event) else "deny",
                        }],
                    )
            elif event.type == "session.error":
                print(f"\n[error] {event.error}", file=sys.stderr)
            elif event.type == "session.status_idle":
                # requires_action means the agent waits on us (a tool approval): keep going.
                if event.stop_reason.type != "requires_action":
                    return event.stop_reason.type
            elif event.type == "session.status_terminated":
                return "terminated"
    return "stream_closed"


def download_outputs(client: anthropic.Anthropic, session_id: str, out_dir: Path) -> list[Path]:
    """Download every file the agent wrote to /mnt/session/outputs/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for _ in range(5):  # outputs can take a few seconds to show up after idle
        files = client.beta.files.list(scope_id=session_id, betas=["managed-agents-2026-04-01"])
        if files.data:
            for f in files.data:
                dest = out_dir / Path(f.filename).name
                client.files.download(f.id).write_to_file(dest)
                saved.append(dest)
            return saved
        time.sleep(2)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", default="sample/app.log", help="log file to triage")
    parser.add_argument("--out", default="out", help="folder for the downloaded report")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        sys.exit("No .agent.json found. Run `python setup_agent.py` first.")
    state = json.loads(STATE_FILE.read_text())

    client = anthropic.Anthropic()

    log_file = client.files.upload(file=Path(args.log))
    print(f"Uploaded {args.log} as {log_file.id}")

    session = client.beta.sessions.create(
        # Pin the version so a later agent update can't change this run.
        agent={"type": "agent", "id": state["agent_id"], "version": state["agent_version"]},
        environment_id=state["environment_id"],
        title=f"Triage {Path(args.log).name}",
        resources=[{"type": "file", "file_id": log_file.id, "mount_path": LOG_MOUNT}],
        budget={"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
    )
    print(f"Session {session.id}")
    print(f"Watch it live: https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    task = "Triage the log at /mnt/session/uploads/app.log and write the report."
    stop = stream_session(client, session.id, task)
    print(f"\n\nAgent stopped: {stop}")

    for path in download_outputs(client, session.id, Path(args.out)):
        print(f"Saved {path}")

    usage = client.beta.sessions.retrieve(session.id).usage
    if usage and usage.list_cost:
        print(f"Session list cost: ${int(usage.list_cost.amount) / 100:.2f}")


if __name__ == "__main__":
    main()
