"""Time, tokens and cost for one demo run, in one shape for every option.

Each demo's run.py accepts --metrics PATH and writes a RunMetrics JSON file there.
compare.py runs the demos and prints those files side by side.

Prices are Claude API list prices for Claude Opus 5.5, checked on 2026-11-26
at https://platform.claude.com/docs/en/about-claude/pricing. Amazon Bedrock is
billed by AWS at AWS's own prices, so for demos 1 to 3 (and 6 on Bedrock) the
estimate is a yardstick, not your invoice. Change PRICES to your AWS rates if
you want a closer number. Regional (non-global) Bedrock endpoints cost 10% more.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# USD per million tokens, Claude Opus 5.5
PRICES = {
    "input": 4.00,
    "output": 20.00,
    "cache_write_5m": 5.00,
    "cache_read": 0.20,
}
SESSION_HOUR_USD = 0.08  # Managed Agents runtime, billed only while a session is running


@dataclass
class RunMetrics:
    option: str
    seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model_calls: int | None = None  # requests to the model, or agent turns
    tool_calls: int | None = None
    runtime_seconds: float = 0.0  # Managed Agents billable running time
    reported_cost_usd: float | None = None  # what the platform itself reported, if anything
    report_path: str | None = None
    notes: str = ""
    # Managed Agents outcomes (option 4). The grader's usage comes from its own
    # span.outcome_evaluation_end events. The docs don't say whether session usage
    # already includes it, so it's kept apart and left out of the estimate.
    outcome_result: str | None = None  # result of the last grader pass
    grader_passes: int | None = None  # 1 = passed or stopped on the first draft
    grader_input_tokens: int = 0
    grader_output_tokens: int = 0
    grader_cache_read_tokens: int = 0
    grader_cache_write_tokens: int = 0

    def token_cost_usd(self) -> float:
        return (
            self.input_tokens * PRICES["input"]
            + self.output_tokens * PRICES["output"]
            + self.cache_write_tokens * PRICES["cache_write_5m"]
            + self.cache_read_tokens * PRICES["cache_read"]
        ) / 1_000_000

    def runtime_cost_usd(self) -> float:
        return self.runtime_seconds / 3600 * SESSION_HOUR_USD

    def estimated_cost_usd(self) -> float:
        return self.token_cost_usd() + self.runtime_cost_usd()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self) | {"estimated_cost_usd": round(self.estimated_cost_usd(), 6)}
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> RunMetrics:
        data = json.loads(path.read_text())
        data.pop("estimated_cost_usd", None)
        return cls(**data)

    def print_summary(self) -> None:
        print(f"\n--- {self.option} ---")
        print(f"Wall time:      {self.seconds:.1f}s")
        print(
            f"Tokens:         {self.input_tokens:,} in, {self.output_tokens:,} out, "
            f"{self.cache_read_tokens:,} cache read, {self.cache_write_tokens:,} cache write"
        )
        if self.model_calls is not None:
            print(f"Model calls:    {self.model_calls}")
        if self.tool_calls is not None:
            print(f"Tool calls:     {self.tool_calls}")
        if self.grader_passes:
            print(
                f"Outcome:        {self.outcome_result} after {self.grader_passes} grader pass(es), "
                f"{self.grader_passes - 1} revision(s)"
            )
            print(
                f"Grader tokens:  {self.grader_input_tokens:,} in, {self.grader_output_tokens:,} out, "
                f"{self.grader_cache_read_tokens:,} cache read, {self.grader_cache_write_tokens:,} cache write"
            )
        print(f"Estimated cost: ${self.estimated_cost_usd():.4f} (Claude API list price)")
        if self.reported_cost_usd is not None:
            print(f"Reported cost:  ${self.reported_cost_usd:.4f}")
        if self.report_path:
            print(f"Report:         {self.report_path}")
