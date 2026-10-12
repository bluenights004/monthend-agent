"""Evaluation harness: is the output *correct*, not just produced?

Three layers, each answering a different question:

1. Golden cases (evals/cases/*.json). The real pipeline runs on the synthetic client
   with planted problems (unmapped account, out-of-balance ledger, missing statement,
   unexplained bank difference...). We grade the *files it produced*: Excel cells read
   back from pack.xlsx, workpaper references re-resolved against the snapshot, the
   state the run ended in, and which checks fired. Expected values are hand-derived
   from the fixture inputs, not copied from the code's output.

2. Commentary quality against reviewer labels. For each material line, a reviewer
   recorded which evidence explains it (driver groups) and the correct direction.
   Driver recall measures whether the draft found the real cause; forbidden phrases
   catch claims the evidence does not support (hallucination probes). An optional
   LLM judge adds rubric scores for readability and proportion.

3. Validator mutation testing. The deterministic validator is itself tested: a
   reviewer-approved commentary must pass cleanly, and each planted defect (wrong
   number, flipped direction, invented evidence...) must be caught. If the checker
   cannot catch these, its "pass" on a model's draft means nothing.

Run: `monthend eval` (offline, rule-based drafts) or `monthend eval --engine claude`.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from monthend.config import ROOT
from monthend.evidence import EvidenceIndex
from monthend.extraction import verify_reference
from monthend.pack import read_pack_xlsx
from monthend.snapshot import load_bundle
from monthend.store import Store
from monthend.variance import Commentary, validate_commentary

CASES = ROOT / "evals" / "cases"
REPORTS = ROOT / "evals" / "reports"


@contextmanager
def isolated_var():
    """Each case gets its own database and run folder; production state is never touched."""
    previous = os.environ.get("MONTHEND_VAR_DIR")
    with tempfile.TemporaryDirectory(prefix="monthend-eval-") as tmp:
        os.environ["MONTHEND_VAR_DIR"] = tmp
        try:
            yield Path(tmp)
        finally:
            if previous is None:
                os.environ.pop("MONTHEND_VAR_DIR", None)
            else:
                os.environ["MONTHEND_VAR_DIR"] = previous


def load_cases(only: list[str] | None = None) -> list[dict]:
    cases = [json.loads(p.read_text()) for p in sorted(CASES.glob("*.json")) if not p.name.endswith("gold-commentary.json")]
    return [c for c in cases if not only or c["id"] in only]


# --------------------------------------------------------------------------- graders

def grade_pack(xlsx: Path, expected: dict) -> dict:
    cells = read_pack_xlsx(xlsx)
    total = correct = 0
    misses = []
    for key, columns in expected.items():
        for column, value in columns.items():
            total += 1
            got = (cells.get(key) or {}).get(column)
            if got is not None and abs(Decimal(str(got)) - Decimal(str(value))) < Decimal("0.005"):
                correct += 1
            else:
                misses.append(f"{key}.{column}: expected {value}, got {got}")
    return {"cells": total, "correct": correct, "misses": misses}


def grade_references(run_dir: Path, papers: list[dict]) -> dict:
    """Re-resolve every workpaper reference against a freshly loaded snapshot."""
    bundle = load_bundle(run_dir / "inputs")
    manifest = json.loads((run_dir / "inputs" / "inputs-manifest.json").read_text())
    index = EvidenceIndex(bundle, manifest["files"])
    total = ok = 0
    failures = []
    for paper in papers:
        for row in paper["rows"]:
            for n, ref in enumerate(row["refs"]):
                total += 1
                ev_id = ref["evidence_id"]
                if ev_id.startswith("doc:"):
                    doc_id, locator = ev_id[4:].split("#", 1)
                    # The first reference on an amount row must contain that amount at the locator.
                    amount = Decimal(row["amount"]) if (n == 0 and row["amount"] is not None and locator.startswith(("p", "r"))
                                                        and not locator.endswith("L2")) else None
                    problem = verify_reference(bundle.documents.get(doc_id), locator, amount, ref["source_hash"])
                else:
                    problem = None if index.resolve(ev_id) else f"{ev_id} does not resolve"
                if problem:
                    failures.append(f"{paper['code']} {row['ref_no']}: {problem}")
                else:
                    ok += 1
    return {"references": total, "resolved": ok, "failures": failures}


def grade_labels(commentary: Commentary, labels: dict) -> dict:
    groups = hits = forbidden = direction_total = direction_ok = 0
    details = []
    items = {i.line_key: i for i in commentary.items}
    for line_key, label in labels.items():
        item = items.get(line_key)
        cited = {ev for d in (item.drivers if item else []) for ev in d.evidence}
        for group in label.get("driver_groups", []):
            groups += 1
            if cited & set(group):
                hits += 1
            else:
                details.append(f"{line_key}: missed driver {group[0]}")
        for phrase in label.get("forbidden_phrases", []):
            if item and phrase.lower() in item.text.lower():
                forbidden += 1
                details.append(f"{line_key}: unsupported claim '{phrase}'")
        if item and "favourable" in label:
            direction_total += 1
            text = item.text.lower()
            says_fav = "favourable" in text.replace("unfavourable", "")
            says_unfav = "unfavourable" in text or "adverse" in text
            if (label["favourable"] and says_fav and not says_unfav) or (not label["favourable"] and says_unfav):
                direction_ok += 1
            elif says_fav or says_unfav:
                details.append(f"{line_key}: direction wording disagrees with label")
            else:
                direction_ok += 1  # no direction stated; the validator flags missing figures separately
    return {"driver_groups": groups, "driver_hits": hits, "forbidden_claims": forbidden,
            "label_direction_checks": direction_total, "label_direction_ok": direction_ok, "details": details}


# --------------------------------------------------------------------------- validator mutation testing

def _mutations(gold: dict) -> list[tuple[str, str, dict]]:
    """(name, issue code that must be raised, mutated commentary)."""
    out = []

    def mutate(name: str, code: str, fn) -> None:
        data = copy.deepcopy(gold)
        fn(data)
        out.append((name, code, data))

    mutate("changed figure in text", "NUMBER_UNTRACEABLE",
           lambda d: d["items"][0].update(text=d["items"][0]["text"].replace("22,400", "24,200")))
    mutate("flipped direction", "DIRECTION_WRONG",
           lambda d: d["items"][1].update(text=d["items"][1]["text"].replace("an unfavourable", "a favourable")))
    mutate("dropped a material line", "MISSING_MATERIAL_LINE", lambda d: d["items"].pop(2))
    mutate("invented evidence id", "EVIDENCE_UNKNOWN",
           lambda d: d["items"][0]["drivers"][0].update(evidence=["xero:invoice:INV-9999"]))
    mutate("driver amount not in evidence", "DRIVER_AMOUNT_UNSUPPORTED",
           lambda d: d["items"][0]["drivers"][0].update(amount=65000))
    mutate("driver without evidence", "DRIVER_NO_EVIDENCE", lambda d: d["items"][4]["drivers"][0].update(evidence=[]))
    mutate("unknown pack line", "UNKNOWN_LINE", lambda d: d["items"].append({**d["items"][0], "line_key": "pl.rev.imaginary"}))
    mutate("wrong summary figure", "NUMBER_UNTRACEABLE",
           lambda d: d.update(summary=d["summary"].replace("9,352", "9,532")))
    mutate("hedged speculation", "SPECULATIVE_LANGUAGE",
           lambda d: d["items"][4].update(text=d["items"][4]["text"] + " This is probably a one-off.", follow_up=[]))
    mutate("inflated rounded figure", "NUMBER_UNTRACEABLE",
           lambda d: d["items"][1].update(text=d["items"][1]["text"].replace("AUD 61,850", "AUD 70k")))
    mutate("wrong direction in summary", "DIRECTION_WRONG",
           lambda d: d.update(summary=d["summary"].replace("ahead of budget", "behind budget")))
    mutate("missing summary", "NO_SUMMARY", lambda d: d.update(summary=""))
    return out


def mutation_test(gold: dict, pack, index) -> dict:
    gold_report = validate_commentary(Commentary.model_validate(gold), pack, index)
    results = []
    for name, code, data in _mutations(gold):
        report = validate_commentary(Commentary.model_validate(data), pack, index)
        caught = any(i.code == code for i in report.issues)
        results.append({"mutation": name, "expected_issue": code, "caught": caught})
    return {"gold_blocking": [i.message for i in gold_report.blocking], "gold_metrics": gold_report.metrics,
            "results": results, "detected": sum(r["caught"] for r in results), "total": len(results)}


# --------------------------------------------------------------------------- run

def _draft(engine: str, case: dict, run_id: str):
    from monthend import pipeline
    from monthend.variance import draft_rule_based

    ctx = pipeline.load(run_id)
    if engine == "rules":
        return draft_rule_based(ctx.pack, pipeline.all_contexts(ctx)), None
    if engine == "claude":
        from monthend.llm import draft_commentary_with_claude

        return draft_commentary_with_claude(ctx.pack, pipeline.all_contexts(ctx), ctx.index)
    path = Path(engine)
    if case["id"] == "base-clean" and path.exists():
        return Commentary.model_validate_json(path.read_text()), None
    return draft_rule_based(ctx.pack, pipeline.all_contexts(ctx)), None


def run_case(case: dict, engine: str, judge: bool = False) -> dict:
    from monthend import pipeline

    with isolated_var() as tmp:
        store = Store(tmp / "monthend.db")
        run = pipeline.prepare(case["client"], case["period"], backend_name="fixtures", store=store,
                               overlays=case.get("overlays"), actor="eval")
        commentary, trace = _draft(engine, case, run["run_id"])
        pipeline.save_commentary(run["run_id"], commentary, actor=f"eval:{engine}", store=store)
        result = pipeline.finalise(run["run_id"], actor="eval", store=store)
        ctx = pipeline.load(run["run_id"], store)
        run_dir = ctx.run_dir
        expect = case["expect"]
        raised_block = {b["code"] for b in result["blocking"]}
        raised_warn = {w["code"] for w in result["warnings"]}
        # Commentary checks run against a freshly built index, independent of the pipeline's objects.
        fresh_index = EvidenceIndex(load_bundle(run_dir / "inputs"),
                                    json.loads((run_dir / "inputs" / "inputs-manifest.json").read_text())["files"])
        for paper in ctx.papers:
            for row in paper.rows:
                fresh_index.add_workpaper_row(paper.code, row.ref_no, row.description, row.amount)
        report = validate_commentary(commentary, ctx.pack, fresh_index)
        out = {
            "id": case["id"],
            "description": case["description"],
            "state": result["state"],
            "state_ok": result["state"] == expect["state"],
            "blocking_expected": sorted(expect["blocking_codes"]),
            "blocking_raised": sorted(raised_block),
            "blocking_missed": sorted(set(expect["blocking_codes"]) - raised_block),
            "unexpected_blocks": sorted(raised_block - set(expect["blocking_codes"]) - {"MISSING_MATERIAL_LINE"}),
            "warnings_expected": len(set(expect.get("warning_codes", []))),
            "warnings_missed": sorted(set(expect.get("warning_codes", [])) - raised_warn),
            "commentary": report.metrics,
            "commentary_issues": [f"{i.severity}: {i.message}" for i in report.issues if i.severity != "info"],
            "commentary_author": commentary.author,
        }
        if trace:
            out["repair_trace"] = trace
        if "material_lines" in expect:
            got = sorted(l.key for l in ctx.pack.material_lines())
            out["material_lines_ok"] = got == sorted(expect["material_lines"])
        if "pack" in expect:
            out["pack"] = grade_pack(ctx.outputs / "pack.xlsx", expect["pack"])
        if "ties" in expect:
            ties = {p.code: p.tie for p in ctx.papers}
            misses = [f"{code}.{k}: expected {v}, got {ties.get(code, {}).get(k)}"
                      for code, exp in expect["ties"].items() for k, v in exp.items() if ties.get(code, {}).get(k) != v]
            out["ties"] = {"checked": sum(len(e) for e in expect["ties"].values()), "misses": misses}
        out["references"] = grade_references(run_dir, [p.to_json() for p in ctx.papers])
        if case.get("commentary_labels"):
            out["labels"] = grade_labels(commentary, case["commentary_labels"])
        if case.get("gold_commentary"):
            gold = json.loads((CASES / case["gold_commentary"]).read_text())
            out["mutation"] = mutation_test(gold, ctx.pack, fresh_index)
        if judge and case.get("commentary_labels"):
            from monthend.llm import judge_commentary

            out["judge"] = judge_commentary(commentary, pipeline.all_contexts(ctx))
        return out


def summarise(results: list[dict], engine: str) -> dict:
    def ratio(num: int, den: int) -> float:
        return round(num / den, 4) if den else 1.0

    exp_blocks = sum(len(r["blocking_expected"]) for r in results)
    missed_blocks = sum(len(r["blocking_missed"]) for r in results)
    pack = [r["pack"] for r in results if "pack" in r]
    ties = [r["ties"] for r in results if "ties" in r]
    refs = [r["references"] for r in results]
    labels = [r["labels"] for r in results if "labels" in r]
    mutation = next((r["mutation"] for r in results if "mutation" in r), None)
    ready = [r for r in results if r["state"] == "READY_FOR_REVIEW"]
    metrics = {
        "cases": len(results),
        "state_accuracy": ratio(sum(r["state_ok"] for r in results), len(results)),
        "blocking_recall": ratio(exp_blocks - missed_blocks, exp_blocks),
        "false_blocks": sum(len(r["unexpected_blocks"]) for r in results),
        "warning_recall": ratio(sum(r["warnings_expected"] for r in results) - sum(len(r["warnings_missed"]) for r in results),
                                sum(r["warnings_expected"] for r in results)),
        "pack_cell_accuracy": ratio(sum(p["correct"] for p in pack), sum(p["cells"] for p in pack)),
        "tie_accuracy": ratio(sum(t["checked"] - len(t["misses"]) for t in ties), sum(t["checked"] for t in ties)),
        "reference_integrity": ratio(sum(r["resolved"] for r in refs), sum(r["references"] for r in refs)),
        "commentary_coverage": min((r["commentary"]["coverage"] for r in ready), default=1.0),
        "numeric_faithfulness": min((r["commentary"]["numeric_faithfulness"] for r in ready), default=1.0),
        "direction_accuracy": min((r["commentary"]["direction_accuracy"] for r in ready), default=1.0),
        "evidence_validity": min((r["commentary"]["evidence_valid"] for r in ready), default=1.0),
        "driver_recall": ratio(sum(l["driver_hits"] for l in labels), sum(l["driver_groups"] for l in labels)),
        "forbidden_claims": sum(l["forbidden_claims"] for l in labels),
    }
    if mutation:
        metrics["validator_mutation_detection"] = ratio(mutation["detected"], mutation["total"])
        metrics["validator_gold_false_positives"] = len(mutation["gold_blocking"])
    thresholds = json.loads((ROOT / "evals" / "thresholds.json").read_text())["thresholds"]
    engine_kind = engine if engine in ("rules", "claude") else "file"
    failures = []
    for name, rule in thresholds.items():
        if "applies_to" in rule and engine_kind not in rule["applies_to"]:
            continue
        value = metrics.get(name)
        if value is None:
            continue
        if "min" in rule and value < rule["min"]:
            failures.append(f"{name} = {value} (minimum {rule['min']})")
        if "max" in rule and value > rule["max"]:
            failures.append(f"{name} = {value} (maximum {rule['max']})")
    return {"metrics": metrics, "failures": failures, "passed": not failures}


def to_markdown(engine: str, summary: dict, results: list[dict]) -> str:
    m = summary["metrics"]
    lines = [f"# Evaluation report - engine `{engine}`", "",
             f"**{'PASSED' if summary['passed'] else 'FAILED'}** on {m['cases']} cases, "
             f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}.", "", "| Metric | Value |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in m.items()]
    if summary["failures"]:
        lines += ["", "## Below threshold", ""] + [f"- {f}" for f in summary["failures"]]
    lines += ["", "## Cases", ""]
    for r in results:
        flag = "ok" if r["state_ok"] and not r["blocking_missed"] and not r["unexpected_blocks"] and not r["warnings_missed"] else "CHECK"
        lines.append(f"- **{r['id']}** [{flag}] ended {r['state']}; blocking raised {r['blocking_raised'] or 'none'}"
                     + (f"; missed {r['blocking_missed']}" if r["blocking_missed"] else "")
                     + (f"; unexpected {r['unexpected_blocks']}" if r["unexpected_blocks"] else "")
                     + (f"; warnings missed {r['warnings_missed']}" if r["warnings_missed"] else ""))
        for detail in r.get("labels", {}).get("details", []):
            lines.append(f"  - {detail}")
        for miss in r.get("pack", {}).get("misses", []):
            lines.append(f"  - pack {miss}")
        for failure in r["references"]["failures"]:
            lines.append(f"  - reference {failure}")
    mutation = next((r["mutation"] for r in results if "mutation" in r), None)
    if mutation:
        lines += ["", "## Validator mutation tests", "", "| Planted defect | Must raise | Caught |", "|---|---|---|"]
        lines += [f"| {x['mutation']} | {x['expected_issue']} | {'yes' if x['caught'] else '**NO**'} |" for x in mutation["results"]]
    judged = [r for r in results if "judge" in r]
    if judged:
        lines += ["", "## LLM judge (advisory)", ""]
        for r in judged:
            for s in r["judge"].get("scores", []):
                lines.append(f"- {r['id']} {s['line_key']}: plain English {s['plain_english']}, cause {s['explains_cause']}, "
                             f"proportion {s['proportionate']}, actionable {s['actionable']} - {s['rationale']}")
    return "\n".join(lines) + "\n"


def run_evaluation(engine: str = "rules", cases: list[str] | None = None, judge: bool = False, trials: int = 1) -> dict:
    selected = load_cases(cases)
    results = []
    for case in selected:
        for trial in range(max(1, trials if engine == "claude" else 1)):
            result = run_case(case, engine, judge=judge)
            result["trial"] = trial
            results.append(result)
    summary = summarise(results, engine)
    markdown = to_markdown(engine, summary, results)
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = engine if engine in ("rules", "claude") else "file"
    payload = {"engine": engine, "summary": summary, "results": results}
    (REPORTS / f"{stamp}-{label}.json").write_text(json.dumps(payload, indent=2, default=str))
    (REPORTS / f"latest-{label}.json").write_text(json.dumps(payload, indent=2, default=str))
    (REPORTS / f"latest-{label}.md").write_text(markdown)
    return {"passed": summary["passed"], "summary": summary, "markdown": markdown, "results": results}
