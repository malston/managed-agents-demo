"""Stands in for an internal service catalog: who owns a service and where its runbook is.

In option 2 this is called in-process by a custom tool, the way an agent loop
inside your own app calls your own APIs with your app's credentials. Nothing
here is exposed to the internet.
"""

from __future__ import annotations

CATALOG: dict[str, dict[str, str]] = {
    "payments-svc": {"team": "Payments", "on_call": "#payments-oncall", "runbook": "runbooks/payments-timeouts.md"},
    "orders-svc": {"team": "Orders", "on_call": "#orders-oncall", "runbook": "runbooks/postgres-connections.md"},
    "users-svc": {"team": "Identity", "on_call": "#identity-oncall", "runbook": "runbooks/slow-queries.md"},
    "gateway": {"team": "Platform", "on_call": "#platform-oncall", "runbook": "runbooks/gateway.md"},
}


def owner(service: str) -> dict[str, str]:
    """Look up a service. Raises KeyError for a service the catalog doesn't know."""
    return {"service": service} | CATALOG[service]
