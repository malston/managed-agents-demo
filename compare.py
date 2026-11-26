"""Run the same log through each option and compare time, tokens and cost.

Each demo runs in its own process, exactly as you would run it by hand, and
writes a metrics file to out/<option>/metrics.json. Options whose credentials
or setup are missing are skipped with the reason.

It also prints how each option is built: what you host, where the data and
session history live, who bills you, and how many lines of tool code you wrote.

    python compare.py                 # every option that is ready, log triage
    python compare.py --scenario fix  # the code-fix scenario (options 2 and 3)
    python compare.py --only 1,2,3    # just these
    python compare.py --check         # show what would run, run nothing
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
        import boto3  # type: ignore[import-untyped, import-not-found, unused-ignore]  # installed with anthropic[bedrock]
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
    you_host: str
    data_and_history: str
    billing: str


OPTIONS = [
    Option(
        "1",
        "1-messages-workflow",
        aws_ready,
        you_host="your script",
        data_and_history="your machine; facts sent to Bedrock",
        billing="AWS (Bedrock)",
    ),
    Option(
        "2",
        "2-messages-agent-loop",
        aws_ready,
        you_host="your app, loop and tools",
        data_and_history="your app; tool results sent to Bedrock",
        billing="AWS (Bedrock)",
    ),
    Option(
        "3",
        "3-agent-sdk",
        aws_ready,
        you_host="SDK process and its workspace",
        data_and_history="your machine; tool results sent to Bedrock",
        billing="AWS (Bedrock)",
    ),
    Option(
        "4",
        "4-managed-agents-cloud",
        state_ready("4-managed-agents-cloud", "setup_agent.py"),
        you_host="nothing",
        data_and_history="Anthropic: files, sandbox, history",
        billing="Anthropic, or AWS Marketplace (Claude Platform on AWS)",
    ),
    Option(
        "5",
        "5-managed-agents-self-hosted-sandbox",
        state_ready("5-managed-agents-self-hosted-sandbox", "setup.py"),
        you_host="sandbox worker",
        data_and_history="files on your worker; history at Anthropic",
        billing="Anthropic, or AWS Marketplace (Claude Platform on AWS)",
    ),
    Option(
        "6",
        "6-self-hosted-cma-bedrock",
        self_hosted_ready,
        you_host="cma-server, PostgreSQL, workers",
        data_and_history="all yours: your Postgres, your workers",
        billing="AWS (Bedrock) plus the cma-server license",
    ),
]

SCENARIO_SCRIPTS = {"triage": "run.py", "fix": "fix.py"}


def marked_lines(folder: str, script_name: str, kind: str) -> int | None:
    """Lines of code between "# --- <kind> code: start/end ---" markers in one script.

    Blank lines, comments and docstring-only lines are left out, so the number is
    the code you'd write, review and maintain.
    """
    script = REPO_ROOT / folder / script_name
    if not script.exists():
        return None
    total = 0
    for text in [script.read_text()]:
        for block in re.findall(rf"# --- {kind} code: start ---\n(.*?)# --- {kind} code: end ---", text, re.S):
            body = re.sub(r'"""(?:.|\n)*?"""', "", block)  # drop docstrings
            total += sum(1 for line in body.splitlines() if line.strip() and not line.strip().startswith("#"))
    return total


def print_build_table(script_name: str) -> None:
    header = f"{'option':<38} {'tools you wrote':>15} {'hooks':>6}  {'you host':<32} {'data and history':<44} billing"
    print("\n" + header)
    print("-" * len(header))
    for option in OPTIONS:
        tools = marked_lines(option.folder, script_name, "tool")
        hooks = marked_lines(option.folder, script_name, "hook")
        print(
            f"{option.folder:<38} {'-' if tools is None else tools:>15} {'-' if hooks is None else hooks:>6}  "
            f"{option.you_host:<32} {option.data_and_history:<44} {option.billing}"
        )
    print(
        f"\ntools you wrote: lines of tool code in each option's {script_name}, without blanks, comments"
        "\nand docstrings. Options 3 to 6 use built-in tools."
        "\nhooks: lines of hook code, the guard rails you add on top of built-in tools."
    )


def money(value: float | None) -> str:
    return "-" if value is None else f"${value:.4f}"


def outcome_cell(metrics: RunMetrics) -> str:
    """Grader result, revisions and grader tokens, for runs that defined an outcome."""
    if not metrics.grader_passes:
        return "-"
    return (
        f"{metrics.outcome_result}, {metrics.grader_passes - 1} revision(s), grader "
        f"{metrics.grader_input_tokens:,} in / {metrics.grader_output_tokens:,} out"
    )


def print_table(rows: list[tuple[Option, RunMetrics | None, str]]) -> None:
    header = f"{'option':<38} {'status':<8} {'secs':>6} {'in':>8} {'out':>7} {'cache rd':>9} {'calls':>5} {'tools':>5} {'est. cost':>10} {'reported':>10}  outcome"
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
            f"{money(metrics.estimated_cost_usd()):>10} {money(metrics.reported_cost_usd):>10}  "
            f"{outcome_cell(metrics)}"
        )
    noted = [(option, metrics) for option, metrics, _ in rows if metrics and metrics.notes]
    if noted:
        print("\nnotes:")
        for option, metrics in noted:
            print(f"  {option.folder}: {metrics.notes}")
    print(
        "\nest. cost: tokens at Claude API list price for Claude Opus 5.5, plus $0.08 per session-hour"
        "\nfor options 4 and 5. Bedrock bills at AWS prices. reported: the platform's own number, if any."
        "\noutcome: option 4's grader. Its tokens are shown apart and left out of est. cost, because the"
        "\ndocs don't say whether session usage already counts them."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--only", help="comma-separated option numbers, for example 1,2,4")
    parser.add_argument("--check", action="store_true", help="report which options are ready, run nothing")
    parser.add_argument("--scenario", choices=sorted(SCENARIO_SCRIPTS), default="triage", help="which job to run")
    args = parser.parse_args()
    script_name = SCENARIO_SCRIPTS[args.scenario]

    wanted = set(args.only.split(",")) if args.only else {o.number for o in OPTIONS}
    rows: list[tuple[Option, RunMetrics | None, str]] = []
    for option in OPTIONS:
        if option.number not in wanted:
            continue
        script = REPO_ROOT / option.folder / script_name
        if not script.exists():
            rows.append((option, None, f"skipped: no {args.scenario} scenario for this option"))
            continue
        reason = option.ready()
        if reason:
            rows.append((option, None, f"skipped: {reason}"))
            continue
        if args.check:
            rows.append((option, None, "ready"))
            continue

        metrics_path = OUT_DIR / option.folder / f"metrics-{args.scenario}.json"
        metrics_path.unlink(missing_ok=True)
        print(f"\n===== {option.folder} =====", flush=True)
        proc = subprocess.run(
            [sys.executable, str(script), str(args.log), "--metrics", str(metrics_path)],
            stdin=subprocess.DEVNULL,  # unattended: any tool approval prompt is denied
        )
        if proc.returncode != 0 or not metrics_path.exists():
            rows.append((option, None, f"failed (exit code {proc.returncode}), see output above"))
            continue
        rows.append((option, RunMetrics.load(metrics_path), "ok"))

    print_table(rows)
    print_build_table(script_name)
    results = {
        o.folder: json.loads((OUT_DIR / o.folder / f"metrics-{args.scenario}.json").read_text())
        for o, m, _ in rows
        if m
    }
    if results:
        summary = OUT_DIR / f"comparison-{args.scenario}.json"
        summary.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nSaved {summary.relative_to(REPO_ROOT)}. Reports are in out/<option>/.")


if __name__ == "__main__":
    main()
