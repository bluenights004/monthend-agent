"""The commentary validator: the definition of 'correct' for drafted commentary."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from monthend.config import ROOT, Period, load_client
from monthend.evidence import EvidenceIndex
from monthend.pack import build_pack
from monthend.snapshot import load_bundle, write_inputs_manifest
from monthend.sources.backends import FixtureBackend
from monthend.variance import Commentary, numbers_in, validate_commentary
from monthend.workpapers import build_workpapers

GOLD = json.loads((ROOT / "evals" / "cases" / "base-clean.gold-commentary.json").read_text())


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    client, period = load_client("harbour-joinery"), Period.parse("2026-09")
    inputs = tmp_path_factory.mktemp("inputs")
    FixtureBackend().fetch(client, period, inputs)
    manifest = write_inputs_manifest(inputs)
    bundle = load_bundle(inputs)
    pack = build_pack(client, period, bundle, json.loads(client.mapping_path.read_text())["rows"])
    index = EvidenceIndex(bundle, manifest["files"])
    for paper in build_workpapers(client, period, bundle, index):
        pass
    return pack, index


def validate(setup, data):
    pack, index = setup
    return validate_commentary(Commentary.model_validate(data), pack, index)


def codes(report):
    return {i.code for i in report.issues}


def test_gold_commentary_passes(setup):
    report = validate(setup, GOLD)
    assert report.ok, [i.message for i in report.blocking]
    assert report.metrics["coverage"] == 1.0 and report.metrics["numeric_faithfulness"] == 1.0


def test_numbers_ignore_dates_ids_and_counts():
    tokens = numbers_in("INV-1042 dated 26 September 2026 for AUD 60,000, stage 2, 8% rise, FY2026 fee of $4.3k")
    assert [t.raw for t in tokens] == ["AUD 60,000", "8%", "$4.3k"]
    assert tokens[2].value == Decimal("4300")


def test_other_period_statements_are_not_direction_checked(setup):
    data = json.loads(json.dumps(GOLD))
    assert "October revenue will be correspondingly lower than budget" in data["items"][0]["text"]
    assert "DIRECTION_WRONG" not in codes(validate(setup, data))
    data["items"][0]["text"] = data["items"][0]["text"].replace("a favourable variance", "below budget, a variance")
    assert "DIRECTION_WRONG" in codes(validate(setup, data))


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d["items"][0].update(text=d["items"][0]["text"].replace("22,400", "24,200")), "NUMBER_UNTRACEABLE"),
    (lambda d: d["items"][1].update(text=d["items"][1]["text"].replace("an unfavourable", "a favourable")), "DIRECTION_WRONG"),
    (lambda d: d["items"].pop(3), "MISSING_MATERIAL_LINE"),
    (lambda d: d["items"][0]["drivers"][0].update(evidence=["email:does-not-exist"]), "EVIDENCE_UNKNOWN"),
    (lambda d: d["items"][0]["drivers"][0].update(amount=61000), "DRIVER_AMOUNT_UNSUPPORTED"),
    (lambda d: d.update(summary=d["summary"].replace("ahead of budget", "behind budget")), "DIRECTION_WRONG"),
])
def test_planted_defects_are_caught(setup, mutate, code):
    data = json.loads(json.dumps(GOLD))
    mutate(data)
    report = validate(setup, data)
    assert code in codes(report)
    assert not report.ok


def test_hedging_is_a_warning_not_a_block(setup):
    data = json.loads(json.dumps(GOLD))
    data["items"][4]["text"] += " This is probably a one-off."
    data["items"][4]["follow_up"] = []
    report = validate(setup, data)
    assert "SPECULATIVE_LANGUAGE" in codes(report) and report.ok
