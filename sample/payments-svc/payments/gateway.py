"""Calls the card gateway (stripe-gw) with a timeout and one retry."""

from __future__ import annotations

import time
from collections.abc import Callable

from payments import settings
from payments.durations import parse_duration_ms


class UpstreamTimeout(Exception):
    pass


Transport = Callable[[str, dict[str, object], float], dict[str, object]]
"""Sends one request: (url, payload, timeout in seconds) -> response. Raises TimeoutError."""


class GatewayClient:
    def __init__(self, transport: Transport, sleep: Callable[[float], None] = time.sleep) -> None:
        self.transport = transport
        self.sleep = sleep
        self.timeout_ms = parse_duration_ms(settings.STRIPE_GW_TIMEOUT)
        self.retry_delay_ms = parse_duration_ms(settings.RETRY_DELAY)

    def charge(self, amount_cents: int, card_token: str) -> dict[str, object]:
        payload: dict[str, object] = {"amount": amount_cents, "source": card_token}
        for attempt in range(1, settings.MAX_ATTEMPTS + 1):
            try:
                return self.transport(settings.STRIPE_GW_URL, payload, self.timeout_ms / 1000)
            except TimeoutError:
                if attempt == settings.MAX_ATTEMPTS:
                    raise UpstreamTimeout(
                        f"upstream timeout calling stripe-gw after {self.timeout_ms}ms"
                    ) from None
                self.sleep(self.retry_delay_ms / 1000)
        raise AssertionError("unreachable")
