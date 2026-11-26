"""Option 6: self-hosted Claude Managed Agents, with model calls on Amazon Bedrock.

You run the whole service (cma-server, PostgreSQL, sandbox workers). The client
code is the same sessions API as options 4 and 5. Only the base URL and the key
change. With inference.provider: bedrock, the server calls Bedrock with your AWS
credentials, so nothing in the run reaches Anthropic.

Your server has no Files API and no file mounts. This script sends the log in
the message as a text document, and the agent replies with the report.

    export CMA_SELF_HOSTED_URL=http://127.0.0.1:8400
    export CMA_SELF_HOSTED_API_KEY=...        # CMA_SERVER__API_KEY from the server's .env
    ant apply --yes 6-self-hosted-cma-bedrock/log-triage-agent.md   # once, with ANTHROPIC_BASE_URL set
    python 6-self-hosted-cma-bedrock/run.py [LOG] [--environment compose-sandbox] [--metrics out.json]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import DEFAULT_LOG, OUT_DIR
from common.cma import MessageContent, self_hosted_client, session_metrics, stream_session

OPTION = "6-self-hosted-cma-bedrock"
AGENT_NAME = "Log Triage Agent"  # the name in log-triage-agent.md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--environment", default="compose-sandbox", help="environment name on your server")
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    client = self_hosted_client()
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
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
