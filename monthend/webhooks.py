"""Xero webhook receiver.

Validates x-xero-signature, answers Xero's intent-to-receive check, and queues the
affected tenant so the next overnight run picks up late changes (for example a
journal posted after the pack was prepared). It never triggers model work directly;
it only marks data as stale, which keeps cost and behaviour predictable.

Put it behind HTTPS (a reverse proxy or tunnel); Xero only calls https URLs.
"""

from __future__ import annotations

import http.server
import json
import os
from datetime import datetime, timezone

from monthend.config import var_dir
from monthend.sources.xero import verify_webhook_signature


def serve(port: int = 8780) -> None:
    key = os.environ.get("XERO_WEBHOOK_KEY")
    if not key:
        raise SystemExit("XERO_WEBHOOK_KEY is not set")
    queue = var_dir() / "webhook-queue.jsonl"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if not verify_webhook_signature(body, self.headers.get("x-xero-signature", ""), key):
                self.send_response(401)
                self.end_headers()
                return
            payload = json.loads(body or b"{}")
            with queue.open("a") as handle:
                for event in payload.get("events", []):
                    handle.write(json.dumps({"received_at": datetime.now(timezone.utc).isoformat(), "tenant": event.get("tenantId"),
                                             "category": event.get("eventCategory"), "type": event.get("eventType"),
                                             "resource": event.get("resourceId")}) + "\n")
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    print(f"Listening for Xero webhooks on :{port}")
    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()
