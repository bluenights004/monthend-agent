"""One addressable index of everything a workpaper or a commentary line may cite.

Evidence ids are stable, human-readable and checkable:

    xero:tb:090                       trial balance line for account 090
    xero:invoice:INV-1042             sales invoice or supplier bill
    xero:banktxn:BT-0930-01           bank transaction (by Reference, else id)
    email:msg-bayside-0922            Outlook message (subject + preview)
    doc:bank-statement-090-2026-09#p1:L13   a line in a source document
    doc:accruals-schedule-2026-09#r3:amount_ex_gst  a CSV cell
    wp:B1:B1.3                        a workpaper row

`EvidenceIndex.resolve` returns the evidence or None. Nothing is cited that cannot
be resolved, and the evaluation harness re-resolves every citation independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from monthend.extraction import amounts_in, read_document, text_at
from monthend.money import dec
from monthend.snapshot import SourceBundle
from monthend.sources.xero_parse import invoice_date

_DOC_REF = re.compile(r"^doc:(?P<doc>[^#]+)#(?P<loc>.+)$")


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    title: str
    text: str
    amounts: tuple[Decimal, ...] = ()
    date: str = ""
    source_hash: str = ""
    extra: dict = field(default_factory=dict, compare=False, hash=False)

    def supports_amount(self, amount: Decimal, tolerance: Decimal = Decimal("0.5")) -> bool:
        return any(abs(abs(a) - abs(amount)) <= tolerance for a in self.amounts)


class EvidenceIndex:
    def __init__(self, bundle: SourceBundle, input_hashes: dict[str, str] | None = None):
        self.bundle = bundle
        self.hashes = input_hashes or {}
        self.items: dict[str, Evidence] = {}
        self._build()

    def _build(self) -> None:
        tb_hash = self.hashes.get("trial-balance-current.json", "")[:12]
        for line in self.bundle.tb_current:
            self._add(Evidence(f"xero:tb:{line.code}", "trial_balance", f"{line.code} {line.name}",
                               f"Month movement {line.month:,.2f}; YTD/closing {line.ytd:,.2f}",
                               (line.month, line.ytd), source_hash=tb_hash, extra={"code": line.code}))
        inv_hash = self.hashes.get("invoices.json", "")[:12]
        for inv in self.bundle.invoices:
            lines = "; ".join(f"{li.get('Description', '')} [{li.get('AccountCode', '')}] {dec(li.get('LineAmount')):,.2f}"
                              for li in inv.get("LineItems", []))
            kind = "sales_invoice" if inv.get("Type") == "ACCREC" else "supplier_bill"
            when = invoice_date(inv)
            amounts = (dec(inv.get("SubTotal")), dec(inv.get("Total")), dec(inv.get("AmountDue")),
                       *(dec(li.get("LineAmount")) for li in inv.get("LineItems", [])))
            self._add(Evidence(f"xero:invoice:{inv['InvoiceNumber']}", kind,
                               f"{inv['InvoiceNumber']} {inv['Contact']['Name']}",
                               f"{inv.get('Type')} dated {when}; {lines}; subtotal {dec(inv.get('SubTotal')):,.2f}, "
                               f"total {dec(inv.get('Total')):,.2f}, due {dec(inv.get('AmountDue')):,.2f}; status {inv.get('Status')}",
                               amounts, date=str(when or ""), source_hash=inv_hash,
                               extra={"accounts": [li.get("AccountCode") for li in inv.get("LineItems", [])],
                                      "contact": inv["Contact"]["Name"], "type": inv.get("Type")}))
        bank_hash = self.hashes.get("bank-transactions.json", "")[:12]
        for txn in self.bundle.bank_transactions:
            ref = txn.get("Reference") or txn["BankTransactionID"]
            when = invoice_date(txn)
            self._add(Evidence(f"xero:banktxn:{ref}", "bank_transaction", f"{txn.get('Type')} {txn['Contact']['Name']} {ref}",
                               f"{txn.get('Type')} {dec(txn.get('Total')):,.2f} on {when}; reconciled={txn.get('IsReconciled')}",
                               (dec(txn.get("Total")),), date=str(when or ""), source_hash=bank_hash,
                               extra={"reconciled": bool(txn.get("IsReconciled")), "type": txn.get("Type"),
                                      "contact": txn["Contact"]["Name"], "id": txn["BankTransactionID"]}))
        mail_hash = self.hashes.get("messages.json", "")[:12]
        for msg in self.bundle.messages:
            sender = msg.get("from", {}).get("emailAddress", {})
            text = f"{msg.get('subject', '')}. {msg.get('bodyPreview', '')}"
            self._add(Evidence(f"email:{msg['id']}", "email", f"{msg.get('subject', '')} ({sender.get('name', '')})",
                               text, tuple(amounts_in(text)), date=msg.get("receivedDateTime", "")[:10],
                               source_hash=mail_hash, extra={"sender": sender.get("address", "")}))

    def _add(self, evidence: Evidence) -> None:
        self.items[evidence.id] = evidence

    def add_workpaper_row(self, wp_code: str, ref_no: str, description: str, amount: Decimal | None) -> None:
        self._add(Evidence(f"wp:{wp_code}:{ref_no}", "workpaper", f"{wp_code} {ref_no} {description}", description,
                           (amount,) if amount is not None else ()))

    def resolve(self, evidence_id: str) -> Evidence | None:
        if evidence_id in self.items:
            return self.items[evidence_id]
        match = _DOC_REF.match(evidence_id)
        if not match:
            return None
        doc = self.bundle.documents.get(match["doc"])
        if doc is None:
            return None
        text = text_at(doc, match["loc"])
        if text is None:
            return None
        amounts = (dec(text),) if read_document(doc).kind == "csv" and _is_amount(text) else tuple(amounts_in(text))
        return Evidence(evidence_id, "document", f"{doc.filename} {match['loc']}", text.strip(), amounts,
                        source_hash=doc.short_hash)

    def for_accounts(self, codes: list[str]) -> list[Evidence]:
        return [e for e in self.items.values()
                if e.kind in ("sales_invoice", "supplier_bill") and set(e.extra.get("accounts", [])) & set(codes)]

    def emails_mentioning(self, words: list[str]) -> list[Evidence]:
        words = [w.lower() for w in words if len(w) > 3]
        return [e for e in self.items.values() if e.kind == "email" and any(w in e.text.lower() or w in e.title.lower() for w in words)]


def _is_amount(text: str) -> bool:
    try:
        dec(text)
        return True
    except ValueError:
        return False
