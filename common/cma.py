"""Managed Agents client code shared by demos 4, 5 and 6.

The sessions API is the same whether Anthropic hosts it (demos 4 and 5) or you
do (demo 6). Only the client's base URL and credentials change.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field

import anthropic
from anthropic.types.beta.sessions import (
    BetaManagedAgentsAgentToolUseEvent,
    BetaManagedAgentsUserDefineOutcomeEventParams,
)
from anthropic.types.beta.sessions.beta_managed_agents_user_message_event_params import (
    Content as MessageContent,  # re-exported for demo 6
)

from common.metrics import RunMetrics

__all__ = ["MessageContent", "SessionResult", "hosted_client", "self_hosted_client", "session_metrics", "stream_session"]


def hosted_client() -> anthropic.Anthropic:
    """Client for Anthropic-hosted Managed Agents.

    Default: the Claude API, with ANTHROPIC_API_KEY or an `ant auth login` profile.
    Set CMA_PLATFORM=aws to use Claude Platform on AWS instead: SigV4 with your AWS
    credentials, billed through AWS Marketplace. That needs `pip install "anthropic[aws]"`
    plus AWS_REGION and ANTHROPIC_AWS_WORKSPACE_ID. Amazon Bedrock has no Managed Agents.
    """
    if os.environ.get("CMA_PLATFORM") == "aws":
        from anthropic import AnthropicAWS

        return AnthropicAWS()
    return anthropic.Anthropic()


def self_hosted_client() -> anthropic.Anthropic:
    """Client for your own cma-server (demo 6).

    Uses its own variable names so it can't pick up a Claude API key by mistake.
    """
    base_url = os.environ.get("CMA_SELF_HOSTED_URL")
    api_key = os.environ.get("CMA_SELF_HOSTED_API_KEY")
    if not base_url or not api_key:
        sys.exit("Set CMA_SELF_HOSTED_URL and CMA_SELF_HOSTED_API_KEY (the server API key).")
    return anthropic.Anthropic(base_url=base_url, api_key=api_key)


def approve(event: BetaManagedAgentsAgentToolUseEvent) -> bool:
    """Ask the person at the terminal about a tool call the server could not decide on."""
    print(f"\n[approval needed] {event.name}: {json.dumps(event.input)[:300]}")
    if not sys.stdin.isatty():  # unattended run: deny
        print("No terminal attached, denying.")
        return False
    try:
        return input("Allow? [y/N] ").strip().lower() == "y"
    except EOFError:
        return False


@dataclass
class SessionResult:
    stop_reason: str
    tool_calls: int = 0
    turns: int = 0
    agent_text: list[str] = field(default_factory=list)
    # Outcomes only: one entry per grader pass, and the grader's token usage.
    outcome_results: list[str] = field(default_factory=list)
    grader_input_tokens: int = 0
    grader_output_tokens: int = 0
    grader_cache_read_tokens: int = 0
    grader_cache_write_tokens: int = 0


def stream_session(
    client: anthropic.Anthropic,
    session_id: str,
    content: list[MessageContent] | None = None,
    outcome: BetaManagedAgentsUserDefineOutcomeEventParams | None = None,
) -> SessionResult:
    """Start the agent, print events until it stops, and return what happened.

    Pass `content` for a plain user message, or `outcome` to define an outcome
    instead. With an outcome the agent starts on its own, and a separate grader
    scores each draft against the rubric until it passes or runs out of tries.
    """
    result = SessionResult(stop_reason="stream_closed")
    # Open the stream first, then send, so no early events are missed.
    with client.beta.sessions.events.stream(session_id) as stream:
        if outcome is not None:
            client.beta.sessions.events.send(session_id, events=[outcome])
        else:
            client.beta.sessions.events.send(
                session_id,
                events=[{"type": "user.message", "content": content or []}],
            )
        for event in stream:
            if event.type == "agent.message":
                result.turns += 1
                text = "".join(block.text for block in event.content if block.type == "text")
                if text:
                    result.agent_text.append(text)  # one entry per agent message
                    print(text, end="", flush=True)
            elif event.type == "agent.tool_use":
                result.tool_calls += 1
                cmd = event.input.get("command") or event.input.get("path") or ""
                print(f"\n[tool] {event.name} {str(cmd)[:120]}", flush=True)
                if event.evaluated_permission == "ask":
                    client.beta.sessions.events.send(
                        session_id,
                        events=[{
                            "type": "user.tool_confirmation",
                            "tool_use_id": event.id,
                            "result": "allow" if approve(event) else "deny",
                        }],
                    )
            elif event.type == "span.outcome_evaluation_start":
                print(f"\n[grader] iteration {event.iteration}: evaluation started", flush=True)
            elif event.type == "span.outcome_evaluation_ongoing":
                print(".", end="", flush=True)  # heartbeat; the grader's reasoning isn't shown
            elif event.type == "span.outcome_evaluation_end":
                result.outcome_results.append(event.result)
                usage = event.usage
                result.grader_input_tokens += usage.input_tokens
                result.grader_output_tokens += usage.output_tokens
                result.grader_cache_read_tokens += usage.cache_read_input_tokens
                result.grader_cache_write_tokens += usage.cache_creation_input_tokens
                print(
                    f"\n[grader] iteration {event.iteration}: {event.result} "
                    f"({usage.input_tokens:,} in, {usage.output_tokens:,} out)\n"
                    f"[grader] {event.explanation}",
                    flush=True,
                )
            elif event.type == "session.error":
                print(f"\n[error] {event.error}", file=sys.stderr)
            elif event.type == "session.status_idle":
                # requires_action means the agent waits on us (a tool approval): keep going.
                if event.stop_reason.type != "requires_action":
                    result.stop_reason = event.stop_reason.type
                    return result
            elif event.type == "session.status_terminated":
                result.stop_reason = "terminated"
                return result
    return result


def session_metrics(
    client: anthropic.Anthropic,
    option: str,
    session_id: str,
    started: float,
    result: SessionResult,
    bill_runtime: bool = True,
) -> RunMetrics:
    """Read the session's own usage counters after it stops.

    bill_runtime=False for your own cma-server: there is no per-session-hour
    charge there (the license is quoted separately), and model calls are billed
    by your provider, so a reported list cost is only a yardstick.
    """
    metrics = RunMetrics(
        option=option,
        seconds=time.monotonic() - started,
        tool_calls=result.tool_calls,
        model_calls=result.turns,
        notes=f"stop reason: {result.stop_reason}",
        outcome_result=result.outcome_results[-1] if result.outcome_results else None,
        grader_passes=len(result.outcome_results) or None,
        grader_input_tokens=result.grader_input_tokens,
        grader_output_tokens=result.grader_output_tokens,
        grader_cache_read_tokens=result.grader_cache_read_tokens,
        grader_cache_write_tokens=result.grader_cache_write_tokens,
    )
    usage = client.beta.sessions.retrieve(session_id).usage
    if usage is None:
        return metrics
    metrics.input_tokens = usage.input_tokens or 0
    metrics.output_tokens = usage.output_tokens or 0
    metrics.cache_read_tokens = usage.cache_read_input_tokens or 0
    if usage.cache_creation:
        metrics.cache_write_tokens = (usage.cache_creation.ephemeral_5m_input_tokens or 0) + (
            usage.cache_creation.ephemeral_1h_input_tokens or 0
        )
    if bill_runtime:
        metrics.runtime_seconds = usage.active_seconds or 0.0
    if usage.list_cost:
        metrics.reported_cost_usd = int(usage.list_cost.amount) / 100  # amount is in cents
    return metrics
