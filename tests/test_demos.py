"""Offline tests. No credentials and no model calls.

python -m unittest discover tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from common import DEFAULT_LOG, codefix, logtools  # noqa: E402
from common.metrics import RunMetrics  # noqa: E402


def load_demo(folder: str, script: str = "run.py") -> ModuleType:
    """Import a demo script. The folders start with a digit, so plain import won't work."""
    spec = importlib.util.spec_from_file_location(f"demo_{folder[0]}_{script[:-3]}", REPO / folder / script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LogToolsTest(unittest.TestCase):
    lines = logtools.load(DEFAULT_LOG)

    def test_counts_match_the_sample(self) -> None:
        self.assertEqual(logtools.count_by(self.lines, "level"), {"INFO": 340, "ERROR": 51, "WARN": 9})

    def test_top_issue_is_the_payment_timeout(self) -> None:
        top = logtools.issues(self.lines)[0]
        self.assertEqual((top["service"], top["count"]), ("payments-svc", 32))

    def test_slow_queries_group_into_one_pattern(self) -> None:
        warn = [row for row in logtools.issues(self.lines) if row["level"] == "WARN"]
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0]["count"], 9)

    def test_spikes_are_found(self) -> None:
        self.assertTrue(logtools.spikes(self.lines))

    def test_bad_field_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            logtools.count_by(self.lines, "host")


class WorkflowTest(unittest.TestCase):
    def test_facts_are_small_json(self) -> None:
        demo = load_demo("1-messages-workflow")
        facts = demo.build_facts(logtools.load(DEFAULT_LOG))
        self.assertIn("issues", json.loads(facts))
        self.assertLess(len(facts), len(DEFAULT_LOG.read_text()))  # far smaller than the raw log


class FakeMessagesAPI(BaseHTTPRequestHandler):
    """Plays back three model turns: call log_overview, call write_report, then stop."""

    replies: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeMessagesAPI.requests.append(body)
        reply = FakeMessagesAPI.replies.pop(0)
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        pass


def reply(content: list[dict[str, Any]], stop_reason: str) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "anthropic.claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 50},
    }


class AgentLoopTest(unittest.TestCase):
    def test_loop_runs_tools_and_saves_the_report(self) -> None:
        from anthropic import AnthropicBedrockMantle

        FakeMessagesAPI.requests = []
        FakeMessagesAPI.replies = [
            reply([{"type": "tool_use", "id": "toolu_1", "name": "log_overview", "input": {}}], "tool_use"),
            reply(
                [{"type": "tool_use", "id": "toolu_2", "name": "write_report", "input": {"markdown": "# Report"}}],
                "tool_use",
            ),
            reply([{"type": "text", "text": "Done."}], "end_turn"),
        ]
        server = HTTPServer(("127.0.0.1", 0), FakeMessagesAPI)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = AnthropicBedrockMantle(
                aws_region="us-east-1", api_key="test", base_url=f"http://127.0.0.1:{server.server_port}"
            )
            demo = load_demo("2-messages-agent-loop")
            with tempfile.TemporaryDirectory() as tmp:
                report = Path(tmp) / "report.md"
                metrics = demo.run(client, DEFAULT_LOG, "anthropic.claude-opus-5-5", report)
                self.assertEqual(report.read_text(), "# Report\n")
        finally:
            server.shutdown()

        self.assertEqual((metrics.model_calls, metrics.tool_calls), (3, 2))
        self.assertEqual(metrics.input_tokens, 3000)
        tool_names = {tool["name"] for tool in FakeMessagesAPI.requests[0]["tools"]}
        self.assertEqual(
            tool_names, {"log_overview", "count_by", "search_log", "error_spikes", "lookup_owner", "write_report"}
        )
        # The second request carries the real overview back as a tool result.
        tool_result = FakeMessagesAPI.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertIn('"lines": 400', str(tool_result["content"]))


class FakeSessions:
    """Stands in for client.beta.sessions: records sent events, replays a fixed stream."""

    def __init__(self, stream_events: list[Any]) -> None:
        self.sent: list[Any] = []
        self._stream_events = stream_events
        self.events = self

    def send(self, session_id: str, events: list[Any]) -> None:
        self.sent.extend(events)

    def stream(self, session_id: str) -> Any:
        events = self._stream_events

        class Stream:
            def __enter__(self) -> list[Any]:
                return events

            def __exit__(self, *args: object) -> None:
                pass

        return Stream()


class OutcomeStreamTest(unittest.TestCase):
    def test_grader_events_are_counted(self) -> None:
        from types import SimpleNamespace

        from common.cma import stream_session

        def usage(i: int, o: int) -> SimpleNamespace:
            return SimpleNamespace(
                input_tokens=i, output_tokens=o, cache_read_input_tokens=10, cache_creation_input_tokens=0
            )

        events = [
            SimpleNamespace(type="span.outcome_evaluation_start", iteration=0),
            SimpleNamespace(type="span.outcome_evaluation_ongoing", iteration=0),
            SimpleNamespace(
                type="span.outcome_evaluation_end",
                iteration=0,
                result="needs_revision",
                explanation="No severity on issues.",
                usage=usage(2000, 300),
            ),
            SimpleNamespace(type="span.outcome_evaluation_start", iteration=1),
            SimpleNamespace(
                type="span.outcome_evaluation_end",
                iteration=1,
                result="satisfied",
                explanation="All criteria met.",
                usage=usage(2500, 200),
            ),
            SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
        ]
        sessions = FakeSessions(events)
        client: Any = SimpleNamespace(beta=SimpleNamespace(sessions=sessions))
        outcome: Any = {"type": "user.define_outcome", "description": "d", "rubric": {"type": "text", "content": "r"}}
        result = stream_session(client, "sesn_test", outcome=outcome)

        self.assertEqual(sessions.sent, [outcome])  # the outcome is the kickoff; no user.message
        self.assertEqual(result.outcome_results, ["needs_revision", "satisfied"])
        self.assertEqual((result.grader_input_tokens, result.grader_output_tokens), (4500, 500))
        self.assertEqual(result.stop_reason, "end_turn")

    def test_rubric_covers_the_asked_criteria(self) -> None:
        rubric = (REPO / "4-managed-agents-cloud" / "rubric.md").read_text().lower()
        for criterion in ("root cause", "log lines cited", "severity", "next action"):
            self.assertIn(criterion, rubric)


def apply_known_fix(workdir: Path) -> None:
    """The fix a good agent makes: a regression test, then the one-character bug."""
    code = workdir / "payments" / "durations.py"
    code.write_text(code.read_text().replace("value * 10_000", "value * 1_000"))
    tests = workdir / "tests" / "test_durations.py"
    tests.write_text(
        tests.read_text()
        + "\n\nclass SecondsTest(unittest.TestCase):\n"
        + "    def test_seconds(self) -> None:\n"
        + '        self.assertEqual(parse_duration_ms("3s"), 3000)\n'
    )


class CodeFixScenarioTest(unittest.TestCase):
    def test_service_reproduces_the_log_error(self) -> None:
        log = DEFAULT_LOG.read_text()
        self.assertIn("upstream timeout calling stripe-gw after 30000ms", log)
        with tempfile.TemporaryDirectory() as tmp:
            workdir = codefix.prepare_workspace(Path(tmp) / "ws")
            check = codefix.verify(workdir)
        self.assertTrue(check.tests_pass)  # the shipped tests miss the bug
        self.assertFalse(check.bug_fixed)
        self.assertFalse(check.ok)

    def test_known_fix_passes_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workdir = codefix.prepare_workspace(Path(tmp) / "ws")
            apply_known_fix(workdir)
            check = codefix.verify(workdir)
        self.assertTrue(check.ok, check.summary())
        self.assertEqual(check.tests_added, 1)

    def test_option_2_tools_stay_in_the_workspace(self) -> None:
        demo = load_demo("2-messages-agent-loop", "fix.py")
        with tempfile.TemporaryDirectory() as tmp:
            workdir = codefix.prepare_workspace(Path(tmp) / "ws", with_claude_setup=False)
            tools = {tool.name: tool for tool in demo.make_tools(workdir)}
            self.assertFalse((workdir / "CLAUDE.md").exists())
            self.assertIn("outside the workspace", tools["read_file"].call({"path": "../../etc/passwd"}))
            self.assertIn("payments/durations.py:19", tools["search_code"].call({"pattern": "10_000"}))
            self.assertIn(
                "ops team",
                tools["edit_file"].call({"path": "payments/settings.py", "old_text": '"3s"', "new_text": '"3000ms"'}),
            )
            self.assertIn(
                "appears 0 times",
                tools["edit_file"].call({"path": "payments/durations.py", "old_text": "nope", "new_text": "x"}),
            )
            self.assertIn(
                "Edited",
                tools["edit_file"].call(
                    {"path": "payments/durations.py", "old_text": "value * 10_000", "new_text": "value * 1_000"}
                ),
            )
            self.assertTrue(tools["run_tests"].call({}).startswith("PASSED"))

    def test_option_3_hook_blocks_settings_edits(self) -> None:
        import asyncio

        demo = load_demo("3-agent-sdk", "fix.py")
        context: Any = {"signal": None}
        denied = asyncio.run(
            demo.protect_settings({"tool_input": {"file_path": "/ws/payments/settings.py"}}, "toolu_1", context)
        )
        allowed = asyncio.run(
            demo.protect_settings({"tool_input": {"file_path": "/ws/payments/durations.py"}}, "toolu_2", context)
        )
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(allowed, {})

    def test_compare_counts_the_tool_code(self) -> None:
        import compare as cmp

        self.assertGreater(cmp.marked_lines("2-messages-agent-loop", "fix.py", "tool") or 0, 50)
        self.assertEqual(cmp.marked_lines("3-agent-sdk", "fix.py", "tool"), 0)
        self.assertGreater(cmp.marked_lines("3-agent-sdk", "fix.py", "hook") or 0, 0)
        self.assertIsNone(cmp.marked_lines("1-messages-workflow", "fix.py", "tool"))


class FixLoopTest(unittest.TestCase):
    def test_option_2_fix_loop_end_to_end_against_a_fake_endpoint(self) -> None:
        from anthropic import AnthropicBedrockMantle

        demo = load_demo("2-messages-agent-loop", "fix.py")

        def call(n: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
            return reply([{"type": "tool_use", "id": f"toolu_{n}", "name": name, "input": args}], "tool_use")

        new_test = (
            "\n\nclass SecondsTest(unittest.TestCase):\n    def test_seconds(self) -> None:\n"
            '        self.assertEqual(parse_duration_ms("3s"), 3000)\n'
        )
        FakeMessagesAPI.requests = []
        FakeMessagesAPI.replies = [
            call(1, "search_code", {"pattern": "upstream timeout"}),
            call(
                2,
                "edit_file",
                {
                    "path": "tests/test_durations.py",
                    "old_text": '            parse_duration_ms("soon")\n',
                    "new_text": '            parse_duration_ms("soon")\n' + new_test,
                },
            ),
            call(
                3,
                "edit_file",
                {
                    "path": "payments/durations.py",
                    "old_text": "value * 10_000",
                    "new_text": "value * 1_000",
                },
            ),
            call(4, "run_tests", {}),
            call(5, "write_file", {"path": "FIX.md", "content": "# Fix\n"}),
            reply([{"type": "text", "text": "Fixed."}], "end_turn"),
        ]
        server = HTTPServer(("127.0.0.1", 0), FakeMessagesAPI)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            setattr(demo, "WORKDIR", Path(tmp) / "ws")
            try:
                client = AnthropicBedrockMantle(
                    aws_region="us-east-1", api_key="test", base_url=f"http://127.0.0.1:{server.server_port}"
                )
                metrics = demo.run(client, DEFAULT_LOG, "anthropic.claude-opus-5-5", max_budget=5.0)
            finally:
                server.shutdown()
            self.assertEqual((metrics.model_calls, metrics.tool_calls), (6, 5))
            self.assertIn("tests added: 1", metrics.notes)
            self.assertIn("bug fixed: yes", metrics.notes)
            self.assertTrue(metrics.report_path and metrics.report_path.endswith("FIX.md"))
        tool_results = FakeMessagesAPI.requests[4]["messages"][-1]["content"][0]
        self.assertTrue(str(tool_results["content"]).startswith("PASSED"))

    def test_option_2_fix_loop_stops_on_budget(self) -> None:
        from anthropic import AnthropicBedrockMantle

        demo = load_demo("2-messages-agent-loop", "fix.py")
        FakeMessagesAPI.requests = []
        FakeMessagesAPI.replies = [
            reply([{"type": "tool_use", "id": f"toolu_{n}", "name": "list_files", "input": {}}], "tool_use")
            for n in range(3)
        ]
        server = HTTPServer(("127.0.0.1", 0), FakeMessagesAPI)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            setattr(demo, "WORKDIR", Path(tmp) / "ws")
            try:
                client = AnthropicBedrockMantle(
                    aws_region="us-east-1", api_key="test", base_url=f"http://127.0.0.1:{server.server_port}"
                )
                # Each fake call costs about $0.006, so a $0.01 budget stops after the second.
                metrics = demo.run(client, DEFAULT_LOG, "anthropic.claude-opus-5-5", max_budget=0.01)
            finally:
                server.shutdown()
        self.assertEqual(metrics.model_calls, 2)
        self.assertIn("Stopped: estimated cost", metrics.notes)

    def test_option_3_options_wire_up_policy(self) -> None:
        demo = load_demo("3-agent-sdk", "fix.py")
        opts = demo.options("us-east-1", "anthropic.claude-opus-5-5", 1.5)
        self.assertEqual(opts.skills, ["fix-regression"])
        self.assertEqual(opts.setting_sources, ["project"])
        self.assertEqual(opts.permission_mode, "dontAsk")
        self.assertIn("Bash(python -m unittest *)", opts.allowed_tools)
        self.assertEqual(set(opts.hooks), {"PreToolUse", "PostToolUse", "PreCompact"})
        self.assertEqual(opts.max_budget_usd, 1.5)
        self.assertTrue((codefix.SERVICE / ".claude" / "skills" / "fix-regression" / "SKILL.md").exists())


class AttachTest(unittest.TestCase):
    def test_reattach_replays_history_then_skips_seen_events(self) -> None:
        from types import SimpleNamespace

        from common.cma import attach_session

        def text(event_id: str, words: str) -> SimpleNamespace:
            block = SimpleNamespace(type="text", text=words)
            return SimpleNamespace(id=event_id, type="agent.message", content=[block])

        history = [text("ev1", "one "), text("ev2", "two ")]
        live = [
            text("ev2", "two "),
            text("ev3", "three"),
            SimpleNamespace(id="ev4", type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
        ]
        sessions = FakeSessions(live)
        sessions.list = lambda session_id, order: history  # type: ignore[attr-defined]
        sessions.retrieve = lambda session_id: SimpleNamespace(status="running")  # type: ignore[attr-defined]
        client: Any = SimpleNamespace(beta=SimpleNamespace(sessions=sessions))
        result = attach_session(client, "sesn_test")
        self.assertEqual(result.agent_text, ["one ", "two ", "three"])  # ev2 not repeated
        self.assertEqual(result.stop_reason, "end_turn")


class PrivateApiTest(unittest.TestCase):
    def test_deploy_history_is_served_on_localhost(self) -> None:
        import urllib.request

        api = load_demo("5-managed-agents-self-hosted-sandbox", "private_api.py")
        server = api.start_in_background()
        try:
            with urllib.request.urlopen(f"{api.URL}/deploys?service=payments-svc") as response:
                rows = json.loads(response.read())
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(api.HOST, "127.0.0.1")
        self.assertEqual([row["version"] for row in rows], ["2.14.0"])


class MetricsTest(unittest.TestCase):
    def test_cost_and_round_trip(self) -> None:
        metrics = RunMetrics(
            option="x", seconds=1.0, input_tokens=1_000_000, output_tokens=100_000, runtime_seconds=3600
        )
        self.assertAlmostEqual(metrics.estimated_cost_usd(), 4.00 + 2.00 + 0.08)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            metrics.save(path)
            self.assertEqual(RunMetrics.load(path), metrics)


if __name__ == "__main__":
    unittest.main()
