"""Option 3, code-fix scenario: fix the bug behind the top log error, with the Agent SDK.

The same job as 2-messages-agent-loop/fix.py, without writing any tools. The SDK
brings Read, Grep, Glob, Edit, Write and Bash. What you write instead is policy:

- Permission rules: edit files in the workspace, and run only the unit tests.
- Hooks: block edits to settings.py, and keep an audit list of changed files.
- Limits: max_turns and max_budget_usd stop a run that goes nowhere.
- Your team's Claude Code setup: the service's CLAUDE.md and its
  fix-regression skill load as they would for a developer in Claude Code.
- Compaction: when the context gets long, the SDK summarizes it and carries on.
  A PreCompact hook prints when that happens.

    python 3-agent-sdk/fix.py [LOG] [--max-budget 3.00] [--metrics out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookContext,
    HookInput,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk.types import SyncHookJSONOutput

from common import DEFAULT_LOG, MODEL_BEDROCK_MANTLE, OUT_DIR, codefix
from common.metrics import RunMetrics

OPTION = "3-agent-sdk"
WORKDIR = OUT_DIR / OPTION / "fix-workspace"
CHANGED: list[str] = []  # filled by the PostToolUse hook


# --- hook code: start ---
async def protect_settings(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> SyncHookJSONOutput:
    """PreToolUse: CLAUDE.md asks the agent not to touch settings. This makes it a rule."""
    tool_input: dict[str, Any] = input_data.get("tool_input", {})  # type: ignore[assignment]
    if str(tool_input.get("file_path", "")).endswith("settings.py"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "settings.py belongs to the ops team. Fix the code instead.",
            }
        }
    return {}


async def record_change(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> SyncHookJSONOutput:
    """PostToolUse: keep an audit list of every file the agent changed."""
    tool_input: dict[str, Any] = input_data.get("tool_input", {})  # type: ignore[assignment]
    path = str(tool_input.get("file_path", ""))
    if path and path not in CHANGED:
        CHANGED.append(path)
    return {}


async def note_compaction(input_data: HookInput, tool_use_id: str | None, context: HookContext) -> SyncHookJSONOutput:
    print(f"[compact] context is being summarized ({input_data.get('trigger')})")
    return {}


# --- hook code: end ---


def options(region: str, model: str, max_budget: float) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=model,
        cwd=str(WORKDIR),
        # Claude Code's own system prompt, so the agent works the way it does for
        # your developers. CLAUDE.md is added on top of it.
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=["project"],  # load the service's CLAUDE.md and .claude/skills
        skills=["fix-regression"],  # the team's skill, from .claude/skills/fix-regression/SKILL.md
        allowed_tools=[
            "Read",
            "Grep",
            "Glob",
            "Edit(/**)",  # edit and write anywhere in the workspace, nowhere else
            "Bash(python -m unittest *)",  # the tests, and no other command
        ],
        disallowed_tools=["WebSearch", "WebFetch"],
        permission_mode="dontAsk",  # unattended: anything not allowed above is denied
        hooks={
            "PreToolUse": [HookMatcher(matcher="Edit|Write", hooks=[protect_settings])],
            "PostToolUse": [HookMatcher(matcher="Edit|Write", hooks=[record_change])],
            "PreCompact": [HookMatcher(hooks=[note_compaction])],
        },
        max_turns=40,
        max_budget_usd=max_budget,
        env={"CLAUDE_CODE_USE_MANTLE": "1", "AWS_REGION": region},
    )


async def run(log: Path, region: str, model: str, max_budget: float) -> RunMetrics:
    workdir = codefix.prepare_workspace(WORKDIR, log)  # keeps CLAUDE.md and .claude/
    CHANGED.clear()
    started = time.monotonic()
    metrics = RunMetrics(option=f"{OPTION} (fix)", seconds=0.0, tool_calls=0)
    prompt = codefix.TASK + "\nUse the fix-regression skill."
    async for message in query(prompt=prompt, options=options(region, model, max_budget)):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
                elif isinstance(block, ToolUseBlock):
                    metrics.tool_calls = (metrics.tool_calls or 0) + 1
                    print(f"[tool] {block.name} {str(block.input)[:120]}")
        elif isinstance(message, SystemMessage):
            if message.subtype == "init":
                print(f"[init] skills: {message.data.get('skills')}, tools: {len(message.data.get('tools', []))}")
            elif message.subtype == "compact_boundary":
                print("[compact] done, the run continues on the summary")
        elif isinstance(message, ResultMessage):
            usage = message.usage or {}
            metrics.input_tokens = int(usage.get("input_tokens", 0))
            metrics.output_tokens = int(usage.get("output_tokens", 0))
            metrics.cache_read_tokens = int(usage.get("cache_read_input_tokens", 0))
            metrics.cache_write_tokens = int(usage.get("cache_creation_input_tokens", 0))
            metrics.model_calls = message.num_turns
            metrics.reported_cost_usd = message.total_cost_usd
            if message.is_error:
                metrics.notes = f"Run ended with {message.subtype}."

    metrics.seconds = time.monotonic() - started
    print(f"\nFiles changed (from the PostToolUse hook): {', '.join(CHANGED) or 'none'}")
    check = codefix.verify(workdir)
    print(f"Check: {check.summary()}")
    metrics.notes = (metrics.notes + " " if metrics.notes else "") + check.summary()
    fix_note = workdir / "FIX.md"
    metrics.report_path = str(fix_note) if fix_note.exists() else None
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log", nargs="?", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--model", default=os.environ.get("BEDROCK_MODEL", MODEL_BEDROCK_MANTLE))
    parser.add_argument("--max-budget", type=float, default=3.00, help="max_budget_usd for the run")
    parser.add_argument("--metrics", type=Path, help="write run metrics as JSON to this path")
    args = parser.parse_args()

    metrics = asyncio.run(run(args.log.resolve(), args.region, args.model, args.max_budget))
    metrics.print_summary()
    if args.metrics:
        metrics.save(args.metrics)


if __name__ == "__main__":
    main()
