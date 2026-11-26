"""Code shared by the six demos: the report spec, log helpers and run metrics."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "sample" / "app.log"
OUT_DIR = REPO_ROOT / "out"

# Every demo asks for the same report, so the outputs can be compared side by side.
REPORT_SPEC = """Write a short Markdown report with these sections:
Summary, Top issues (a table with service, pattern, count, first seen, last seen),
Error spikes, Suggested next steps.
Keep the report under one page. Use plain, simple language.
Do not guess numbers; compute them or take them from tool results."""

# Model IDs. Same model everywhere; only the name format changes per platform.
MODEL_CLAUDE_API = "claude-opus-5-5"  # Claude API, Claude Platform on AWS, self-hosted CMA agents
MODEL_BEDROCK_MANTLE = "anthropic.claude-opus-5-5"  # Claude in Amazon Bedrock (bedrock-mantle)
