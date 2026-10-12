"""Variance context, the commentary schema, and the deterministic commentary validator.

The validator is the core of "how do we know the agent is wrong". It does not judge
style; it checks things that are either true or false:

- every material variance has commentary (coverage)
- every number in the text traces to the pack or to cited evidence (no invented figures)
- favourable/unfavourable and above/below budget match the sign of the variance
- every cited evidence id resolves, and each driver amount appears in its evidence
- hedged speculation is flagged so the reviewer knows what is not evidenced

It runs on every production run (before a pack can be submitted for review) and on
every evaluation case. The same function, so there is one definition of "correct".
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from monthend.evidence import EvidenceIndex
from monthend.money import ZERO, dec, q2
from monthend.pack import Pack, PackLine
from monthend.snapshot import SourceBundle
from monthend.sources.xero_parse import invoice_date

# --------------------------------------------------------------------------- schema


class Driver(BaseModel):
    description: str = Field(description="One factual clause naming the cause, e.g. 'Bayside Medical stage 2 invoiced in September'")
    amount: float | None = Field(description="The amount this driver contributed, exactly as it appears in the cited evidence; null if not quantifiable")
    evidence: list[str] = Field(description="Evidence ids from the variance context, e.g. 'xero:invoice:INV-1042' or 'email:msg-...'")


class CommentaryItem(BaseModel):
    line_key: str = Field(description="Pack line key, e.g. 'pl.rev.contract'")
    text: str = Field(description="2-4 sentences for a business owner. State actual, budget and variance, then the evidenced cause.")
    drivers: list[Driver]
    follow_up: list[str] = Field(default_factory=list, description="Questions for the client where the cause is not evidenced")


class Commentary(BaseModel):
    summary: str = Field(description="2-3 sentences on net profit against budget and the main reasons")
    items: list[CommentaryItem]
    author: str = Field(default="", description="Who drafted this: 'claude:<model>', 'claude-code:variance-analyst' or 'rules-baseline'")


# --------------------------------------------------------------------------- context

def variance_context(pack: Pack, bundle: SourceBundle, index: EvidenceIndex, line_key: str, period_key: str,
                     workpaper_rows: list[dict] | None = None) -> dict:
    """Everything a writer needs for one line, and nothing else. Agents get this via MCP."""
    line = pack.line(line_key)
    v = line.values
    current = {l.code: l for l in bundle.tb_current}
    accounts = []
    for code in line.accounts:
        tb = current.get(code)
        budget = bundle.budgets.get(code, {}).get(period_key, ZERO)
        actual = (-(tb.month) if line.nature == "income" else tb.month) if tb else ZERO
        accounts.append({"code": code, "name": tb.name if tb else "", "actual": str(q2(actual)), "budget": str(q2(budget)),
                         "variance": str(q2(actual - budget))})

    transactions = []
    for ev in index.for_accounts(line.accounts):
        if not ev.date.startswith(period_key):
            continue
        inv = next((i for i in bundle.invoices if f"xero:invoice:{i['InvoiceNumber']}" == ev.id), None)
        amount = sum((dec(li.get("LineAmount")) for li in (inv or {}).get("LineItems", []) if li.get("AccountCode") in line.accounts), ZERO)
        transactions.append({"evidence_id": ev.id, "title": ev.title, "date": ev.date, "amount_for_line": str(q2(amount)), "detail": ev.text})
    transactions.sort(key=lambda t: -abs(dec(t["amount_for_line"])))

    contacts = {t["title"].split(" ", 1)[1] for t in transactions if " " in t["title"]}
    words = [w for c in contacts for w in c.split()] + [w for w in line.label.split()]
    emails = [{"evidence_id": e.id, "date": e.date, "title": e.title, "text": e.text} for e in index.emails_mentioning(words)]

    related_wp = []
    for row in workpaper_rows or []:
        if any(f"account {code}" in row["description"] for code in line.accounts):
            related_wp.append(row)

    return {
        "line_key": line.key,
        "label": line.label,
        "nature": line.nature,
        "material": line.material,
        "materiality_reason": line.materiality_reason,
        "figures": {k: (str(q2(val)) if isinstance(val, Decimal) and not k.endswith("_pct") else (str(val) if val is not None else None))
                    for k, val in v.items()},
        "favourable": line.favourable,
        "direction": "above budget" if line.variance > 0 else "below budget" if line.variance < 0 else "on budget",
        "accounts": accounts,
        "transactions_this_period": transactions[:12],
        "related_emails": emails[:6],
        "related_workpaper_rows": related_wp,
        "currency": pack.currency,
    }


def workpaper_rows_for_context(papers) -> list[dict]:
    rows = []
    for paper in papers:
        for row in paper.rows:
            if row.kind == "item":
                rows.append({"evidence_id": f"wp:{paper.code}:{row.ref_no}", "description": row.description,
                             "amount": str(row.amount) if row.amount is not None else None, "note": row.note,
                             "source_refs": [r.evidence_id for r in row.refs]})
    return rows


# --------------------------------------------------------------------------- validation

@dataclass
class Issue:
    code: str
    severity: str  # block | warn | info
    message: str
    line_key: str = ""


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "block"]

    @property
    def ok(self) -> bool:
        return not self.blocking

    def to_json(self) -> dict:
        return {"ok": self.ok, "issues": [asdict(i) for i in self.issues], "metrics": self.metrics}


HEDGES = re.compile(r"\b(likely|probably|possibly|presumably|perhaps|may have been|might|appears to|seems to|we believe|we assume|assumed to)\b", re.I)
_IDS = re.compile(r"`[^`]*`|\b(?:xero|email|doc|wp):[^\s,;)]+|\b[A-Z]{1,5}-[A-Z]?\d+[A-Z0-9-]*\b")
_DATES = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{4})?\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b|\b(?:FY)?20\d{2}\b", re.I)
_NUMBER = re.compile(r"(?P<cur>\$|AUD|NZD|USD|GBP|SGD)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?(?P<suffix>%|k\b|K\b|m\b|million\b|thousand\b)?")

FAV = re.compile(r"(?<!un)\bfavourabl[ey]\b|(?<!un)\bfavorabl[ey]\b", re.I)
UNFAV = re.compile(r"\bunfavourabl[ey]\b|\bunfavorabl[ey]\b|\badverse(?:ly)?\b", re.I)
ABOVE = re.compile(r"\b(above|over|ahead of|higher than|exceed(?:ed|s)?|more than)\s+(?:the\s+)?budget", re.I)
BELOW = re.compile(r"\b(below|under|behind|lower than|less than|short of)\s+(?:the\s+)?budget", re.I)


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
OTHER_PERIOD = re.compile(r"\b(next|following|last|prior|previous) (month|quarter|year)\b|\byear[- ]to[- ]date\b|\bYTD\b|\bfull[- ]year\b", re.I)


def _current_period_text(text: str, period_label: str) -> str:
    """Sentences about the reporting month only.

    'October revenue will be lower than budget' is a statement about another period and
    must not be checked against September's variance sign.
    """
    this_month = period_label.split()[0].lower()
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        lower = sentence.lower()
        if OTHER_PERIOD.search(sentence) or any(m in lower for m in MONTHS if m != this_month):
            continue
        kept.append(sentence)
    return " ".join(kept)


@dataclass(frozen=True)
class NumberToken:
    value: Decimal
    tolerance: Decimal
    is_percent: bool
    raw: str


def numbers_in(text: str) -> list[NumberToken]:
    cleaned = _DATES.sub(" ", _IDS.sub(" ", text))
    tokens = []
    for m in _NUMBER.finditer(cleaned):
        num, suffix, cur = m["num"], (m["suffix"] or "").lower(), m["cur"]
        value = dec(num)
        decimals = len(num.split(".")[1]) if "." in num else 0
        step = Decimal(1).scaleb(-decimals)
        if suffix in ("k", "thousand"):
            value, step = value * 1000, step * 1000
        elif suffix in ("m", "million"):
            value, step = value * 1_000_000, step * 1_000_000
        is_percent = suffix == "%"
        # Small bare integers are counts ("stage 2", "4 days"), not figures.
        if not is_percent and not cur and not suffix and "," not in num and "." not in num and value < 100:
            continue
        tokens.append(NumberToken(value, step / 2 + Decimal("0.005"), is_percent, m.group().strip()))
    return tokens


def _line_figures(line: PackLine) -> tuple[set[Decimal], set[Decimal]]:
    money, pcts = set(), set()
    for key, value in line.values.items():
        if value is None:
            continue
        (pcts if key.endswith("_pct") else money).add(abs(value))
    return money, pcts


def _matches(token: NumberToken, candidates: set[Decimal]) -> bool:
    return any(abs(token.value - c) <= token.tolerance for c in candidates)


def validate_commentary(commentary: Commentary, pack: Pack, index: EvidenceIndex) -> ValidationReport:
    report = ValidationReport()
    lines = {l.key: l for l in pack.lines}
    material = [l for l in pack.lines if l.material]
    covered = {item.line_key for item in commentary.items}

    for line in material:
        if line.key not in covered:
            report.issues.append(Issue("MISSING_MATERIAL_LINE", "block",
                                       f"No commentary for material variance on '{line.label}' ({line.variance:,.0f}).", line.key))

    all_money: set[Decimal] = set()
    all_pct: set[Decimal] = set()
    for line in pack.lines:
        m, p = _line_figures(line)
        all_money |= m
        all_pct |= p

    number_total = number_traced = direction_checks = direction_ok = evidence_total = evidence_ok = 0
    explained_shares = []
    for item in commentary.items:
        line = lines.get(item.line_key)
        if line is None:
            report.issues.append(Issue("UNKNOWN_LINE", "block", f"Commentary refers to unknown pack line '{item.line_key}'.", item.line_key))
            continue
        if not line.material:
            report.issues.append(Issue("NON_MATERIAL_LINE", "info", f"Commentary on non-material line '{line.label}'.", line.key))

        money, pcts = _line_figures(line)
        cited_text_numbers: set[Decimal] = set()
        driver_amounts: set[Decimal] = set()
        for driver in item.drivers:
            if not driver.evidence:
                report.issues.append(Issue("DRIVER_NO_EVIDENCE", "block", f"Driver '{driver.description}' cites no evidence.", line.key))
            resolved = []
            for ev_id in driver.evidence:
                evidence_total += 1
                ev = index.resolve(ev_id)
                if ev is None:
                    report.issues.append(Issue("EVIDENCE_UNKNOWN", "block", f"Evidence '{ev_id}' does not exist in this run.", line.key))
                    continue
                evidence_ok += 1
                resolved.append(ev)
                cited_text_numbers |= {abs(a) for a in ev.amounts}
                cited_text_numbers |= {t.value for t in numbers_in(ev.text)}
            if driver.amount is not None:
                amount = dec(driver.amount)
                if resolved and not any(ev.supports_amount(amount) for ev in resolved):
                    report.issues.append(Issue("DRIVER_AMOUNT_UNSUPPORTED", "block",
                                               f"Driver amount {amount:,.2f} does not appear in its evidence ({', '.join(driver.evidence)}).", line.key))
                else:
                    driver_amounts.add(abs(amount))
        if line.variance != 0:
            explained = min(sum(driver_amounts, ZERO), abs(line.variance)) / abs(line.variance)
            explained_shares.append(float(explained))
            if line.material and explained < Decimal("0.5"):
                report.issues.append(Issue("DRIVERS_EXPLAIN_LITTLE", "warn",
                                           f"Quantified drivers explain {explained:.0%} of the variance on '{line.label}'.", line.key))

        allowed_money = money | all_money | cited_text_numbers | driver_amounts
        allowed_pct = pcts | all_pct | cited_text_numbers
        for token in numbers_in(item.text):
            number_total += 1
            if _matches(token, allowed_pct if token.is_percent else allowed_money):
                number_traced += 1
            else:
                report.issues.append(Issue("NUMBER_UNTRACEABLE", "block",
                                           f"'{token.raw}' in commentary on '{line.label}' does not match the pack or cited evidence.", line.key))

        if not any(_matches(t, {abs(line.variance)}) for t in numbers_in(item.text) if not t.is_percent) and line.variance != 0:
            report.issues.append(Issue("VARIANCE_NOT_STATED", "warn", f"Commentary on '{line.label}' does not state the variance amount.", line.key))

        checks = []
        current_text = _current_period_text(item.text, pack.period_label)
        if FAV.search(current_text):
            checks.append(("favourable", line.favourable is True))
        if UNFAV.search(current_text):
            checks.append(("unfavourable", line.favourable is False))
        if ABOVE.search(current_text):
            checks.append(("above budget", line.variance > 0))
        if BELOW.search(current_text):
            checks.append(("below budget", line.variance < 0))
        for word, ok in checks:
            direction_checks += 1
            direction_ok += ok
            if not ok:
                report.issues.append(Issue("DIRECTION_WRONG", "block",
                                           f"Commentary says '{word}' but '{line.label}' is {'favourable' if line.favourable else 'unfavourable'} "
                                           f"({line.variance:+,.0f}).", line.key))
        if hedge := HEDGES.search(item.text):
            severity = "info" if item.follow_up else "warn"
            report.issues.append(Issue("SPECULATIVE_LANGUAGE", severity,
                                       f"'{hedge.group()}' on '{line.label}': state the evidenced cause or move it to a follow-up question.", line.key))
        if len(item.text) > 900:
            report.issues.append(Issue("TOO_LONG", "warn", f"Commentary on '{line.label}' is {len(item.text)} characters; keep under 900.", line.key))

    if not commentary.summary.strip():
        report.issues.append(Issue("NO_SUMMARY", "block", "Commentary has no summary paragraph."))
    for token in numbers_in(commentary.summary):
        number_total += 1
        if _matches(token, all_pct if token.is_percent else all_money):
            number_traced += 1
        else:
            report.issues.append(Issue("NUMBER_UNTRACEABLE", "block", f"'{token.raw}' in the summary does not match any pack figure."))
    # The summary's first sentence is about net profit; check its direction words against net profit.
    net = pack.line("pl.net_profit")
    first = re.split(r"(?<=[.!?])\s+", _current_period_text(commentary.summary, pack.period_label))[0]
    net_ahead = re.compile(r"\b(ahead of|above|over|exceed(?:ed|s)?|better than)\s+(?:the\s+)?budget", re.I)
    net_behind = re.compile(r"\b(behind|below|under|short of|worse than)\s+(?:the\s+)?budget", re.I)
    for pattern, ok, word in ((net_ahead, net.variance > 0, "ahead of budget"), (net_behind, net.variance < 0, "behind budget")):
        if pattern.search(first):
            direction_checks += 1
            direction_ok += ok
            if not ok:
                report.issues.append(Issue("DIRECTION_WRONG", "block",
                                           f"Summary says net profit is {word} but the variance is {net.variance:+,.0f}."))

    report.metrics = {
        "material_lines": len(material),
        "material_covered": sum(1 for l in material if l.key in covered),
        "coverage": round(sum(1 for l in material if l.key in covered) / len(material), 4) if material else 1.0,
        "numbers_checked": number_total,
        "numbers_traced": number_traced,
        "numeric_faithfulness": round(number_traced / number_total, 4) if number_total else 1.0,
        "direction_checks": direction_checks,
        "direction_accuracy": round(direction_ok / direction_checks, 4) if direction_checks else 1.0,
        "evidence_citations": evidence_total,
        "evidence_valid": round(evidence_ok / evidence_total, 4) if evidence_total else 1.0,
        "mean_explained_share": round(sum(explained_shares) / len(explained_shares), 4) if explained_shares else 0.0,
    }
    return report


# --------------------------------------------------------------------------- baseline drafter

def _money(value: Decimal, currency: str) -> str:
    return f"{currency} {abs(value).quantize(Decimal(1), rounding=ROUND_HALF_UP):,.0f}"


def draft_rule_based(pack: Pack, contexts: dict[str, dict]) -> Commentary:
    """Deterministic baseline. Used offline and as the bar a model must beat in evaluation."""
    items = []
    for line in pack.material_lines():
        ctx = contexts[line.key]
        v = line.values
        direction = "favourable" if line.favourable else "unfavourable"
        pct_text = f" ({abs(v['month_var_pct'])}%)" if v.get("month_var_pct") is not None else ""
        article = "an" if direction.startswith("u") else "a"
        text = (f"{line.label} was {_money(v['month_actual'], pack.currency)} against a budget of "
                f"{_money(v['month_budget'], pack.currency)}, {article} {direction} variance of {_money(line.variance, pack.currency)}{pct_text}.")
        drivers = []
        top = ctx["transactions_this_period"][:1]
        for txn in top:
            amount = dec(txn["amount_for_line"])
            text += f" The largest item this month was {txn['title']} ({_money(amount, pack.currency)})."
            drivers.append(Driver(description=f"{txn['title']}", amount=float(amount), evidence=[txn["evidence_id"]]))
        if not drivers:
            for row in ctx["related_workpaper_rows"][:1]:
                drivers.append(Driver(description=row["description"], amount=float(dec(row["amount"])), evidence=[row["evidence_id"]]))
                text += f" This includes an accrual of {_money(dec(row['amount']), pack.currency)} ({row['description'].split(' - ')[0]})."
        items.append(CommentaryItem(line_key=line.key, text=text, drivers=drivers,
                                    follow_up=[] if drivers else [f"What caused the movement in {line.label.lower()}?"]))
    net = pack.line("pl.net_profit")
    summary = (f"Net profit before tax for {pack.period_label} was {_money(net.values['month_actual'], pack.currency)} against a budget of "
               f"{_money(net.values['month_budget'], pack.currency)}, {'ahead of' if net.variance > 0 else 'behind'} budget by "
               f"{_money(net.variance, pack.currency)}.")
    return Commentary(summary=summary, items=items, author="rules-baseline")


def load_commentary(path: Path) -> Commentary:
    return Commentary.model_validate_json(path.read_text())


def save_commentary(commentary: Commentary, path: Path) -> None:
    path.write_text(json.dumps(commentary.model_dump(), indent=2) + "\n")
