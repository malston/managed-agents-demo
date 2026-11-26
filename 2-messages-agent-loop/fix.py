"""Option 2, code-fix scenario: fix the bug behind the top log error, with hand-written tools.

The same job as 3-agent-sdk/fix.py. Here you write every tool the agent needs:
listing files, reading, searching, editing and running tests. You also write the
guard rails a harness would give you: keep paths inside the workspace, strip
credentials from the test run, cap the time, and stop when the budget runs out.
Count the lines between the "tool code" markers to see what that costs you.

The tool runner doesn't compact context. Every file the agent reads stays in
the conversation until the run ends.

    python 2-messages-agent-loop/fix.py [LOG] [--max-budget 3.00] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AnthropicBedrockMantle, beta_tool
from anthropic.lib.tools import BetaFunctionTool

from common import DEFAULT_LOG, MODEL_BEDROCK_MANTLE, OUT_DIR, codefix
from common.metrics import RunMetrics

OPTION = "2-messages-agent-loop"
WORKDIR = OUT_DIR / OPTION / "fix-workspace"
MAX_ITERATIONS = 40

SYSTEM_PROMPT = """You are a software engineer fixing a production bug. You can only
see the code through your tools. Search before you read, and read only what you need.
Settings in payments/settings.py belong to the ops team: fix the code, not the settings.
When the tests pass and FIX.md is written, reply with one sentence and stop."""


# --- tool code: start ---
def make_tools(root: Path) -> list[BetaFunctionTool[Any]]:
    """Every tool the agent can use. Each one is code you write, test and maintain."""
    root = root.resolve()

    def inside(path: str) -> Path:
        """Resolve a path the model sent, and refuse anything outside the workspace."""
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            raise ValueError(f"{path} is outside the workspace")
        return target

    @beta_tool
    def list_files(path: str = ".") -> str:
        """List files under a folder in the workspace, recursively.

        Args:
            path: Folder relative to the workspace root.
        """
        try:
            base = inside(path)
        except ValueError as err:
            return f"Error: {err}"
        files = [
            str(p.relative_to(root)) for p in sorted(base.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
        ]
        return "\n".join(files[:500]) or "No files."

    @beta_tool
    def read_file(path: str, start_line: int = 1, end_line: int = 400) -> str:
        """Read a text file, with line numbers.

        Args:
            path: File relative to the workspace root.
            start_line: First line to return, counting from 1.
            end_line: Last line to return.
        """
        try:
            lines = inside(path).read_text().splitlines()
        except (ValueError, OSError) as err:
            return f"Error: {err}"
        chosen = lines[max(start_line - 1, 0) : end_line]
        return "\n".join(f"{n:>5}  {text}" for n, text in enumerate(chosen, start=max(start_line, 1)))

    @beta_tool
    def search_code(pattern: str, max_results: int = 50) -> str:
        """Search every text file in the workspace for a regular expression.

        Args:
            pattern: Python regular expression.
            max_results: Maximum matching lines to return.
        """
        try:
            regex = re.compile(pattern)
        except re.error as err:
            return f"Error: bad pattern: {err}"
        hits: list[str] = []
        for file in sorted(root.rglob("*")):
            if not file.is_file() or "__pycache__" in file.parts:
                continue
            try:
                text = file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(f"{file.relative_to(root)}:{number}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        return "\n".join(hits)
        return "\n".join(hits) or "No matches."

    @beta_tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Replace one exact piece of text in a file. old_text must appear exactly once.

        Args:
            path: File relative to the workspace root.
            old_text: The text to replace, copied exactly, including spaces.
            new_text: The replacement text.
        """
        try:
            target = inside(path)
            text = target.read_text()
        except (ValueError, OSError) as err:
            return f"Error: {err}"
        if target.name == "settings.py":
            return "Error: settings.py belongs to the ops team. Fix the code instead."
        count = text.count(old_text)
        if count != 1:
            return f"Error: old_text appears {count} times. It must appear exactly once."
        target.write_text(text.replace(old_text, new_text))
        return f"Edited {path}."

    @beta_tool
    def write_file(path: str, content: str) -> str:
        """Create a new file, or replace a whole file. Use edit_file for small changes.

        Args:
            path: File relative to the workspace root.
            content: The full file content.
        """
        try:
            target = inside(path)
        except ValueError as err:
            return f"Error: {err}"
        if target.name == "settings.py":
            return "Error: settings.py belongs to the ops team. Fix the code instead."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} characters to {path}."

    @beta_tool
    def run_tests() -> str:
        """Run the service's whole unit test suite and return the output."""
        # Runs on this machine. Credentials are stripped and time is capped, but
        # this is not a sandbox: use a container for code you don't trust.
        passed, output = codefix.run_tests(root)
        return ("PASSED\n" if passed else "FAILED\n") + output

    return [list_files, read_file, search_code, edit_file, write_file, run_tests]


# --- tool code: end ---


def run(client: AnthropicBedrockMantle, log: Path, model: str, max_budget: float) -> RunMetrics:
    workdir = codefix.prepare_workspace(WORKDIR, log, with_claude_setup=False)
    started = time.monotonic()
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},
        tools=make_tools(workdir),
        max_iterations=MAX_ITERATIONS,
        messages=[{"role": "user", "content": codefix.TASK}],
    )

    metrics = RunMetrics(option=f"{OPTION} (fix)", seconds=0.0, model_calls=0, tool_calls=0)
    # Turn handling you write yourself: count, print, and stop on budget.
    for message in runner:
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
            metrics.notes = "Claude declined this request."
            break
        if metrics.token_cost_usd() > max_budget:
            metrics.notes = f"Stopped: estimated cost passed ${max_budget:.2f}."
            print(metrics.notes, file=sys.stderr)
            break

    metrics.seconds = time.monotonic() - started
    check = codefix.verify(workdir)
    print(f"\nCheck: {check.summary()}")
    metrics.notes = (metrics.notes + " " if metrics.notes else "") + check.summary()
    fix_note = workdir / "FIX.md"
    metrics.report_path = str(fix_note) if fix_note.exists() else None
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--max-budget", type=float, default=3.00, help="stop when estimated cost passes this (USD)")
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    client = AnthropicBedrockMantle(aws_region=args.region)
    metrics = run(client, args.log, args.model, args.max_budget)
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
