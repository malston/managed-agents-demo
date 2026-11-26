"""Option 1: a Messages API workflow on Amazon Bedrock.

Your code does every step in a fixed order. Python parses the log and computes
the numbers. Claude gets those facts in one request and writes the report.
Claude never decides what to do next, and it has no tools.

That makes the cost of a run easy to predict. The script prints what 1,000 logs
like this one would cost and take, and a fingerprint of the facts Claude got.
Run it with --repeat 3 to see the facts come out the same every time. Only the
wording of the report changes between runs.

    python 1-messages-workflow/run.py [LOG] [--repeat 3] [--region us-east-1] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import hashlib
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


def write_report(client: AnthropicBedrockMantle, model: str, facts: str) -> tuple[str, RunMetrics]:
    """Step 2: one model call writes the report from the facts."""
    started = time.monotonic()
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},  # a writing task over given facts needs little thinking
        messages=[{"role": "user", "content": f"Facts from the log:\n\n{facts}"}],
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason == "refusal":
        sys.exit("Claude declined this request. See stop_details on the response.")
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
    )
    return "".join(block.text for block in message.content if block.type == "text"), metrics


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--repeat", type=int, default=1, help="run the same log this many times")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    # Credentials come from the AWS default chain (profile, SSO, role) or AWS_BEARER_TOKEN_BEDROCK.
    client = AnthropicBedrockMantle(aws_region=args.region)
    runs: list[RunMetrics] = []
    report = ""
    for number in range(1, args.repeat + 1):
        # Step 1: code computes the facts. Same answer every time, no tokens spent.
        lines = logtools.load(args.log)
        facts = build_facts(lines)
        report, metrics = write_report(client, args.model, facts)
        runs.append(metrics)
        print(
            f"Run {number}: {len(lines)} lines, facts {fingerprint(facts)} ({len(facts):,} chars), "
            f"report {fingerprint(report)}, {metrics.input_tokens:,} in / {metrics.output_tokens:,} out, "
            f"{metrics.seconds:.1f}s, ${metrics.estimated_cost_usd():.4f}"
        )

    # Step 3: code saves the result.
    out = OUT_DIR / OPTION / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n")
    print(report)

    # One call per log, no loop: the cost of N logs is N times the cost of one.
    per_run_cost = sum(m.estimated_cost_usd() for m in runs) / len(runs)
    per_run_secs = sum(m.seconds for m in runs) / len(runs)
    projection = (
        f"1,000 logs like this: about ${per_run_cost * 1000:,.2f} and "
        f"{per_run_secs * 1000 / 60:,.0f} minutes one at a time (1 model call each, no tools)"
    )
    print(f"\n{projection}")

    total = runs[-1]
    total.report_path = str(out)
    total.notes = projection
    total.print_summary()
    if args.metrics:
        total.save(args.metrics)


if __name__ == "__main__":
    main()
