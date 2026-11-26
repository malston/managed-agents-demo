import unittest

from payments.gateway import GatewayClient, UpstreamTimeout


class GatewayTest(unittest.TestCase):
    def test_returns_the_response(self) -> None:
        client = GatewayClient(lambda url, payload, timeout: {"status": "ok"}, sleep=lambda s: None)
        self.assertEqual(client.charge(500, "tok_1"), {"status": "ok"})

    def test_retries_once_then_gives_up(self) -> None:
        calls: list[float] = []

        def always_times_out(url: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
            calls.append(timeout)
            raise TimeoutError

        client = GatewayClient(always_times_out, sleep=lambda s: None)
        with self.assertRaises(UpstreamTimeout):
            client.charge(500, "tok_1")
        self.assertEqual(len(calls), 2)
