"""Read source documents and pin every extracted figure to a location in the file.

A reference is only useful if a reviewer can open the document and find the number.
So each extracted amount carries a locator ("p1:L13" for PDFs, "r4:amount_ex_gst" for
CSVs) and the exact line text. `verify_reference` re-opens the document and checks
the figure is really there; the evaluation harness runs it on every reference.

Deterministic parsers handle the layouts we know. `monthend.llm.extract_invoice_with_claude`
handles unfamiliar layouts, and its output goes through the same grounding check.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from monthend.money import dec
from monthend.snapshot import Document

AMOUNT = re.compile(r"(?<![\w.])\(?-?\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})\)?(?![\w])")


@dataclass(frozen=True)
class Located:
    value: Decimal
    locator: str
    text: str


@dataclass(frozen=True)
class DocumentText:
    kind: str                      # "pdf" | "csv" | "text"
    pages: tuple[tuple[str, ...], ...]  # pdf/text: pages of lines
    rows: tuple[dict, ...]         # csv: rows as dicts


@lru_cache(maxsize=256)
def _read(path: str, sha256: str) -> DocumentText:  # sha256 in the key: a changed file is re-read
    file = Path(path)
    suffix = file.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(file))
        pages = tuple(tuple((page.extract_text() or "").splitlines()) for page in reader.pages)
        return DocumentText("pdf", pages, ())
    if suffix == ".csv":
        with file.open(newline="") as handle:
            rows = tuple(dict(r) for r in csv.DictReader(handle))
        return DocumentText("csv", (), rows)
    return DocumentText("text", (tuple(file.read_text(errors="replace").splitlines()),), ())


def read_document(doc: Document) -> DocumentText:
    return _read(str(doc.path), doc.sha256)


def text_at(doc: Document, locator: str) -> str | None:
    content = read_document(doc)
    if content.kind == "csv":
        match = re.fullmatch(r"r(\d+):(\w+)", locator)
        if not match:
            return None
        row = int(match[1]) - 1
        return content.rows[row].get(match[2]) if 0 <= row < len(content.rows) else None
    match = re.fullmatch(r"p(\d+):L(\d+)", locator)
    if not match:
        return None
    page, line = int(match[1]) - 1, int(match[2]) - 1
    if 0 <= page < len(content.pages) and 0 <= line < len(content.pages[page]):
        return content.pages[page][line]
    return None


def amounts_in(text: str) -> list[Decimal]:
    return [dec(m.group()) for m in AMOUNT.finditer(text)]


def verify_reference(doc: Document | None, locator: str, amount: Decimal | None, sha256_prefix: str = "") -> str | None:
    """Return None if the reference holds up, otherwise a reason it does not."""
    if doc is None:
        return "document not in snapshot"
    if sha256_prefix and not doc.sha256.startswith(sha256_prefix):
        return f"document hash {doc.short_hash} does not match reference {sha256_prefix}"
    text = text_at(doc, locator)
    if text is None:
        return f"locator {locator} not found in {doc.filename}"
    if amount is not None:
        found = amounts_in(text) if read_document(doc).kind != "csv" else [dec(text)]
        if not any(abs(abs(v) - abs(amount)) < Decimal("0.005") for v in found):
            return f"{amount} not found at {doc.filename} {locator} (text: {text.strip()[:80]!r})"
    return None


def locate_amount(doc: Document, amount: Decimal, near: str = "") -> Located | None:
    """First line containing `amount` (and `near`, case-insensitive, if given)."""
    content = read_document(doc)
    for p, lines in enumerate(content.pages, start=1):
        for i, line in enumerate(lines, start=1):
            if near and near.lower() not in line.lower():
                continue
            if any(abs(abs(v) - abs(amount)) < Decimal("0.005") for v in amounts_in(line)):
                return Located(amount, f"p{p}:L{i}", line.strip())
    return None


# --------------------------------------------------------------------------- bank statements

@dataclass(frozen=True)
class StatementLine:
    date: str
    description: str
    debit: Decimal
    credit: Decimal
    locator: str
    text: str


@dataclass(frozen=True)
class Statement:
    closing: Located | None
    opening: Located | None
    lines: tuple[StatementLine, ...]


_STATEMENT_ROW = re.compile(r"^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<rest>.*)$")


def parse_bank_statement(doc: Document) -> Statement:
    """Read date/description/debit/credit rows. Column is inferred from position of the amount."""
    content = read_document(doc)
    closing = opening = None
    lines: list[StatementLine] = []
    header_debit_col = None
    for p, page in enumerate(content.pages, start=1):
        for i, raw in enumerate(page, start=1):
            if "Debit" in raw and "Credit" in raw:
                header_debit_col = raw.index("Debit")
            match = _STATEMENT_ROW.match(raw)
            if not match:
                continue
            found = list(AMOUNT.finditer(raw))
            if not found:
                continue
            locator = f"p{p}:L{i}"
            label = raw.lower()
            if "closing balance" in label:
                closing = Located(dec(found[-1].group()), locator, raw.strip())
                continue
            if "opening balance" in label:
                opening = Located(dec(found[-1].group()), locator, raw.strip())
                continue
            amount_match = found[-1]
            amount = dec(amount_match.group())
            # Amounts that end before the Credit column are debits.
            is_debit = header_debit_col is not None and amount_match.end() <= header_debit_col + len("Debit") + 4
            description = raw[match.start("rest"):amount_match.start()].strip()
            lines.append(StatementLine(match["date"], description, amount if is_debit else Decimal(0),
                                       Decimal(0) if is_debit else amount, locator, raw.strip()))
    return Statement(closing, opening, tuple(lines))


# --------------------------------------------------------------------------- supplier invoices

@dataclass(frozen=True)
class ExtractedInvoice:
    supplier: str
    invoice_number: Located | None
    invoice_date: Located | None
    subtotal: Located | None
    tax: Located | None
    total: Located | None
    method: str

    def arithmetic_ok(self) -> bool:
        if not (self.subtotal and self.tax and self.total):
            return False
        return abs(self.subtotal.value + self.tax.value - self.total.value) < Decimal("0.01")


def parse_invoice(doc: Document) -> ExtractedInvoice:
    content = read_document(doc)
    found: dict[str, Located] = {}
    supplier = ""
    for p, page in enumerate(content.pages, start=1):
        for i, raw in enumerate(page, start=1):
            loc = f"p{p}:L{i}"
            line = raw.strip()
            if p == 1 and i == 1:
                supplier = re.split(r"\s{2,}", line)[0].replace("(fictional)", "").strip()
            if m := re.search(r"Invoice number:\s*(\S+)", line):
                found["number"] = Located(Decimal(0), loc, m[1])
            if m := re.search(r"Invoice date:\s*(\d{2}/\d{2}/\d{4})", line):
                found["date"] = Located(Decimal(0), loc, m[1])
            amounts = amounts_in(line)
            if not amounts:
                continue
            lower = line.lower()
            if lower.startswith("subtotal"):
                found["subtotal"] = Located(amounts[-1], loc, line)
            elif lower.startswith("gst") or lower.startswith("tax"):
                found["tax"] = Located(amounts[-1], loc, line)
            elif lower.startswith("total"):
                found["total"] = Located(amounts[-1], loc, line)
    return ExtractedInvoice(supplier, found.get("number"), found.get("date"), found.get("subtotal"),
                            found.get("tax"), found.get("total"), method="rules")
