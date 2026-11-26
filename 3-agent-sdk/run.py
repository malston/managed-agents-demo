"""Option 3: the Claude Agent SDK, with model calls on Amazon Bedrock.

The Agent SDK is the Claude Code harness as a library. It brings the agent
loop, context management and built-in tools (Read, Grep, Glob, Bash, Write).
You host it: the tools run on this machine, in a working folder you choose.

This run is set up for unattended use. permission_mode="dontAsk" denies any
tool call not on the allow list, instead of stopping to ask a person.

    python 3-agent-sdk/run.py [LOG] [--region us-east-1] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from common import DEFAULT_LOG, MODEL_BEDROCK_MANTLE, OUT_DIR, REPORT_SPEC
from common.metrics import RunMetrics

OPTION = "3-agent-sdk"
WORKDIR = OUT_DIR / OPTION / "workspace"

SYSTEM_PROMPT = f"""You are a log triage engineer. The log is app.log in your
working directory. Read it with the file tools and count things with grep, awk,
sort, uniq and wc.

{REPORT_SPEC}

Write the report to report.md in your working directory, then reply with a
two-sentence summary and stop."""


def options(region: str, model: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        cwd=str(WORKDIR),
        # Allow list. Read-only shell commands like grep, sort and wc need no rule.
        # Edit(path) rules also cover the Write tool. A leading "/" anchors the
        # path at the working directory, so this allows writing report.md only.
        allowed_tools=["Read", "Grep", "Glob", "Bash(awk *)", "Edit(/report.md)"],
        disallowed_tools=["WebSearch", "WebFetch"],  # WebSearch isn't offered on Bedrock anyway
        permission_mode="dontAsk",  # unattended: deny anything else instead of prompting
        setting_sources=[],  # ignore any CLAUDE.md or settings on this machine, for a repeatable run
        max_turns=30,
        max_budget_usd=2.00,  # hard stop, estimated at list price
        env={
            # Route the harness to Claude in Amazon Bedrock (bedrock-mantle).
            # For the InvokeModel endpoint instead, set CLAUDE_CODE_USE_BEDROCK=1
            # and a model such as us.anthropic.claude-opus-5-5.
            "CLAUDE_CODE_USE_MANTLE": "1",
            "AWS_REGION": region,
        },
    )


async def run(log: Path, region: str, model: str) -> RunMetrics:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)
    shutil.copy(log, WORKDIR / "app.log")

    started = time.monotonic()
    metrics = RunMetrics(option=OPTION, seconds=0.0, tool_calls=0)
    prompt = "Triage app.log and write report.md."
    async for message in query(prompt=prompt, options=options(region, model)):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    metrics.tool_calls = (metrics.tool_calls or 0) + 1
                    print(f"[tool] {block.name} {str(block.input)[:120]}")
        elif isinstance(message, ResultMessage):
            usage = message.usage or {}
            metrics.input_tokens = int(usage.get("input_tokens", 0))
            metrics.output_tokens = int(usage.get("output_tokens", 0))
            metrics.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
            metrics.cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0))
            metrics.model_calls = message.num_turns
            metrics.reported_cost_usd = message.total_cost_usd  # the harness's own list-price estimate
            if message.is_error:
                metrics.notes = f"Run ended with {message.subtype}: {message.errors}"

    metrics.seconds = time.monotonic() - started
    report = WORKDIR / "report.md"
    if report.exists():
        metrics.report_path = str(report)
    elif not metrics.notes:
        metrics.notes = "No report.md written."
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    metrics = asyncio.run(run(args.log.resolve(), args.region, args.model))
    if metrics.notes:
        print(metrics.notes, file=sys.stderr)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
