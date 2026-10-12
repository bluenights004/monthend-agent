"""Parse Xero Accounting API payloads into plain records.

Xero reports are nested Rows/Cells structures rather than flat tables. This module
is the only place that knows that shape, so a Xero change is a one-file fix.

Trial balance convention used throughout (matches Xero's Trial Balance report):
- "Debit"/"Credit" columns: movement for the report month.
- "YTD Debit"/"YTD Credit": year-to-date movement for P&L accounts and the
  closing balance for balance-sheet accounts.
Signed values are debit-positive. Verify the convention against one real Trial
Balance export per client during onboarding (docs/04-connecting-xero-and-microsoft-365.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from monthend.money import ZERO, dec

_ACCOUNT_CELL = re.compile(r"^(?P<name>.*?)\s*\((?P<code>[^()]+)\)\s*$")
_MS_DATE = re.compile(r"/Date\((?P<ms>-?\d+)(?P<tz>[+-]\d{4})?\)/")


@dataclass(frozen=True)
class TBLine:
    code: str
    name: str
    account_id: str
    section: str
    month: Decimal  # signed, debit positive
    ytd: Decimal    # signed, debit positive


def parse_xero_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _MS_DATE.match(value)
    if match:
        return datetime.fromtimestamp(int(match["ms"]) / 1000, tz=timezone.utc).date()
    return date.fromisoformat(value[:10])


def invoice_date(invoice: dict) -> date | None:
    return parse_xero_date(invoice.get("DateString") or invoice.get("Date"))


def parse_trial_balance(payload: dict) -> list[TBLine]:
    report = payload["Reports"][0]
    if report.get("ReportID") not in ("TrialBalance", None):
        raise ValueError(f"expected a TrialBalance report, got {report.get('ReportID')!r}")
    header = next(r for r in report["Rows"] if r["RowType"] == "Header")
    columns = [c.get("Value", "") for c in header["Cells"]]
    try:
        idx = {name: columns.index(name) for name in ("Debit", "Credit", "YTD Debit", "YTD Credit")}
    except ValueError as exc:
        raise ValueError(f"unexpected Trial Balance columns {columns}") from exc

    lines: list[TBLine] = []
    for section in report["Rows"]:
        if section["RowType"] != "Section":
            continue
        for row in section.get("Rows", []):
            if row.get("RowType") != "Row":
                continue  # SummaryRow totals are recomputed, never trusted
            cells = row["Cells"]
            match = _ACCOUNT_CELL.match(cells[0]["Value"])
            if not match:
                raise ValueError(f"cannot read account code from {cells[0]['Value']!r}")
            account_id = next((a["Value"] for a in cells[0].get("Attributes", []) if a.get("Id") == "account"), "")
            lines.append(TBLine(
                code=match["code"].strip(),
                name=match["name"].strip(),
                account_id=account_id,
                section=section.get("Title", ""),
                month=dec(cells[idx["Debit"]]["Value"]) - dec(cells[idx["Credit"]]["Value"]),
                ytd=dec(cells[idx["YTD Debit"]]["Value"]) - dec(cells[idx["YTD Credit"]]["Value"]),
            ))
    return lines


def tb_imbalance(lines: list[TBLine]) -> Decimal:
    """Sum of signed YTD balances. Zero when the trial balance balances."""
    return sum((line.ytd for line in lines), ZERO)


def parse_budgets(payload: dict, description_hint: str = "") -> dict[str, dict[str, Decimal]]:
    """Return {account_code: {"YYYY-MM": natural-sign amount}} for the chosen OVERALL budget."""
    budgets = payload.get("Budgets", [])
    candidates = [b for b in budgets if b.get("Type") == "OVERALL" and b.get("Status", "ACTIVE") == "ACTIVE"]
    if description_hint:
        candidates = [b for b in candidates if description_hint.lower() in b.get("Description", "").lower()] or candidates
    if not candidates:
        return {}
    out: dict[str, dict[str, Decimal]] = {}
    for line in candidates[0].get("BudgetLines", []):
        code = line.get("AccountCode", "")
        out[code] = {b["Period"][:7]: dec(b.get("Amount")) for b in line.get("BudgetBalances", [])}
    return out
