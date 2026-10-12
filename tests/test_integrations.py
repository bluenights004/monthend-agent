"""Connector behaviour against mocked HTTP: OAuth refresh rotation, rate limits, webhooks, Graph gating."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date

import httpx
import pytest

from monthend.sources.http import FileTokenStore, MinuteWindowLimiter, ReauthorisationRequired
from monthend.sources.xero import XeroAuth, XeroClient, verify_webhook_signature


def make_auth(tmp_path, handler, token=None):
    store = FileTokenStore(tmp_path / "token.json")
    if token:
        store.save(token)
    return XeroAuth("id", "secret", store, http=httpx.Client(transport=httpx.MockTransport(handler))), store


def test_refresh_token_rotation_is_persisted(tmp_path):
    def handler(request):
        assert b"grant_type=refresh_token" in request.content
        return httpx.Response(200, json={"access_token": "new-access", "refresh_token": "rotated", "expires_in": 1800})

    auth, store = make_auth(tmp_path, handler, {"access_token": "old", "refresh_token": "r1", "expires_at": 0})
    assert auth.access_token() == "new-access"
    assert store.load()["refresh_token"] == "rotated"
    assert oct((tmp_path / "token.json").stat().st_mode)[-3:] == "600"


def test_expired_refresh_token_needs_a_person(tmp_path):
    auth, _ = make_auth(tmp_path, lambda r: httpx.Response(400, json={"error": "invalid_grant"}),
                        {"access_token": "old", "refresh_token": "r1", "expires_at": 0})
    with pytest.raises(ReauthorisationRequired):
        auth.access_token()


def test_429_honours_retry_after_and_sends_tenant_header(tmp_path):
    calls, sleeps = [], []

    def api(request):
        calls.append(request)
        assert request.headers["xero-tenant-id"] == "tenant-1"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7", "X-Rate-Limit-Problem": "minute"})
        return httpx.Response(200, json={"Reports": []}, headers={"X-DayLimit-Remaining": "4990", "X-MinLimit-Remaining": "50"})

    auth, _ = make_auth(tmp_path, lambda r: httpx.Response(500), {"access_token": "a", "refresh_token": "r", "expires_at": 9e12})
    client = XeroClient(auth, "tenant-1", http=httpx.Client(transport=httpx.MockTransport(api)), sleep=sleeps.append)
    client.trial_balance(date(2026, 9, 30))
    assert len(calls) == 2 and 7 in sleeps
    assert calls[1].url.params["date"] == "2026-09-30"
    assert client.day_remaining == 4990


def test_pagination_stops_on_short_page(tmp_path):
    pages = []

    def api(request):
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"Invoices": [{"InvoiceNumber": f"{page}-{i}"} for i in range(100 if page < 3 else 7)]})

    auth, _ = make_auth(tmp_path, lambda r: httpx.Response(500), {"access_token": "a", "refresh_token": "r", "expires_at": 9e12})
    client = XeroClient(auth, "t", http=httpx.Client(transport=httpx.MockTransport(api)), sleep=lambda s: None)
    assert len(client.invoices(date(2026, 9, 30))["Invoices"]) == 207
    assert pages == [1, 2, 3]


def test_minute_limiter_waits_instead_of_exceeding():
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    limiter = MinuteWindowLimiter(3, clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        limiter.acquire()
    assert sleeps and sleeps[0] > 59


def test_webhook_signature():
    key, body = "webhook-key", json.dumps({"events": []}).encode()
    good = base64.b64encode(hmac.new(key.encode(), body, hashlib.sha256).digest()).decode()
    assert verify_webhook_signature(body, good, key)
    assert not verify_webhook_signature(body, good, "other-key")
    assert not verify_webhook_signature(body + b" ", good, key)


def test_graph_writes_require_a_ticket():
    from monthend.sources.graph import GraphClient

    client = GraphClient("t", "c", "s", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(AttributeError):
        client.create_draft(None, "m", "s", "b", [], [], [])  # no ticket -> cannot even start
