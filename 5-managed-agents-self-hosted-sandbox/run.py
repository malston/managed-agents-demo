"""Option 5: Managed Agents with a self-hosted sandbox.

Anthropic still runs the agent loop and keeps the session history. Your worker
(worker.py or `ant beta:worker poll`) runs the tools on your machine, in
./workspace. The log stays in that folder. Only what a tool returns, such as
grep output, goes to Anthropic so the model can read it.

Self-hosted environments don't accept file mounts, so this script copies the
log into the worker's folder, the way real data would already live next to
the worker.

It also starts private_api.py, a deploy history service that listens on
127.0.0.1 only. The task asks the agent to curl it, to match the error spike to
a deploy. That call works because the tools run on your side. It's the reason to
pick this option: tools that need your private network. (The script assumes the
worker runs on this machine. In real use, the API is an internal service the
worker's network can reach.)

    python 5-managed-agents-self-hosted-sandbox/run.py [LOG] [--metrics out.json]
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEFAULT_LOG
from common.cma import hosted_client, session_metrics, stream_session

sys.path.insert(0, str(Path(__file__).resolve().parent))
import private_api  # noqa: E402

OPTION = "5-managed-agents-self-hosted-sandbox"
HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / ".agent.json"
WORKDIR = HERE / "workspace"  # must match the worker's --workdir
BUDGET_CENTS = "200"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    if not STATE_FILE.exists():
        sys.exit(f"No {STATE_FILE.name} found. Run `python {OPTION}/setup.py` first.")
    state = json.loads(STATE_FILE.read_text())
    client = hosted_client()

    # A session waits silently at its first tool call if no worker is polling.
    stats = client.beta.environments.work.stats(state["environment_id"])
    if not stats.workers_polling:
        sys.exit("No worker is polling this environment. Start worker.py first (see README.md).")

    WORKDIR.mkdir(exist_ok=True)
    (WORKDIR / "report.md").unlink(missing_ok=True)
    shutil.copy(args.log, WORKDIR / "app.log")

    started = time.monotonic()
    session = client.beta.sessions.create(
        agent={"type": "agent", "id": state["agent_id"], "version": state["agent_version"]},
        environment_id=state["environment_id"],
        title=f"Triage {args.log.name} (self-hosted sandbox)",
        budget={"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
    )
    print(f"Session {session.id}\n")

    api = private_api.start_in_background()
    print(f"Private deploy API listening on {private_api.URL} (this machine only)\n")
    task = (
        "Triage app.log in your working directory and write report.md. Deploy history is at "
        f"{private_api.URL}/deploys?service=NAME on the private network. curl it for the top issue's "
        "service and say in the report whether a deploy lines up with the start of its errors."
    )
    try:
        result = stream_session(client, session.id, [{"type": "text", "text": task}])
    finally:
        api.shutdown()
    print(f"\n\nAgent stopped: {result.stop_reason}")

    metrics = session_metrics(client, OPTION, session.id, started, result)
    report = WORKDIR / "report.md"
    if report.exists():  # written by the worker on this machine; nothing to download
        metrics.report_path = str(report)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
