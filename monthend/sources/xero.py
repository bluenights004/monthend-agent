"""Read-only Xero Accounting API client.

- OAuth 2.0: authorisation-code flow with rotating refresh tokens, or Xero "custom
  connections" (client_credentials) for unattended single-organisation access.
- Rate limits: Xero allows 60 calls/minute and 5,000 calls/day per organisation, plus
  5 concurrent calls. We pace ourselves below the minute limit, read the
  X-MinLimit-Remaining / X-DayLimit-Remaining headers, and honour Retry-After on 429.
- Read-only by construction: `_get` is the only request method for accounting data.
  There is deliberately no code path that posts journals or edits invoices.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from datetime import date
from pathlib import Path

from monthend.sources.http import (FileTokenStore, IntegrationError, MinuteWindowLimiter, ReauthorisationRequired,
                                   require_env, send_with_retries)

log = logging.getLogger("monthend.xero")

IDENTITY_URL = "https://identity.xero.com/connect/token"
AUTHORISE_URL = "https://login.xero.com/identity/connect/authorize"
API_URL = "https://api.xero.com/api.xro/2.0"
CONNECTIONS_URL = "https://api.xero.com/connections"
# Read-only granular scopes. offline_access is needed for refresh tokens.
DEFAULT_SCOPES = ("openid profile email offline_access accounting.reports.read accounting.settings.read "
                  "accounting.transactions.read accounting.contacts.read accounting.attachments.read accounting.budgets.read")


def verify_webhook_signature(raw_body: bytes, signature: str, webhook_key: str) -> bool:
    """Xero signs webhook bodies with HMAC-SHA256 (base64) in the x-xero-signature header.

    Return 200 only when this is True, 401 otherwise; Xero's intent-to-receive check
    sends both valid and invalid signatures and expects exactly that behaviour.
    """
    expected = base64.b64encode(hmac.new(webhook_key.encode(), raw_body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, signature or "")


class XeroAuth:
    def __init__(self, client_id: str, client_secret: str, store: FileTokenStore, *, mode: str = "authorization_code",
                 scopes: str = DEFAULT_SCOPES, http=None):
        import httpx

        self.client_id, self.client_secret, self.store, self.mode, self.scopes = client_id, client_secret, store, mode, scopes
        self.http = http or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls, var_dir: Path) -> "XeroAuth":
        env = require_env("XERO_CLIENT_ID", "XERO_CLIENT_SECRET")
        import os

        mode = os.environ.get("XERO_AUTH_MODE", "authorization_code")
        return cls(env["XERO_CLIENT_ID"], env["XERO_CLIENT_SECRET"], FileTokenStore(var_dir / "secrets" / "xero-token.json"), mode=mode)

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        query = {"response_type": "code", "client_id": self.client_id, "redirect_uri": redirect_uri,
                 "scope": self.scopes, "state": state}
        return f"{AUTHORISE_URL}?{urllib.parse.urlencode(query)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        return self._token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})

    def access_token(self) -> str:
        token = self.store.load()
        if token and token.get("expires_at", 0) - 60 > time.time():
            return token["access_token"]
        if self.mode == "client_credentials":
            # Custom connections: no refresh token; just request a new access token.
            scopes = " ".join(s for s in self.scopes.split() if s not in ("openid", "profile", "email", "offline_access"))
            return self._token_request({"grant_type": "client_credentials", "scope": scopes})["access_token"]
        if not token.get("refresh_token"):
            raise ReauthorisationRequired("no Xero refresh token stored; run `monthend connect xero`")
        return self._token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})["access_token"]

    def force_refresh(self) -> None:
        token = self.store.load()
        token["expires_at"] = 0
        self.store.save(token)

    def _token_request(self, data: dict) -> dict:
        response = self.http.post(IDENTITY_URL, data=data, auth=(self.client_id, self.client_secret))
        if response.status_code == 400 and "invalid_grant" in response.text:
            raise ReauthorisationRequired("Xero rejected the refresh token (expired after 60 days unused, or revoked); "
                                          "a person must reconnect with `monthend connect xero`")
        if response.status_code != 200:
            raise IntegrationError(f"Xero token endpoint returned {response.status_code}: {response.text[:200]}")
        token = response.json()
        token["expires_at"] = time.time() + int(token.get("expires_in", 1800))
        # Refresh tokens rotate: persist the new one before anything else can fail.
        self.store.save(token)
        return token


class XeroClient:
    def __init__(self, auth: XeroAuth, tenant_id: str, *, per_minute: int = 55, http=None, sleep=time.sleep):
        import httpx

        if not tenant_id:
            raise IntegrationError("XERO_TENANT_ID / source.xero_tenant_id is not set for this client")
        self.auth, self.tenant_id = auth, tenant_id
        self.http = http or httpx.Client(timeout=60)
        self.limiter = MinuteWindowLimiter(per_minute, sleep=sleep)
        self.sleep = sleep
        self.day_remaining: int | None = None

    # ------------------------------------------------------------------ transport

    def _get(self, path: str, params: dict | None = None, *, accept: str = "application/json",
             modified_since: str | None = None):
        url = path if path.startswith("http") else f"{API_URL}/{path.lstrip('/')}"

        def send():
            self.limiter.acquire()
            headers = {"Authorization": f"Bearer {self.auth.access_token()}", "xero-tenant-id": self.tenant_id,
                       "Accept": accept}
            if modified_since:
                headers["If-Modified-Since"] = modified_since
            return self.http.get(url, params=params, headers=headers)

        response = send_with_retries(send, sleep=self.sleep, on_unauthorised=self.auth.force_refresh)
        self._observe_limits(response.headers)
        if response.status_code == 304:
            return None
        if response.status_code != 200:
            raise IntegrationError(f"Xero GET {path} returned {response.status_code}: {response.text[:300]}")
        return response.json() if accept == "application/json" else response.content

    def _observe_limits(self, headers) -> None:
        day = headers.get("X-DayLimit-Remaining")
        minute = headers.get("X-MinLimit-Remaining")
        if day is not None:
            self.day_remaining = int(day)
            if self.day_remaining < 200:
                log.warning("Xero daily allowance nearly used: %s calls left", day)
        if minute is not None and int(minute) <= 2:
            self.sleep(5)

    def _paged(self, path: str, key: str, params: dict) -> list[dict]:
        items, page = [], 1
        while True:
            data = self._get(path, {**params, "page": page, "pageSize": 100})
            batch = (data or {}).get(key, [])
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    # ------------------------------------------------------------------ endpoints

    def connections(self) -> list[dict]:
        response = self.http.get(CONNECTIONS_URL, headers={"Authorization": f"Bearer {self.auth.access_token()}"})
        if response.status_code != 200:
            raise IntegrationError(f"Xero connections returned {response.status_code}")
        return response.json()

    def organisation(self) -> dict:
        return self._get("Organisation")

    def accounts(self) -> dict:
        return self._get("Accounts")

    def trial_balance(self, as_at: date) -> dict:
        return self._get("Reports/TrialBalance", {"date": as_at.isoformat()})

    def budgets(self) -> dict:
        data = self._get("Budgets")
        # The list endpoint omits budget lines; fetch each budget's detail.
        detailed = []
        for budget in data.get("Budgets", []):
            detail = self._get(f"Budgets/{budget['BudgetID']}")
            detailed.extend(detail.get("Budgets", []))
        return {"Budgets": detailed}

    def invoices(self, date_to: date, date_from: date | None = None) -> dict:
        where = f"Date <= DateTime({date_to.year}, {date_to.month:02d}, {date_to.day:02d})"
        if date_from:
            where += f" && Date >= DateTime({date_from.year}, {date_from.month:02d}, {date_from.day:02d})"
        params = {"where": where, "Statuses": "AUTHORISED,PAID"}
        return {"Invoices": self._paged("Invoices", "Invoices", params)}

    def bank_transactions(self, date_from: date, date_to: date) -> dict:
        where = (f"Date >= DateTime({date_from.year}, {date_from.month:02d}, {date_from.day:02d}) && "
                 f"Date <= DateTime({date_to.year}, {date_to.month:02d}, {date_to.day:02d})")
        return {"BankTransactions": self._paged("BankTransactions", "BankTransactions", {"where": where})}

    def attachments(self, endpoint: str, guid: str) -> list[dict]:
        return (self._get(f"{endpoint}/{guid}/Attachments") or {}).get("Attachments", [])

    def attachment_content(self, endpoint: str, guid: str, filename: str, mime_type: str) -> bytes:
        return self._get(f"{endpoint}/{guid}/Attachments/{urllib.parse.quote(filename)}", accept=mime_type)
