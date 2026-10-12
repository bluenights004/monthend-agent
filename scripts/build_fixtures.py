"""Generate the synthetic demo client "Harbour Joinery Pty Ltd" (fictional).

Writes Xero-shaped API responses, SharePoint-style source documents (PDF/CSV) and
Outlook-style messages under fixtures/harbour-joinery/. Everything is
deterministic so the evaluation cases have stable expected answers.

    python scripts/build_fixtures.py

All names, amounts and email addresses are invented. `.example` domains are used
so nothing can resolve to a real mailbox.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monthend.pdfgen import write_text_pdf  # noqa: E402

OUT = ROOT / "fixtures" / "harbour-joinery"
D = Decimal

# --------------------------------------------------------------------------- chart

ACCOUNTS = [
    # code, name, xero Type, xero Class
    ("090", "Business Bank Account", "BANK", "ASSET"),
    ("091", "Business Savings Account", "BANK", "ASSET"),
    ("610", "Accounts Receivable", "CURRENT", "ASSET"),
    ("620", "Prepayments", "CURRENT", "ASSET"),
    ("630", "Inventory", "INVENTORY", "ASSET"),
    ("710", "Plant and Equipment at Cost", "FIXED", "ASSET"),
    ("711", "Accumulated Depreciation - Plant", "FIXED", "ASSET"),
    ("800", "Accounts Payable", "CURRLIAB", "LIABILITY"),
    ("820", "GST", "CURRLIAB", "LIABILITY"),
    ("825", "PAYG Withholdings Payable", "CURRLIAB", "LIABILITY"),
    ("826", "Superannuation Payable", "CURRLIAB", "LIABILITY"),
    ("830", "Accrued Expenses", "CURRLIAB", "LIABILITY"),
    ("840", "Provision for Annual Leave", "CURRLIAB", "LIABILITY"),
    ("900", "Equipment Loan", "TERMLIAB", "LIABILITY"),
    ("960", "Retained Earnings", "EQUITY", "EQUITY"),
    ("970", "Share Capital", "EQUITY", "EQUITY"),
    ("200", "Sales - Fitout Contracts", "REVENUE", "REVENUE"),
    ("210", "Sales - Joinery Products", "REVENUE", "REVENUE"),
    ("260", "Other Revenue", "OTHERINCOME", "REVENUE"),
    ("310", "Materials", "DIRECTCOSTS", "EXPENSE"),
    ("320", "Subcontractors", "DIRECTCOSTS", "EXPENSE"),
    ("330", "Direct Wages", "DIRECTCOSTS", "EXPENSE"),
    ("400", "Advertising", "EXPENSE", "EXPENSE"),
    ("404", "Bank Fees", "EXPENSE", "EXPENSE"),
    ("412", "Consulting & Accounting", "EXPENSE", "EXPENSE"),
    ("416", "Depreciation", "DEPRECIATN", "EXPENSE"),
    ("420", "Rent", "OVERHEADS", "EXPENSE"),
    ("437", "Interest Expense", "EXPENSE", "EXPENSE"),
    ("445", "Light, Power, Heating", "OVERHEADS", "EXPENSE"),
    ("461", "Software Subscriptions", "OVERHEADS", "EXPENSE"),
    ("466", "Equipment Hire", "EXPENSE", "EXPENSE"),  # created 14 Sep 2026, not in the pack mapping
    ("477", "Salaries - Administration", "EXPENSE", "EXPENSE"),
    ("478", "Superannuation", "EXPENSE", "EXPENSE"),
    ("489", "Motor Vehicle Expenses", "EXPENSE", "EXPENSE"),
    ("493", "Insurance", "EXPENSE", "EXPENSE"),
]
CLASS = {code: cls for code, _, _, cls in ACCOUNTS}
NAME = {code: name for code, name, _, _ in ACCOUNTS}


def account_id(code: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"harbour-joinery/account/{code}"))


# --------------------------------------------------------------------------- P&L (natural sign, positive)

MONTHS = ["2026-07", "2026-08", "2026-09"]
PL_ACTUAL = {
    "200": ["148200", "155900", "182400"],
    "210": ["22150", "19800", "21300"],
    "260": ["350", "0", "1850"],
    "310": ["50100", "53300", "61850"],
    "320": ["31800", "33900", "28300"],
    "330": ["38400", "38900", "39250"],
    "400": ["1450", "1100", "1200"],
    "404": ["85", "92", "88"],
    "412": ["2400", "2500", "6800"],
    "416": ["3150", "3150", "3150"],
    "420": ["9500", "9500", "9500"],
    "437": ["820", "805", "790"],
    "445": ["1680", "1720", "1910"],
    "461": ["1240", "1240", "1310"],
    "466": ["0", "0", "4600"],
    "477": ["24500", "24500", "24500"],
    "478": ["2817.50", "2817.50", "2817.50"],
    "489": ["2980", "3120", "3950"],
    "493": ["1100", "1100", "1100"],
}
PL_BUDGET = {
    "200": ["150000", "155000", "160000"],
    "210": ["20000", "20000", "22000"],
    "310": ["51000", "52700", "52000"],
    "320": ["33000", "33500", "34000"],
    "330": ["39000", "39000", "39000"],
    "400": ["1500", "1500", "1500"],
    "404": ["100", "100", "100"],
    "412": ["2500", "2500", "2500"],
    "416": ["3150", "3150", "3150"],
    "420": ["9500", "9500", "9500"],
    "437": ["820", "810", "800"],
    "445": ["1700", "1700", "1700"],
    "461": ["1250", "1250", "1250"],
    "477": ["24500", "24500", "24500"],
    "478": ["2817.50", "2817.50", "2817.50"],
    "489": ["3000", "3000", "3000"],
    "493": ["1100", "1100", "1100"],
}

# Balance sheet closing balances, natural sign (positive). 090 is the plug.
BS = {
    "2026-07": {"091": "50000", "610": "88200", "620": "7700", "630": "22800", "710": "189000", "711": "56700",
                "800": "38900", "820": "11900", "825": "9700", "826": "3075", "830": "6450", "840": "18100",
                "900": "73850", "960": "165000", "970": "10000"},
    "2026-08": {"091": "50000", "610": "96400", "620": "6600", "630": "24300", "710": "189000", "711": "59850",
                "800": "41200", "820": "12480", "825": "9850", "826": "6150", "830": "7900", "840": "18600",
                "900": "72400", "960": "165000", "970": "10000"},
    "2026-09": {"091": "50000", "610": "118800", "620": "5500", "630": "27900", "710": "189000", "711": "63000",
                "800": "47950", "820": "15320", "825": "9980", "826": "9205", "830": "14350", "840": "19150",
                "900": "70950", "960": "165000", "970": "10000"},
}
CONTRA_ASSETS = {"711"}  # credit-balance asset accounts
MONTH_END = {"2026-07": "2026-07-31", "2026-08": "2026-08-31", "2026-09": "2026-09-30"}


def is_pl(code: str) -> bool:
    return CLASS[code] in ("REVENUE", "EXPENSE")


def debit_sign(code: str) -> int:
    """+1 if the account's natural balance is a debit."""
    if code in CONTRA_ASSETS:
        return -1
    return 1 if CLASS[code] in ("ASSET", "EXPENSE") else -1


def ytd_profit(upto: int) -> Decimal:
    total = D(0)
    for code, values in PL_ACTUAL.items():
        amount = sum(D(v) for v in values[: upto + 1])
        total += amount if CLASS[code] == "REVENUE" else -amount
    return total


def signed_closing(month: str) -> dict[str, Decimal]:
    """Signed (debit +) closing balances for BS accounts with the cash plug solved."""
    idx = MONTHS.index(month)
    signed = {code: D(v) * debit_sign(code) for code, v in BS[month].items()}
    # assets + liabilities + equity (signed) + current-year earnings (credit => negative) == 0
    signed["090"] = -(sum(signed.values()) - ytd_profit(idx))
    return signed


# --------------------------------------------------------------------------- Xero shapes

def money(value: Decimal) -> str:
    return f"{value:.2f}"


def trial_balance_report(month: str) -> dict:
    idx = MONTHS.index(month)
    closing = signed_closing(month)
    prior = signed_closing(MONTHS[idx - 1]) if idx > 0 else None
    sections: dict[str, list] = {"Revenue": [], "Expenses": [], "Assets": [], "Liabilities": [], "Equity": []}
    section_for = {"REVENUE": "Revenue", "EXPENSE": "Expenses", "ASSET": "Assets", "LIABILITY": "Liabilities", "EQUITY": "Equity"}
    for code, name, _, cls in ACCOUNTS:
        if is_pl(code):
            month_signed = D(PL_ACTUAL[code][idx]) * debit_sign(code)
            ytd_signed = sum(D(v) for v in PL_ACTUAL[code][: idx + 1]) * debit_sign(code)
        else:
            ytd_signed = closing[code]
            month_signed = closing[code] - (prior[code] if prior else D(0))
        if month_signed == 0 and ytd_signed == 0:
            continue

        def dc(v: Decimal) -> tuple[str, str]:
            return (money(v), "") if v > 0 else ("", money(-v)) if v < 0 else ("", "")

        md, mc = dc(month_signed)
        yd, yc = dc(ytd_signed)
        attrs = [{"Value": account_id(code), "Id": "account"}]
        sections[section_for[cls]].append({
            "RowType": "Row",
            "Cells": [
                {"Value": f"{name} ({code})", "Attributes": attrs},
                {"Value": md, "Attributes": attrs},
                {"Value": mc, "Attributes": attrs},
                {"Value": yd, "Attributes": attrs},
                {"Value": yc, "Attributes": attrs},
            ],
        })
    rows = [{"RowType": "Header", "Cells": [{"Value": "Account"}, {"Value": "Debit"}, {"Value": "Credit"},
                                            {"Value": "YTD Debit"}, {"Value": "YTD Credit"}]}]
    for title, section_rows in sections.items():
        rows.append({"RowType": "Section", "Title": title, "Rows": section_rows})
    end = MONTH_END[month]
    return {
        "Id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"tb/{end}")),
        "Status": "OK",
        "ProviderName": "monthend-agent fixtures",
        "Reports": [{
            "ReportID": "TrialBalance",
            "ReportName": "Trial Balance",
            "ReportType": "TrialBalance",
            "ReportTitles": ["Trial Balance", "Harbour Joinery Pty Ltd", f"As at {end}"],
            "ReportDate": end,
            "UpdatedDateUTC": "/Date(1791763200000+0000)/",
            "Rows": rows,
        }],
    }


def budgets() -> dict:
    lines = []
    for code, values in PL_BUDGET.items():
        lines.append({
            "AccountID": account_id(code),
            "AccountCode": code,
            "BudgetBalances": [{"Period": m, "Amount": float(D(v)), "Notes": ""} for m, v in zip(MONTHS, values)],
        })
    return {"Budgets": [{
        "BudgetID": str(uuid.uuid5(uuid.NAMESPACE_URL, "budget/fy2027")),
        "Type": "OVERALL",
        "Description": "FY2027 Board approved budget",
        "Status": "ACTIVE",
        "BudgetLines": lines,
    }]}


def invoice(number, kind, contact, date, due, lines, status="AUTHORISED", amount_paid="0", reference=""):
    subtotal = sum(D(amount) for _, amount, _ in lines)
    tax = (subtotal * D("0.10")).quantize(D("0.01"))
    total = subtotal + tax
    return {
        "InvoiceID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"invoice/{number}")),
        "InvoiceNumber": number,
        "Reference": reference,
        "Type": kind,
        "Contact": {"ContactID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"contact/{contact}")), "Name": contact},
        "DateString": f"{date}T00:00:00",
        "DueDateString": f"{due}T00:00:00",
        "Status": status,
        "LineAmountTypes": "Exclusive",
        "LineItems": [{"Description": desc, "AccountCode": code, "LineAmount": float(D(amount)), "TaxType": "OUTPUT" if kind == "ACCREC" else "INPUT"}
                      for code, amount, desc in lines],
        "SubTotal": float(subtotal),
        "TotalTax": float(tax),
        "Total": float(total),
        "AmountPaid": float(D(amount_paid)),
        "AmountDue": float(total - D(amount_paid)),
        "CurrencyCode": "AUD",
    }


def invoices() -> dict:
    accrec = [
        invoice("INV-1042", "ACCREC", "Bayside Medical Centre", "2026-09-26", "2026-10-26",
                [("200", "60000", "Fitout stage 2 - joinery and partitions (per progress claim 2)")], reference="BMC-PC2"),
        invoice("INV-1039", "ACCREC", "Coastal Dental Group", "2026-09-12", "2026-10-12",
                [("200", "25000", "Surgery fitout - progress claim 1")]),
        invoice("INV-1035", "ACCREC", "Northside Cafe Co", "2026-08-28", "2026-09-27",
                [("200", "13500", "Counter and shelving fitout")]),
        invoice("INV-1027", "ACCREC", "Marina Apartments Body Corporate", "2026-07-30", "2026-08-29",
                [("210", "9500", "Lobby joinery - supply and install")]),
        invoice("INV-1040", "ACCREC", "Westend Physio", "2026-09-15", "2026-10-15",
                [("200", "97400", "Clinic fitout - practical completion")], status="PAID", amount_paid="107140"),
        invoice("INV-1041", "ACCREC", "Various retail customers", "2026-09-30", "2026-09-30",
                [("210", "21300", "Joinery product sales - September")], status="PAID", amount_paid="23430"),
    ]
    accpay = [
        invoice("TC-88790", "ACCPAY", "Timberco Pty Ltd", "2026-09-08", "2026-10-08",
                [("310", "28400", "Hardwood and board - general stock (incl. 8% price increase)")], status="PAID", amount_paid="31240"),
        invoice("TC-88801", "ACCPAY", "Timberco Pty Ltd", "2026-09-19", "2026-10-19",
                [("310", "19850", "Bayside Medical stage 2 - laminate and hardware")]),
        invoice("VS-0912", "ACCPAY", "Various suppliers", "2026-09-30", "2026-10-30",
                [("310", "6750", "Consumables and fixings - September")], status="PAID", amount_paid="7425"),
        invoice("SB-E2195", "ACCPAY", "Sparky Bros Electrical", "2026-09-10", "2026-10-10",
                [("320", "9800", "Westend Physio electrical - final")], status="PAID", amount_paid="10780"),
        invoice("FW-3318", "ACCPAY", "FormWorks Plastering", "2026-09-24", "2026-10-24",
                [("320", "15300", "Bayside Medical stage 2 - partitions and set")]),
        invoice("HI-5521", "ACCPAY", "Hire-It Equipment", "2026-09-14", "2026-10-14",
                [("466", "4600", "Scissor lift and access equipment hire - Bayside Medical, 14-30 Sep")]),
    ]
    return {"Invoices": accrec + accpay}


BANK_TXNS = [
    # id, type, contact, date, reference, total, reconciled, account, description
    ("BT-0915-01", "RECEIVE", "Westend Physio", "2026-09-18", "INV-1040", "107140.00", True, "200", "Receipt INV-1040"),
    ("BT-0915-02", "SPEND", "Timberco Pty Ltd", "2026-09-22", "TC-88790", "31240.00", True, "800", "Payment TC-88790"),
    ("BT-0915-03", "SPEND", "Harbour Joinery payroll", "2026-09-25", "PAY-0925", "41850.00", True, "477", "Fortnightly payroll"),
    ("BT-0930-01", "SPEND", "Sparky Bros Electrical", "2026-09-30", "SB-E2195", "6420.00", False, "800", "Part payment SB-E2195 (EFT 30 Sep)"),
    ("BT-0930-02", "RECEIVE", "Northside Cafe Co", "2026-09-30", "DEP-0930", "3300.00", False, "610", "Counter deposit - banked 1 Oct"),
]


def bank_transactions() -> dict:
    out = []
    for tid, kind, contact, date, ref, total, reconciled, code, desc in BANK_TXNS:
        out.append({
            "BankTransactionID": str(uuid.uuid5(uuid.NAMESPACE_URL, f"bank/{tid}")),
            "Type": kind,
            "Contact": {"Name": contact},
            "DateString": f"{date}T00:00:00",
            "Reference": ref,
            "IsReconciled": reconciled,
            "Status": "AUTHORISED",
            "BankAccount": {"AccountID": account_id("090"), "Code": "090", "Name": NAME["090"]},
            "LineItems": [{"Description": desc, "AccountCode": code, "LineAmount": float(D(total))}],
            "Total": float(D(total)),
            "CurrencyCode": "AUD",
        })
    return {"BankTransactions": out}


# --------------------------------------------------------------------------- documents

def fmt(value: Decimal) -> str:
    return f"{value:,.2f}"


def write_documents(base: Path) -> None:
    docs = base / "sharepoint" / "Clients" / "Harbour Joinery" / "2026-09"
    xero_bank = signed_closing("2026-09")["090"]
    # statement = ledger + unpresented payment - outstanding deposit - unrecorded bank fee
    statement_close = xero_bank + D("6420.00") - D("3300.00") - D("45.10")
    opening = signed_closing("2026-08")["090"]
    write_text_pdf(docs / "bank-statement-090-2026-09.pdf", [[
        "COASTAL MUTUAL BANK (fictional)            STATEMENT OF ACCOUNT",
        "Account name: Harbour Joinery Pty Ltd",
        "BSB 999-001  Account 0000 1234         Period 01/09/2026 - 30/09/2026",
        "",
        "Date        Description                          Debit        Credit",
        f"01/09/2026  Opening balance                                {fmt(opening):>12}",
        "18/09/2026  Westend Physio INV-1040                       107,140.00",
        "22/09/2026  Timberco Pty Ltd TC-88790        31,240.00",
        "25/09/2026  Payroll PAY-0925                 41,850.00",
        "30/09/2026  Account keeping and merchant fee     45.10",
        "            (other September activity summarised in Xero feed)",
        "",
        f"30/09/2026  Closing balance                                {fmt(statement_close):>12}",
    ]])

    accruals = [
        ("ACC-01", "Timberco Pty Ltd", "310", "September hardwood delivery not yet invoiced", "6850.00", "inv-timberco-T88812.pdf"),
        ("ACC-02", "Sparky Bros Electrical", "320", "Bayside Medical rough-in, September work", "3200.00", "inv-sparkybros-E2209.pdf"),
        ("ACC-03", "Pinnacle Audit & Advisory", "412", "FY2026 financial statements and tax return", "4300.00", "inv-pinnacle-PA-7781.pdf"),
    ]
    with (docs / "accruals-schedule-2026-09.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ref", "supplier", "account_code", "description", "amount_ex_gst", "support"])
        writer.writerows(accruals)

    write_text_pdf(docs / "inv-timberco-T88812.pdf", [[
        "TIMBERCO PTY LTD (fictional)                       TAX INVOICE",
        "Invoice number: T-88812             Invoice date: 03/10/2026",
        "Bill to: Harbour Joinery Pty Ltd",
        "",
        "Description                                         Amount",
        "Hardwood delivery 26-29 September 2026            6,850.00",
        "Subtotal (ex GST)                                 6,850.00",
        "GST                                                 685.00",
        "Total                                             7,535.00",
    ]])
    write_text_pdf(docs / "inv-sparkybros-E2209.pdf", [[
        "SPARKY BROS ELECTRICAL (fictional)                 TAX INVOICE",
        "Invoice number: E-2209              Invoice date: 05/10/2026",
        "Bill to: Harbour Joinery Pty Ltd",
        "",
        "Description                                         Amount",
        "Bayside Medical stage 2 rough-in (Sep 2026)       3,250.00",
        "Subtotal (ex GST)                                 3,250.00",
        "GST                                                 325.00",
        "Total                                             3,575.00",
    ]])
    write_text_pdf(docs / "inv-pinnacle-PA-7781.pdf", [[
        "PINNACLE AUDIT & ADVISORY (fictional)              TAX INVOICE",
        "Invoice number: PA-7781             Invoice date: 07/10/2026",
        "Bill to: Harbour Joinery Pty Ltd",
        "",
        "Description                                         Amount",
        "FY2026 financial statements and income tax return 4,300.00",
        "Subtotal (ex GST)                                 4,300.00",
        "GST                                                 430.00",
        "Total                                             4,730.00",
    ]])


MESSAGES = [
    {
        "id": "msg-bayside-0922",
        "receivedDateTime": "2026-09-22T09:14:00Z",
        "from": {"emailAddress": {"name": "Accounts - Bayside Medical Centre", "address": "accounts@baysidemedical.example"}},
        "subject": "Stage 2 progress claim - please invoice this month",
        "bodyPreview": "Hi team, our board approved bringing stage 2 forward. Please issue progress claim 2 in September rather than October so it lands in our current budget period.",
    },
    {
        "id": "msg-timberco-0820",
        "receivedDateTime": "2026-08-20T03:02:00Z",
        "from": {"emailAddress": {"name": "Timberco Sales", "address": "sales@timberco.example"}},
        "subject": "Price increase notice - effective 1 September 2026",
        "bodyPreview": "Please note an 8% increase on hardwood and board lines effective 1 September 2026 due to supply constraints.",
    },
    {
        "id": "msg-sparky-0917",
        "receivedDateTime": "2026-09-17T23:40:00Z",
        "from": {"emailAddress": {"name": "Sparky Bros Electrical", "address": "office@sparkybros.example"}},
        "subject": "Coastal Dental rough-in moved to 6 October",
        "bodyPreview": "Confirming the Coastal Dental electrical rough-in has moved to 6 October at the builder's request. September claim will only cover Westend final and Bayside works.",
    },
]


def main() -> None:
    xero = OUT / "xero"
    xero.mkdir(parents=True, exist_ok=True)

    def dump(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")

    dump(xero / "organisation.json", {"Organisations": [{
        "Name": "Harbour Joinery Pty Ltd", "LegalName": "Harbour Joinery Pty Ltd", "BaseCurrency": "AUD",
        "CountryCode": "AU", "FinancialYearEndDay": 30, "FinancialYearEndMonth": 6, "Timezone": "AUSWESTERNSTANDARDTIME",
    }]})
    dump(xero / "accounts.json", {"Accounts": [
        {"AccountID": account_id(c), "Code": c, "Name": n, "Type": t, "Class": cls, "Status": "ACTIVE"}
        for c, n, t, cls in ACCOUNTS
    ]})
    for month in ("2026-08", "2026-09"):
        dump(xero / f"trial-balance-{MONTH_END[month]}.json", trial_balance_report(month))
    dump(xero / "budgets.json", budgets())
    dump(xero / "invoices.json", invoices())
    dump(xero / "bank-transactions.json", bank_transactions())
    dump(OUT / "outlook" / "messages.json", {"value": MESSAGES})
    write_documents(OUT)

    cash = signed_closing("2026-09")["090"]
    print(f"Cash at bank (090) 30 Sep: {cash:,.2f}; YTD profit: {ytd_profit(2):,.2f}")
    for path in sorted(OUT.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            print(f"  {digest}  {path.relative_to(OUT)}")


if __name__ == "__main__":
    main()
