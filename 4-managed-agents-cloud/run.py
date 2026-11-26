"""Option 4: Managed Agents with an Anthropic-hosted cloud sandbox.

Each run starts a new session from the agent saved by setup_agent.py:
upload the log, stream the agent's work, then download report.md.
Anthropic runs the agent loop and the container the tools run in.

By default the run defines an outcome: the task plus rubric.md. A separate
grader scores each draft of the report against the rubric, and the agent
revises until it passes or runs out of tries. Pass --no-outcome to send a
plain message instead and compare the two.

    python 4-managed-agents-cloud/run.py [LOG] [--max-iterations 3] [--no-outcome] [--metrics out.json]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic
from anthropic.types.beta.sessions import BetaManagedAgentsUserDefineOutcomeEventParams

from common import DEFAULT_LOG, OUT_DIR
from common.cma import hosted_client, session_metrics, stream_session

OPTION = "4-managed-agents-cloud"
STATE_FILE = Path(__file__).resolve().parent / ".agent.json"
LOG_MOUNT = "/app.log"  # mounted at /mnt/session/uploads/app.log
BUDGET_CENTS = "200"  # hard cap per session: $2.00 at list price
OUTCOME_BUDGET_CENTS = "500"  # grader passes and revisions cost more: $5.00
RUBRIC = Path(__file__).resolve().parent / "rubric.md"
TASK = "Triage the log at /mnt/session/uploads/app.log and write the report to /mnt/session/outputs/report.md."
# With an outcome, say up front what the grader will check, so the first draft can pass.
OUTCOME_TASK = (
    TASK + " For each issue, give a severity (high, medium or low) and cite at least one log line "
    "by timestamp or req_id. Name a likely root cause for the top issue, and give a concrete "
    "next action for each high-severity issue."
)


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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG, help="log file to triage")
    parser.add_argument("--out", type=Path, default=OUT_DIR / OPTION, help="folder for the downloaded report")
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    parser.add_argument("--no-outcome", action="store_true", help="send a plain message, with no grader")
    parser.add_argument(
        "--max-iterations", type=int, default=3, help="grader passes before it stops (default 3, max 20)"
    )
    args = parser.parse_args()
    if not 1 <= args.max_iterations <= 20:
        parser.error("--max-iterations must be between 1 and 20")

    if not STATE_FILE.exists():
        sys.exit(f"No {STATE_FILE.name} found. Run `python {OPTION}/setup_agent.py` first.")
    state = json.loads(STATE_FILE.read_text())

    client = hosted_client()
    started = time.monotonic()

    log_file = client.files.upload(file=args.log)
    print(f"Uploaded {args.log} as {log_file.id}")

    session = client.beta.sessions.create(
        # Pin the version so a later agent update can't change this run.
        agent={"type": "agent", "id": state["agent_id"], "version": state["agent_version"]},
        environment_id=state["environment_id"],
        title=f"Triage {args.log.name}",
        resources=[{"type": "file", "file_id": log_file.id, "mount_path": LOG_MOUNT}],
        budget={
            "type": "limit",
            "max_list_cost": {"amount": BUDGET_CENTS if args.no_outcome else OUTCOME_BUDGET_CENTS, "currency": "USD"},
        },
    )
    print(f"Session {session.id}")
    print(f"Watch it live: https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    if args.no_outcome:
        result = stream_session(client, session.id, [{"type": "text", "text": TASK}])
    else:
        # The outcome replaces the first user message: the agent starts on receipt.
        outcome: BetaManagedAgentsUserDefineOutcomeEventParams = {
            "type": "user.define_outcome",
            "description": OUTCOME_TASK,
            "rubric": {"type": "text", "content": RUBRIC.read_text()},
            "max_iterations": args.max_iterations,
        }
        result = stream_session(client, session.id, outcome=outcome)
    print(f"\n\nAgent stopped: {result.stop_reason}")
    if result.outcome_results:
        print(f"Grader results, in order: {', '.join(result.outcome_results)}")

    saved = download_outputs(client, session.id, args.out)
    for path in saved:
        print(f"Saved {path}")

    metrics = session_metrics(client, OPTION, session.id, started, result)
    metrics.report_path = next((str(p) for p in saved if p.name == "report.md"), None)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
