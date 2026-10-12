"""Unit tests for the accounting core: parsing, mapping, pack arithmetic, workpapers, references."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from monthend.config import Period, load_client
from monthend.evidence import EvidenceIndex
from monthend.extraction import parse_bank_statement, parse_invoice, verify_reference
from monthend.money import dec, pct
from monthend.pack import build_pack, map_accounts, read_pack_xlsx, write_pack_xlsx
from monthend.snapshot import load_bundle, verify_inputs, write_inputs_manifest
from monthend.sources.backends import FixtureBackend
from monthend.sources.xero_parse import parse_trial_balance, parse_xero_date, tb_imbalance
from monthend.workpapers import build_workpapers


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory):
    client = load_client("harbour-joinery")
    period = Period.parse("2026-09")
    inputs = tmp_path_factory.mktemp("inputs")
    FixtureBackend().fetch(client, period, inputs)
    manifest = write_inputs_manifest(inputs)
    bundle = load_bundle(inputs)
    pack = build_pack(client, period, bundle, json.loads(client.mapping_path.read_text())["rows"])
    index = EvidenceIndex(bundle, manifest["files"])
    papers = build_workpapers(client, period, bundle, index)
    return {"client": client, "period": period, "inputs": inputs, "bundle": bundle, "pack": pack, "index": index, "papers": papers}


def test_money_parsing_never_uses_binary_floats():
    assert dec(0.1) + dec(0.2) == Decimal("0.3")
    assert dec("(1,234.50)") == Decimal("-1234.50")
    assert pct(Decimal("22400"), Decimal("160000")) == Decimal("14.0")
    assert pct(Decimal("1"), Decimal("0")) is None


def test_xero_dates_both_formats():
    assert str(parse_xero_date("/Date(1727654400000+0000)/")) == "2024-09-30"
    assert str(parse_xero_date("2026-09-26T00:00:00")) == "2026-09-26"


def test_trial_balance_parses_and_balances(snapshot):
    lines = snapshot["bundle"].tb_current
    assert tb_imbalance(lines) == 0
    cash = next(l for l in lines if l.code == "090")
    assert cash.ytd == Decimal("44772.50")


def test_trial_balance_rejects_unreadable_account_cell():
    payload = {"Reports": [{"ReportID": "TrialBalance", "Rows": [
        {"RowType": "Header", "Cells": [{"Value": v} for v in ("Account", "Debit", "Credit", "YTD Debit", "YTD Credit")]},
        {"RowType": "Section", "Title": "Revenue", "Rows": [{"RowType": "Row", "Cells": [{"Value": "Sales"}, {"Value": ""}, {"Value": "1"}, {"Value": ""}, {"Value": "1"}]}]},
    ]}]}
    with pytest.raises(ValueError, match="account code"):
        parse_trial_balance(payload)


def test_mapping_explicit_beats_range_and_unmapped_blocks():
    rows = [{"key": "pl.a", "type": "line", "accounts": ["400"], "ranges": [["400", "499"]]},
            {"key": "pl.b", "type": "line", "accounts": [], "ranges": [["450", "499"]]}]
    mapping, checks = map_accounts(rows, ["400", "466", "SUSP"])
    assert mapping["400"] == "pl.a"
    assert mapping["466"] == "pl.a"  # first range wins
    codes = {c.code for c in checks}
    assert codes == {"MAP_FALLBACK", "MAP_MISSING"}
    assert next(c for c in checks if c.code == "MAP_MISSING").severity == "block"


def test_pack_figures_and_integrity(snapshot):
    pack = snapshot["pack"]
    assert not pack.blocking
    net = pack.line("pl.net_profit").values
    assert net["month_actual"] == Decimal("14434.50")
    assert net["month_var"] == Decimal("9352.00")
    assert pack.line("bs.net_assets").values["closing"] == pack.line("bs.total_equity").values["closing"]
    assert pack.line("bs.current_earnings").values["closing"] == net["ytd_actual"]
    contract = pack.line("pl.rev.contract")
    assert contract.material and contract.favourable is True
    materials = pack.line("pl.cos.materials")
    assert materials.material and materials.favourable is False
    assert not pack.line("pl.opex.motor").material  # 950 is under the 2,000 floor


def test_excel_round_trip_by_keys(snapshot, tmp_path):
    out = tmp_path / "pack.xlsx"
    write_pack_xlsx(snapshot["pack"], snapshot["client"].template_path, out, meta={"run_id": "t"})
    cells = read_pack_xlsx(out)
    assert cells["pl.rev.contract"]["month_var"] == 22400
    assert cells["pl.rev.contract"]["month_var_pct"] == pytest.approx(0.14)
    assert cells["bs.receivables"]["closing"] == 118800


def test_bank_statement_parsing(snapshot):
    doc = snapshot["bundle"].document_by_filename("bank-statement-090-2026-09.pdf")
    statement = parse_bank_statement(doc)
    assert statement.closing.value == Decimal("47847.40")
    fee = next(l for l in statement.lines if "fee" in l.description.lower())
    assert fee.debit == Decimal("45.10") and fee.credit == 0
    receipt = next(l for l in statement.lines if "INV-1040" in l.description)
    assert receipt.credit == Decimal("107140.00")


def test_invoice_extraction_and_arithmetic(snapshot):
    invoice = parse_invoice(snapshot["bundle"].documents["inv-sparkybros-E2209"])
    assert invoice.invoice_number.text == "E-2209"
    assert invoice.subtotal.value == Decimal("3250.00")
    assert invoice.arithmetic_ok()


def test_workpapers_tie_and_flag(snapshot):
    papers = {p.code: p for p in snapshot["papers"]}
    a1 = papers["A1"]
    assert a1.rows[-1].description == "Unexplained difference" and a1.rows[-1].amount == 0
    assert {i.code for i in a1.issues} == {"BANKREC_UNRECORDED_ITEMS"}
    b1 = papers["B1"]
    assert b1.tie == {"tb": "14350.00", "workpaper": "14350.00"}
    assert "50.00 different" in b1.rows[1].note  # Sparky accrual vs invoice, under tolerance
    c1 = papers["C1"]
    assert c1.tie["workpaper"] == c1.tie["tb"] == "118800.00"
    assert any(i.code == "RECEIVABLE_AGED" for i in c1.issues)


def test_every_document_reference_resolves_to_the_figure(snapshot):
    docs = snapshot["bundle"].documents
    checked = 0
    for paper in snapshot["papers"]:
        for row in paper.rows:
            for ref in row.refs[:1]:
                if ref.evidence_id.startswith("doc:") and row.amount is not None:
                    doc_id, locator = ref.evidence_id[4:].split("#")
                    assert verify_reference(docs[doc_id], locator, row.amount, ref.source_hash) is None
                    checked += 1
    assert checked >= 5


def test_reference_check_catches_wrong_figure_and_changed_file(snapshot):
    doc = snapshot["bundle"].documents["inv-timberco-T88812"]
    assert verify_reference(doc, "p1:L6", Decimal("6850.00")) is None
    assert "not found" in verify_reference(doc, "p1:L6", Decimal("6580.00"))
    assert "does not match" in verify_reference(doc, "p1:L6", Decimal("6850.00"), "000000000000")


def test_snapshot_tamper_detection(snapshot, tmp_path):
    import shutil

    copy = tmp_path / "inputs"
    shutil.copytree(snapshot["inputs"], copy)
    assert verify_inputs(copy) == []
    (copy / "budgets.json").write_text("{}")
    assert verify_inputs(copy) == ["budgets.json: changed since snapshot"]
