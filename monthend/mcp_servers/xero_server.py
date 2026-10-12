"""MCP server: read-only Xero Accounting API.

Backend per client config (`source.backend`), overridable with MONTHEND_BACKEND:
'fixtures' reads the synthetic files, 'live' calls Xero with OAuth 2.0 and paces
itself under Xero's 60-calls-per-minute limit. There are no write tools.
"""

from __future__ import annotations

import json
from datetime import date

from mcp.server.fastmcp import FastMCP

from monthend.config import load_client, var_dir
from monthend.mcp_servers._common import tool_errors
from monthend.money import dec
from monthend.sources.xero_parse import invoice_date, parse_budgets, parse_trial_balance

mcp = FastMCP("xero", instructions="Read-only access to Xero. Use for ad-hoc look-ups; run figures come from the monthend server's frozen snapshot.")


class _Fixtures:
    def __init__(self, client):
        self.root = client.fixtures_dir / "xero"

    def _read(self, name: str) -> dict:
        path = self.root / name
        if not path.exists():
            raise FileNotFoundError(f"no fixture {name}")
        return json.loads(path.read_text())

    def organisation(self):
        return self._read("organisation.json")

    def accounts(self):
        return self._read("accounts.json")

    def trial_balance(self, as_at: date):
        return self._read(f"trial-balance-{as_at.isoformat()}.json")

    def budgets(self):
        return self._read("budgets.json")

    def invoices(self, date_to: date, date_from: date | None = None):
        return self._read("invoices.json")

    def bank_transactions(self, date_from: date, date_to: date):
        return self._read("bank-transactions.json")


def _source(client_id: str):
    client = load_client(client_id)
    if client.backend == "fixtures":
        return _Fixtures(client)
    from monthend.sources.xero import XeroAuth, XeroClient

    return XeroClient(XeroAuth.from_env(var_dir()), client.xero_tenant_id)


@mcp.tool()
@tool_errors
def xero_get_organisation(client_id: str) -> dict:
    """Organisation name, base currency and financial year end."""
    org = _source(client_id).organisation()["Organisations"][0]
    return {k: org.get(k) for k in ("Name", "LegalName", "BaseCurrency", "CountryCode", "FinancialYearEndDay", "FinancialYearEndMonth")}


@mcp.tool()
@tool_errors
def xero_list_accounts(client_id: str) -> list[dict]:
    """Chart of accounts: code, name, type, class, status."""
    return [{k: a.get(k) for k in ("Code", "Name", "Type", "Class", "Status")} for a in _source(client_id).accounts()["Accounts"]]


@mcp.tool()
@tool_errors
def xero_get_trial_balance(client_id: str, as_at: str) -> dict:
    """Trial balance at a date (YYYY-MM-DD). Signed amounts, debit positive; 'month' is the movement for that month."""
    lines = parse_trial_balance(_source(client_id).trial_balance(date.fromisoformat(as_at)))
    return {"as_at": as_at, "imbalance": str(sum((l.ytd for l in lines), dec(0))),
            "lines": [{"code": l.code, "name": l.name, "section": l.section, "month": str(l.month), "ytd_or_closing": str(l.ytd)} for l in lines]}


@mcp.tool()
@tool_errors
def xero_get_budget(client_id: str, account_code: str = "") -> dict:
    """Monthly budget amounts by account (natural sign). Optionally one account."""
    budgets = parse_budgets(_source(client_id).budgets())
    if account_code:
        budgets = {account_code: budgets.get(account_code, {})}
    return {code: {m: str(v) for m, v in months.items()} for code, months in budgets.items()}


@mcp.tool()
@tool_errors
def xero_list_invoices(client_id: str, date_from: str, date_to: str, invoice_type: str = "", account_code: str = "") -> list[dict]:
    """Sales invoices (ACCREC) and supplier bills (ACCPAY) dated in a range, optionally filtered by type or line account code."""
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out = []
    for inv in _source(client_id).invoices(date_to=end, date_from=start)["Invoices"]:
        when = invoice_date(inv)
        if not when or not (start <= when <= end):
            continue
        if invoice_type and inv.get("Type") != invoice_type:
            continue
        if account_code and account_code not in {li.get("AccountCode") for li in inv.get("LineItems", [])}:
            continue
        out.append({"evidence_id": f"xero:invoice:{inv['InvoiceNumber']}", "number": inv["InvoiceNumber"], "type": inv.get("Type"),
                    "contact": inv["Contact"]["Name"], "date": str(when), "status": inv.get("Status"),
                    "subtotal": str(dec(inv.get("SubTotal"))), "total": str(dec(inv.get("Total"))), "amount_due": str(dec(inv.get("AmountDue"))),
                    "lines": [{"description": li.get("Description"), "account": li.get("AccountCode"), "amount": str(dec(li.get("LineAmount")))}
                              for li in inv.get("LineItems", [])]})
    return out


@mcp.tool()
@tool_errors
def xero_list_bank_transactions(client_id: str, date_from: str, date_to: str, unreconciled_only: bool = False) -> list[dict]:
    """Spend and receive money transactions in a date range."""
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    out = []
    for txn in _source(client_id).bank_transactions(start, end)["BankTransactions"]:
        when = invoice_date(txn)
        if not when or not (start <= when <= end) or (unreconciled_only and txn.get("IsReconciled")):
            continue
        out.append({"evidence_id": f"xero:banktxn:{txn.get('Reference') or txn['BankTransactionID']}", "type": txn.get("Type"),
                    "contact": txn["Contact"]["Name"], "date": str(when), "reference": txn.get("Reference"),
                    "total": str(dec(txn.get("Total"))), "reconciled": txn.get("IsReconciled"),
                    "bank_account": txn.get("BankAccount", {}).get("Code")})
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
