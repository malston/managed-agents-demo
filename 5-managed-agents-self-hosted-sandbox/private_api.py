"""A stand-in for an internal service that only your private network can reach.

It serves deploy history on 127.0.0.1, so only processes on this machine can
call it. The agent's bash tool runs in your worker, on this machine, so it can
curl it. Anthropic's hosted container (option 4) can't.

    python 5-managed-agents-self-hosted-sandbox/private_api.py    # serve until Ctrl+C
    curl -s 'http://127.0.0.1:8765/deploys?service=payments-svc'
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HOST, PORT = "127.0.0.1", 8765
URL = f"http://{HOST}:{PORT}"

DEPLOYS = [
    {"service": "orders-svc", "version": "5.2.0", "at": "2026-11-23T16:10:00Z", "change": "raise pool size to 20"},
    {
        "service": "users-svc",
        "version": "3.8.1",
        "at": "2026-11-24T08:15:00Z",
        "change": "add index hint to user search",
    },
    {
        "service": "payments-svc",
        "version": "2.14.0",
        "at": "2026-11-24T09:30:40Z",
        "change": "read STRIPE_GW_TIMEOUT as a duration string ('3s') instead of milliseconds",
        "author": "deploy-bot",
    },
]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/deploys":
            self.send_error(404, "try /deploys?service=NAME")
            return
        service = parse_qs(url.query).get("service", [None])[0]
        rows = [d for d in DEPLOYS if service is None or d["service"] == service]
        body = json.dumps(rows, indent=1).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[private api] {self.address_string()} {format % args}", flush=True)


def start_in_background() -> ThreadingHTTPServer:
    """Serve on a daemon thread. Returns the server so the caller can shut it down."""
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    print(f"Serving deploy history at {URL}/deploys (this machine only)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
