"""Option 2: an agent loop on the Messages API, on Amazon Bedrock.

Claude decides which tools to call and in what order. The SDK's tool runner
runs the loop: call the model, run the tools Claude asked for, send the
results back, and repeat until Claude stops. Your process runs every tool,
so the log never leaves your machine except as tool results.

The tools are narrow and read-only on purpose. Claude can't run a shell here.
One tool, lookup_owner, calls the company's service catalog in-process
(common/catalog.py), the way an agent inside your own app reaches your own
APIs. That's the reason to pick this option: a few tools you control.

For a job that needs real file and shell work, see fix.py next to this file.

    python 2-messages-agent-loop/run.py [LOG] [--region us-east-1] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AnthropicBedrockMantle, beta_tool
from anthropic.lib.tools import BetaFunctionTool

from common import DEFAULT_LOG, MODEL_BEDROCK_MANTLE, OUT_DIR, REPORT_SPEC, catalog, logtools
from common.metrics import RunMetrics

OPTION = "2-messages-agent-loop"
MAX_ITERATIONS = 25  # hard stop on model calls, so a confused loop can't run forever

SYSTEM_PROMPT = f"""You are a log triage engineer. You can't see the log directly.
Use the tools to explore it: start with log_overview, then count and search.
For each top issue, call lookup_owner and name the owning team and on-call
channel in Suggested next steps.

{REPORT_SPEC}

When the report is ready, save it with write_report, then reply with a
two-sentence summary and stop."""


# --- tool code: start ---
def make_tools(lines: list[logtools.LogLine], report_path: Path) -> list[BetaFunctionTool[Any]]:
    """Wrap the plain functions in common/logtools.py, and your service catalog, as tools."""

    @beta_tool
    def log_overview() -> str:
        """Line count, time range, and line counts per level and per service."""
        return json.dumps(logtools.overview(lines))

    @beta_tool
    def count_by(field: str, level: str | None = None) -> str:
        """Count log lines grouped by one field.

        Args:
            field: One of level, service, minute, pattern. "pattern" is the message with numbers replaced by N.
            level: Optional. Only count lines at this level, for example ERROR or WARN.
        """
        try:
            return json.dumps(logtools.count_by(lines, field, level))
        except ValueError as err:
            return f"Error: {err}"

    @beta_tool
    def search_log(pattern: str, limit: int = 50) -> str:
        """Return log lines that match a regular expression (case-insensitive), with line numbers.

        Args:
            pattern: Python regular expression, matched against level, service and message.
            limit: Maximum number of lines to return, up to 200.
        """
        return "\n".join(logtools.grep(lines, pattern, min(limit, 200))) or "No matches."

    @beta_tool
    def error_spikes() -> str:
        """Minutes where the ERROR count is more than two standard deviations above the mean."""
        return json.dumps(logtools.spikes(lines))

    @beta_tool
    def lookup_owner(service: str) -> str:
        """Look up the team, on-call channel and runbook for a service in the company service catalog.

        Args:
            service: Service name as it appears in the log, for example payments-svc.
        """
        try:
            return json.dumps(catalog.owner(service))
        except KeyError:
            return f"Error: {service} is not in the service catalog."

    @beta_tool
    def write_report(markdown: str) -> str:
        """Save the finished report.

        Args:
            markdown: The full report in Markdown.
        """
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown + "\n")
        return f"Saved {len(markdown)} characters."

    return [log_overview, count_by, search_log, error_spikes, lookup_owner, write_report]


# --- tool code: end ---


def run(client: AnthropicBedrockMantle, log: Path, model: str, report_path: Path) -> RunMetrics:
    """Run the agent loop to the end and return what it cost."""
    started = time.monotonic()
    lines = logtools.load(log)
    report_path.unlink(missing_ok=True)

    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        tools=make_tools(lines, report_path),
        max_iterations=MAX_ITERATIONS,
        messages=[{"role": "user", "content": f"Triage the log file {log.name} and write the report."}],
    )

    metrics = RunMetrics(option=OPTION, seconds=0.0, model_calls=0, tool_calls=0)
    for message in runner:  # one item per model call
        metrics.model_calls = (metrics.model_calls or 0) + 1
        usage = message.usage
        metrics.input_tokens += usage.input_tokens
        metrics.output_tokens += usage.output_tokens
        metrics.cache_read_tokens += usage.cache_read_input_tokens or 0
        metrics.cache_write_tokens += usage.cache_creation_input_tokens or 0
        for block in message.content:
            if block.type == "tool_use":
                metrics.tool_calls = (metrics.tool_calls or 0) + 1
                print(f"[tool] {block.name} {json.dumps(block.input)[:120]}")
            elif block.type == "text":
                print(block.text)
        if message.stop_reason == "refusal":
            sys.exit("Claude declined this request. See stop_details on the response.")

    metrics.seconds = time.monotonic() - started
    if report_path.exists():
        metrics.report_path = str(report_path)
    else:
        metrics.notes = f"No report saved after {metrics.model_calls} model calls."
        print(metrics.notes, file=sys.stderr)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    client = AnthropicBedrockMantle(aws_region=args.region)
    metrics = run(client, args.log, args.model, OUT_DIR / OPTION / "report.md")
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
