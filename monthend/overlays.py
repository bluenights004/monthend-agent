"""Controlled edits to a snapshot, used only by evaluation cases to plant known errors.

Each operation changes the raw source files the same way a real data problem would
(an unmapped account, a missing document, an out-of-balance ledger), so the whole
pipeline is exercised, not a mocked part of it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from monthend.money import dec


def _fmt(value: Decimal) -> tuple[str, str]:
    if value > 0:
        return f"{value:.2f}", ""
    if value < 0:
        return "", f"{-value:.2f}"
    return "", ""


def _adjust_tb(inputs: Path, which: str, code: str, name: str, section: str, month: Decimal, ytd: Decimal) -> None:
    path = inputs / f"trial-balance-{which}.json"
    data = json.loads(path.read_text())
    report = data["Reports"][0]
    for sec in report["Rows"]:
        for row in sec.get("Rows", []):
            if row.get("RowType") == "Row" and row["Cells"][0]["Value"].endswith(f"({code})"):
                cells = row["Cells"]
                new_month = dec(cells[1]["Value"]) - dec(cells[2]["Value"]) + month
                new_ytd = dec(cells[3]["Value"]) - dec(cells[4]["Value"]) + ytd
                cells[1]["Value"], cells[2]["Value"] = _fmt(new_month)
                cells[3]["Value"], cells[4]["Value"] = _fmt(new_ytd)
                path.write_text(json.dumps(data, indent=2))
                return
    target = next(s for s in report["Rows"] if s.get("RowType") == "Section" and s.get("Title") == section)
    md, mc = _fmt(month)
    yd, yc = _fmt(ytd)
    target["Rows"].append({"RowType": "Row", "Cells": [{"Value": f"{name} ({code})"}, {"Value": md}, {"Value": mc},
                                                       {"Value": yd}, {"Value": yc}]})
    path.write_text(json.dumps(data, indent=2))


def apply_overlays(inputs: Path, overlays: list[dict]) -> None:
    for op in overlays:
        kind = op["op"]
        if kind == "tb_adjust":
            _adjust_tb(inputs, op.get("which", "current"), op["code"], op.get("name", op["code"]), op.get("section", "Expenses"),
                       dec(op.get("month", "0")), dec(op.get("ytd", "0")))
        elif kind == "remove_document":
            (inputs / "documents" / op["filename"]).unlink()
        elif kind == "bank_txn_set":
            path = inputs / "bank-transactions.json"
            data = json.loads(path.read_text())
            for txn in data["BankTransactions"]:
                if txn.get("Reference") == op["reference"]:
                    txn[op["field"]] = op["value"]
            path.write_text(json.dumps(data, indent=2))
        elif kind == "remove_message":
            path = inputs / "messages.json"
            data = json.loads(path.read_text())
            data["value"] = [m for m in data["value"] if m["id"] != op["id"]]
            path.write_text(json.dumps(data, indent=2))
        else:
            raise ValueError(f"unknown overlay op {kind!r}")
