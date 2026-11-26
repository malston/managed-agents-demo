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

from common import DEFAULT_LOG, logtools  # noqa: E402
from common.metrics import RunMetrics  # noqa: E402


def load_demo(folder: str) -> ModuleType:
    """Import a demo's run.py. The folders start with a digit, so plain import won't work."""
    spec = importlib.util.spec_from_file_location(f"demo_{folder[0]}", REPO / folder / "run.py")
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
        self.assertEqual(tool_names, {"log_overview", "count_by", "search_log", "error_spikes", "write_report"})
        # The second request carries the real overview back as a tool result.
        tool_result = FakeMessagesAPI.requests[1]["messages"][-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertIn('"lines": 400', str(tool_result["content"]))


class MetricsTest(unittest.TestCase):
    def test_cost_and_round_trip(self) -> None:
        metrics = RunMetrics(option="x", seconds=1.0, input_tokens=1_000_000, output_tokens=100_000, runtime_seconds=3600)
        self.assertAlmostEqual(metrics.estimated_cost_usd(), 4.00 + 2.00 + 0.08)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            metrics.save(path)
            self.assertEqual(RunMetrics.load(path), metrics)


if __name__ == "__main__":
    unittest.main()
