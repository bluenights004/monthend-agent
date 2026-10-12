"""Paths and client configuration.

Client configuration lives in config/clients/<client_id>.json. Secrets never live
in these files: connectors read them from environment variables that a secret
manager injects (see docs/04-connecting-xero-and-microsoft-365.md).
"""

from __future__ import annotations

import calendar
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def var_dir() -> Path:
    """Runtime state (runs, database, locks). Override with MONTHEND_VAR_DIR."""
    path = Path(os.environ.get("MONTHEND_VAR_DIR", ROOT / "var"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Period:
    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> "Period":
        year, month = text.split("-")
        period = cls(int(year), int(month))
        if not 1 <= period.month <= 12:
            raise ValueError(f"bad period {text!r}; expected YYYY-MM")
        return period

    @classmethod
    def previous_to(cls, today: date) -> "Period":
        return cls(today.year - 1, 12) if today.month == 1 else cls(today.year, today.month - 1)

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def start(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def label(self) -> str:
        return self.end.strftime("%B %Y")

    def prior(self) -> "Period":
        return Period.previous_to(self.start)

    def fy_months(self, fy_start_month: int) -> list["Period"]:
        """Periods from the start of the financial year up to and including this one."""
        start_year = self.year if self.month >= fy_start_month else self.year - 1
        months, current = [], Period(start_year, fy_start_month)
        while (current.year, current.month) <= (self.year, self.month):
            months.append(current)
            current = Period(current.year + (current.month == 12), current.month % 12 + 1)
        return months


@dataclass
class WorkpaperSpec:
    code: str
    kind: str
    account: str
    pack_line: str
    title: str
    options: dict = field(default_factory=dict)


@dataclass
class ClientConfig:
    client_id: str
    name: str
    currency: str
    fy_start_month: int
    backend: str
    fixtures_dir: Path | None
    xero_tenant_id: str
    sharepoint_folder: str
    mailbox: str
    mapping_path: Path
    template_path: Path
    materiality: dict
    workpapers: list[WorkpaperSpec]
    reviewers: list[str]
    delivery: dict
    raw: dict

    @property
    def path(self) -> Path:
        return CONFIG_DIR / "clients" / f"{self.client_id}.json"


def load_client(client_id: str) -> ClientConfig:
    path = CONFIG_DIR / "clients" / f"{client_id}.json"
    if not path.exists():
        known = sorted(p.stem for p in (CONFIG_DIR / "clients").glob("*.json"))
        raise FileNotFoundError(f"no client config {path.name}; known clients: {', '.join(known) or 'none'}")
    raw = json.loads(path.read_text())
    source = raw["source"]
    backend = os.environ.get("MONTHEND_BACKEND", source.get("backend", "fixtures"))
    return ClientConfig(
        client_id=raw["client_id"],
        name=raw["name"],
        currency=raw.get("currency", "AUD"),
        fy_start_month=int(raw.get("fy_start_month", 7)),
        backend=backend,
        fixtures_dir=(ROOT / source["fixtures_dir"]) if source.get("fixtures_dir") else None,
        xero_tenant_id=os.environ.get("XERO_TENANT_ID", source.get("xero_tenant_id", "")),
        sharepoint_folder=source.get("sharepoint_folder", ""),
        mailbox=source.get("mailbox", ""),
        mapping_path=ROOT / raw["mapping"],
        template_path=ROOT / raw["template"],
        materiality=raw["materiality"],
        workpapers=[WorkpaperSpec(**spec) for spec in raw.get("workpapers", [])],
        reviewers=list(raw.get("reviewers", [])),
        delivery=raw.get("delivery", {}),
        raw=raw,
    )


def list_clients() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "clients").glob("*.json"))
