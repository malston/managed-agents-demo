"""Run the same log through each option and compare time, tokens and cost.

Each demo runs in its own process, exactly as you would run it by hand, and
writes a metrics file to out/<option>/metrics.json. Options whose credentials
or setup are missing are skipped with the reason.

    python compare.py                 # every option that is ready
    python compare.py --only 1,2,3    # just these
    python compare.py --check         # show what would run, run nothing
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common import DEFAULT_LOG, OUT_DIR, REPO_ROOT
from common.metrics import RunMetrics


def aws_ready() -> str | None:
    """None when AWS credentials for Bedrock are findable, else the reason they aren't."""
    if os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        return None
    try:
        import boto3  # installed with anthropic[bedrock]
    except ImportError:
        return 'boto3 missing: pip install "anthropic[bedrock]"'
    if boto3.Session().get_credentials() is None:
        return "no AWS credentials (set AWS_PROFILE, run aws sso login, or set AWS_BEARER_TOKEN_BEDROCK)"
    return None


def anthropic_ready() -> str | None:
    if os.environ.get("CMA_PLATFORM") == "aws":
        return aws_ready()
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return None
    if (Path.home() / ".config" / "anthropic").exists():  # `ant auth login` profile
        return None
    return "no Claude API credentials (set ANTHROPIC_API_KEY or run ant auth login)"


def state_ready(folder: str, setup: str) -> Callable[[], str | None]:
    def check() -> str | None:
        reason = anthropic_ready()
        if reason:
            return reason
        if not (REPO_ROOT / folder / ".agent.json").exists():
            return f"not set up yet: run python {folder}/{setup}"
        return None

    return check


def self_hosted_ready() -> str | None:
    if os.environ.get("CMA_SELF_HOSTED_URL") and os.environ.get("CMA_SELF_HOSTED_API_KEY"):
        return None
    return "no self-hosted server (set CMA_SELF_HOSTED_URL and CMA_SELF_HOSTED_API_KEY)"


@dataclass
class Option:
    number: str
    folder: str
    ready: Callable[[], str | None]


OPTIONS = [
    Option("1", "1-messages-workflow", aws_ready),
    Option("2", "2-messages-agent-loop", aws_ready),
    Option("3", "3-agent-sdk", aws_ready),
    Option("4", "4-managed-agents-cloud", state_ready("4-managed-agents-cloud", "setup_agent.py")),
    Option("5", "5-managed-agents-self-hosted-sandbox", state_ready("5-managed-agents-self-hosted-sandbox", "setup.py")),
    Option("6", "6-self-hosted-cma-bedrock", self_hosted_ready),
]


def money(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def print_table(rows: list[tuple[Option, RunMetrics | None, str]]) -> None:
    header = f"{'option':<38} {'status':<8} {'secs':>6} {'in':>8} {'out':>7} {'cache rd':>9} {'calls':>5} {'tools':>5} {'est. cost':>10} {'reported':>10}"
    print("\n" + header)
    print("-" * len(header))
    for option, metrics, status in rows:
        if metrics is None:
            print(f"{option.folder:<38} {status}")
            continue
        print(
            f"{option.folder:<38} {status:<8} {metrics.seconds:>6.1f} {metrics.input_tokens:>8,} "
            f"{metrics.output_tokens:>7,} {metrics.cache_read_tokens:>9,} "
            f"{metrics.model_calls if metrics.model_calls is not None else '-':>5} "
            f"{metrics.tool_calls if metrics.tool_calls is not None else '-':>5} "
            f"{money(metrics.estimated_cost_usd()):>10} {money(metrics.reported_cost_usd):>10}"
        )
    print(
        "\nest. cost: tokens at Claude API list price for Claude Opus 5.5, plus $0.08 per session-hour"
        "\nfor options 4 and 5. Bedrock bills at AWS prices. reported: the platform's own number, if any."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--only", help="comma-separated option numbers, for example 1,2,4")
    parser.add_argument("--check", action="store_true", help="report which options are ready, run nothing")
    args = parser.parse_args()

    wanted = set(args.only.split(",")) if args.only else {o.number for o in OPTIONS}
    rows: list[tuple[Option, RunMetrics | None, str]] = []
    for option in OPTIONS:
        if option.number not in wanted:
            continue
        reason = option.ready()
        if reason:
            rows.append((option, None, f"skipped: {reason}"))
            continue
        if args.check:
            rows.append((option, None, "ready"))
            continue

        metrics_path = OUT_DIR / option.folder / "metrics.json"
        metrics_path.unlink(missing_ok=True)
        print(f"\n===== {option.folder} =====", flush=True)
        script = REPO_ROOT / option.folder / "run.py"
        proc = subprocess.run(
            [sys.executable, str(script), str(args.log), "--metrics", str(metrics_path)],
            stdin=subprocess.DEVNULL,  # unattended: any tool approval prompt is denied
        )
        if proc.returncode != 0 or not metrics_path.exists():
            rows.append((option, None, f"failed (exit code {proc.returncode}), see output above"))
            continue
        rows.append((option, RunMetrics.load(metrics_path), "ok"))

    print_table(rows)
    results = {o.folder: json.loads((OUT_DIR / o.folder / "metrics.json").read_text()) for o, m, _ in rows if m}
    if results:
        summary = OUT_DIR / "comparison.json"
        summary.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nSaved {summary.relative_to(REPO_ROOT)}. Reports are in out/<option>/.")


if __name__ == "__main__":
    main()
