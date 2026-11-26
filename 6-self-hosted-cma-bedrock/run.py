"""Option 6: self-hosted Claude Managed Agents, with model calls on Amazon Bedrock.

You run the whole service (cma-server, PostgreSQL, sandbox workers). The client
code is the same sessions API as options 4 and 5. Only the base URL and the key
change. With inference.provider: bedrock, the server calls Bedrock with your AWS
credentials, so nothing in the run reaches Anthropic.

After the run, the script reads the session's history back from your server.
It lives in your PostgreSQL database, and tokens were billed by AWS through
Bedrock. Those two facts are the reason to pick this option. --history
SESSION_ID prints a stored session again, any time later.

Your server has no Files API and no file mounts. This script sends the log in
the message as a text document, and the agent replies with the report.

    export CMA_SELF_HOSTED_URL=http://127.0.0.1:8400
    export CMA_SELF_HOSTED_API_KEY=...        # CMA_SERVER__API_KEY from the server's .env
    ant apply --yes 6-self-hosted-cma-bedrock/log-triage-agent.md   # once, with ANTHROPIC_BASE_URL set
    python 6-self-hosted-cma-bedrock/run.py [LOG] [--environment compose-sandbox] [--metrics out.json]
    python 6-self-hosted-cma-bedrock/run.py --history sesn_...
"""

import argparse
import os
import sys
import time
from collections import Counter
from pathlib import Path

import anthropic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEFAULT_LOG, OUT_DIR
from common.cma import MessageContent, self_hosted_client, session_metrics, stream_session

OPTION = "6-self-hosted-cma-bedrock"
AGENT_NAME = "Log Triage Agent"  # the name in log-triage-agent.md


def show_history(client: anthropic.Anthropic, session_id: str) -> None:
    """Read a session's stored events back from your own server."""
    events = list(client.beta.sessions.events.list(session_id, order="asc"))
    kinds = Counter(event.type for event in events)
    base_url = os.environ.get("CMA_SELF_HOSTED_URL", "")
    print(f"\nHistory for {session_id}, read from {base_url} (stored in your server's PostgreSQL):")
    print(f"  {len(events)} events: " + ", ".join(f"{n} {kind}" for kind, n in kinds.most_common()))
    print("  With inference.provider: bedrock (config/inference-bedrock.yaml), model calls went to Amazon")
    print("  Bedrock with your AWS credentials and are billed on your AWS invoice. Per the docs, the server")
    print("  connects to Anthropic only when the provider is the Claude API.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--environment", default="compose-sandbox", help="environment name on your server")
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    parser.add_argument("--history", metavar="SESSION_ID", help="print a stored session's history and exit")
    args = parser.parse_args()

    client = self_hosted_client()
    if args.history:
        show_history(client, args.history)
        return
    agent = next((a for a in client.beta.agents.list() if a.name == AGENT_NAME), None)
    environment = next((e for e in client.beta.environments.list() if e.name == args.environment), None)
    if agent is None:
        sys.exit(f"No agent named {AGENT_NAME!r}. Run `ant apply` on log-triage-agent.md first (see README.md).")
    if environment is None:
        sys.exit(f"No environment named {args.environment!r} on this server.")

    started = time.monotonic()
    session = client.beta.sessions.create(
        agent={"type": "agent", "id": agent.id, "version": agent.version},
        environment_id=environment.id,
        title=f"Triage {args.log.name} (self-hosted, Bedrock)",
    )
    print(f"Session {session.id}\n")

    content: list[MessageContent] = [
        {"type": "text", "text": "Triage this log and reply with the report."},
        {
            "type": "document",
            "title": args.log.name,
            # URL sources are silently ignored on a self-hosted server. Send text.
            "source": {"type": "text", "media_type": "text/plain", "data": args.log.read_text()},
        },
    ]
    result = stream_session(client, session.id, content)
    print(f"\n\nAgent stopped: {result.stop_reason}")

    metrics = session_metrics(client, OPTION, session.id, started, result, bill_runtime=False)
    if result.agent_text:
        out = OUT_DIR / OPTION / "report.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.agent_text[-1] + "\n")  # the final reply is the report
        metrics.report_path = str(out)
    show_history(client, session.id)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
