"""Backends write one period's source data into a run's inputs/ folder.

Both backends produce identical file names, so everything downstream (pack,
workpapers, commentary, evaluation) reads a frozen snapshot and never calls a
live system. That is what makes a run reproducible and reviewable.

Canonical files:
    organisation.json, accounts.json, trial-balance-current.json,
    trial-balance-prior.json, budgets.json, invoices.json,
    bank-transactions.json, messages.json, documents/<files>
"""

from __future__ import annotations

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from monthend.config import ClientConfig, Period, var_dir


class SourceBackend(Protocol):
    name: str

    def fetch(self, client: ClientConfig, period: Period, dest: Path) -> None: ...


def _write(dest: Path, name: str, data: dict) -> None:
    (dest / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


class FixtureBackend:
    """Reads Xero-shaped JSON and documents from fixtures/<client>/ (demo and evaluation)."""

    name = "fixtures"

    def fetch(self, client: ClientConfig, period: Period, dest: Path) -> None:
        if client.fixtures_dir is None:
            raise ValueError(f"{client.client_id} has no fixtures_dir")
        root = client.fixtures_dir
        xero = root / "xero"
        copies = {
            "organisation.json": xero / "organisation.json",
            "accounts.json": xero / "accounts.json",
            "trial-balance-current.json": xero / f"trial-balance-{period.end.isoformat()}.json",
            "trial-balance-prior.json": xero / f"trial-balance-{period.prior().end.isoformat()}.json",
            "budgets.json": xero / "budgets.json",
            "invoices.json": xero / "invoices.json",
            "bank-transactions.json": xero / "bank-transactions.json",
            "messages.json": root / "outlook" / "messages.json",
        }
        for name, source in copies.items():
            if not source.exists():
                raise FileNotFoundError(f"fixture missing for {period.key}: {source.relative_to(root)}")
            shutil.copyfile(source, dest / name)
        folder = root / "sharepoint" / client.sharepoint_folder.format(period=period.key)
        docs = dest / "documents"
        docs.mkdir(exist_ok=True)
        if folder.exists():
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    shutil.copyfile(path, docs / path.name)


class LiveBackend:
    """Pulls from Xero and Microsoft 365. Read-only."""

    name = "live"

    def __init__(self, xero=None, graph=None):
        self._xero, self._graph = xero, graph

    def _clients(self, client: ClientConfig):
        from monthend.sources.graph import GraphClient
        from monthend.sources.xero import XeroAuth, XeroClient

        xero = self._xero or XeroClient(XeroAuth.from_env(var_dir()), client.xero_tenant_id)
        graph = self._graph or GraphClient.from_env()
        return xero, graph

    def fetch(self, client: ClientConfig, period: Period, dest: Path) -> None:
        from monthend.sources.graph import sharepoint_site

        xero, graph = self._clients(client)
        _write(dest, "organisation.json", xero.organisation())
        _write(dest, "accounts.json", xero.accounts())
        _write(dest, "trial-balance-current.json", xero.trial_balance(period.end))
        _write(dest, "trial-balance-prior.json", xero.trial_balance(period.prior().end))
        _write(dest, "budgets.json", xero.budgets())
        fy_start = period.fy_months(client.fy_start_month)[0].start
        _write(dest, "invoices.json", xero.invoices(date_to=period.end, date_from=fy_start - timedelta(days=365)))
        _write(dest, "bank-transactions.json", xero.bank_transactions(period.start, period.end))

        window_from = f"{(period.start - timedelta(days=45)).isoformat()}T00:00:00Z"
        window_to = f"{(period.end + timedelta(days=20)).isoformat()}T23:59:59Z"
        messages = graph.list_messages(client.mailbox, window_from, window_to) if client.mailbox else []
        # Keep previews only: enough to cite, minimal personal data in the snapshot.
        _write(dest, "messages.json", {"value": [
            {k: m.get(k) for k in ("id", "subject", "from", "receivedDateTime", "bodyPreview")} for m in messages
        ]})

        docs = dest / "documents"
        docs.mkdir(exist_ok=True)
        host, site_path = sharepoint_site()
        if host and client.sharepoint_folder:
            site = graph.site_id(host, site_path)
            for item in graph.folder_children(site, client.sharepoint_folder.format(period=period.key)):
                if "file" in item:
                    (docs / Path(item["name"]).name).write_bytes(graph.download(site, item["id"]))


def backend_for(name: str) -> SourceBackend:
    if name == "fixtures":
        return FixtureBackend()
    if name == "live":
        return LiveBackend()
    raise ValueError(f"unknown backend {name!r}; use 'fixtures' or 'live'")
