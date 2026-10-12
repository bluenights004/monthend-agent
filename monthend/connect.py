"""One-time Xero consent: opens the authorisation URL and captures the code on localhost."""

from __future__ import annotations

import http.server
import secrets
import urllib.parse
import webbrowser

from monthend.config import var_dir
from monthend.sources.xero import XeroAuth, XeroClient


def connect_xero(port: int = 8765) -> None:
    auth = XeroAuth.from_env(var_dir())
    redirect = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)
    captured: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            captured.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Xero connected. You can close this tab.")

        def log_message(self, *args):
            pass

    url = auth.authorization_url(redirect, state)
    print(f"Opening Xero consent page. If it does not open, visit:\n{url}\n")
    webbrowser.open(url)
    with http.server.HTTPServer(("127.0.0.1", port), Handler) as server:
        server.handle_request()
    if captured.get("state") != state or "code" not in captured:
        raise SystemExit("Consent failed or state mismatch; nothing was stored.")
    auth.exchange_code(captured["code"], redirect)
    tenants = XeroClient(auth, tenant_id="pending").connections()
    print("Connected organisations (put the tenantId in the client config or XERO_TENANT_ID):")
    for t in tenants:
        print(f"  {t['tenantName']}: {t['tenantId']}")
