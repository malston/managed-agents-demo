"""Option 1: a Messages API workflow on Amazon Bedrock.

Your code does every step in a fixed order. Python parses the log and computes
the numbers. Claude gets those facts in one request and writes the report.
Claude never decides what to do next, and it has no tools.

    python 1-messages-workflow/run.py [LOG] [--region us-east-1] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AnthropicBedrockMantle

from common import DEFAULT_LOG, MODEL_BEDROCK_MANTLE, OUT_DIR, REPORT_SPEC, logtools
from common.metrics import RunMetrics

OPTION = "1-messages-workflow"
SYSTEM_PROMPT = f"""You are a log triage engineer. You get facts that code already
computed from an application log. Use only those numbers.

{REPORT_SPEC}

Reply with the report only."""


def build_facts(lines: list[logtools.LogLine]) -> str:
    """Step 1, plain code: turn the raw log into a small JSON summary."""
    facts = {
        "overview": logtools.overview(lines),
        "issues": logtools.issues(lines),
        "error_spikes": logtools.spikes(lines),
        "errors_per_minute": logtools.count_by(lines, "minute", level="ERROR"),
    }
    return json.dumps(facts, indent=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    started = time.monotonic()

    # Step 1: code computes the facts. Same answer every time, no tokens spent.
    lines = logtools.load(args.log)
    facts = build_facts(lines)
    print(f"Parsed {len(lines)} lines. Sending {len(facts):,} characters of facts to Claude.")

    # Step 2: one model call writes the report. Credentials come from the AWS
    # default chain (profile, SSO, role) or AWS_BEARER_TOKEN_BEDROCK.
    client = AnthropicBedrockMantle(aws_region=args.region)
    with client.messages.stream(
        model=args.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},  # a writing task over given facts needs little thinking
        messages=[{"role": "user", "content": f"Facts from the log:\n\n{facts}"}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        sys.exit("Claude declined this request. See stop_details on the response.")
    report = "".join(block.text for block in message.content if block.type == "text")

    # Step 3: code saves the result.
    out = OUT_DIR / OPTION / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n")

    usage = message.usage
    metrics = RunMetrics(
        option=OPTION,
        seconds=time.monotonic() - started,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        model_calls=1,
        tool_calls=0,
        report_path=str(out),
    )
    print(report)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
