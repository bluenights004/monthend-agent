"""Deterministic run lifecycle: prepare -> (agents draft) -> finalise -> human review -> release.

Agents call into this module through the `monthend` MCP server; people call it
through the CLI. Both paths share the same functions and the same checks.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from monthend.config import ClientConfig, Period, load_client, var_dir
from monthend.delivery import build_payload, write_payload
from monthend.evidence import EvidenceIndex
from monthend.pack import Check, Pack, build_pack, write_pack_xlsx
from monthend.review import GateError, submit_for_review
from monthend.snapshot import SourceBundle, load_bundle, write_inputs_manifest
from monthend.sources.backends import backend_for
from monthend.store import Store, default_store
from monthend.variance import (Commentary, ValidationReport, validate_commentary, variance_context,
                               workpaper_rows_for_context)
from monthend.workpapers import Workpaper, build_workpapers, workpapers_markdown, write_workpapers_xlsx

ACTIVE_STATES = ("PREPARED", "BLOCKED", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "APPROVED")


@dataclass
class RunContext:
    run: dict
    client: ClientConfig
    period: Period
    bundle: SourceBundle
    pack: Pack
    papers: list[Workpaper]
    index: EvidenceIndex

    @property
    def run_dir(self) -> Path:
        return Path(self.run["run_dir"])

    @property
    def outputs(self) -> Path:
        return self.run_dir / "outputs"


def _mapping_rows(client: ClientConfig) -> list[dict]:
    return json.loads(client.mapping_path.read_text())["rows"]


def _new_run_id(client_id: str, period: Period) -> str:
    return f"{client_id}-{period.key}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"


def prepare(client_id: str, period_key: str, *, backend_name: str | None = None, store: Store | None = None,
            overlays: list[dict] | None = None, skip_if_unchanged: bool = False, actor: str = "system") -> dict:
    """Snapshot sources, build the pack and workpapers. Returns the run record."""
    from monthend.overlays import apply_overlays

    store = store or default_store()
    client = load_client(client_id)
    period = Period.parse(period_key)
    backend = backend_for(backend_name or client.backend)

    staging = Path(tempfile.mkdtemp(prefix="monthend-", dir=var_dir()))
    try:
        inputs = staging / "inputs"
        inputs.mkdir()
        backend.fetch(client, period, inputs)
        if overlays:
            apply_overlays(inputs, overlays)
        manifest = write_inputs_manifest(inputs)

        active = store.runs(client_id, period.key, ACTIVE_STATES)
        if skip_if_unchanged and active and active[0]["inputs_sha256"] == manifest["inputs_sha256"]:
            store.event(active[0]["run_id"], actor, "prepare_skipped", {"reason": "source data unchanged"})
            return active[0]

        run_id = _new_run_id(client_id, period)
        run_dir = var_dir() / "runs" / client_id / period.key / run_id
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), run_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    (run_dir / "outputs").mkdir(exist_ok=True)
    (run_dir / "notes").mkdir(exist_ok=True)
    bundle = load_bundle(run_dir / "inputs")
    pack = build_pack(client, period, bundle, _mapping_rows(client))
    released = store.runs(client_id, period.key, ("RELEASED",))
    if released:
        pack.checks.append(Check("REISSUE", "warn", f"A pack for {period.label} was already released (run {released[0]['run_id']}). "
                                                    "Approving this run means issuing a revised pack."))
    index = EvidenceIndex(bundle, manifest["files"])
    papers = build_workpapers(client, period, bundle, index)
    _write_json(run_dir / "outputs" / "pack.json", pack.to_json())
    _write_json(run_dir / "outputs" / "workpapers.json", [p.to_json() for p in papers])

    for older in active:
        store.set_state(older["run_id"], "SUPERSEDED", actor, f"superseded by {run_id} (source data changed)")
    store.create_run(run_id, client_id, period.key, backend.name, run_dir, manifest["inputs_sha256"])
    _render_workpapers(run_dir, client, pack, papers, bundle, run_id)
    return store.run(run_id)


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False, default=str) + "\n")


def load(run_id: str, store: Store | None = None) -> RunContext:
    store = store or default_store()
    run = store.run(run_id)
    if run is None:
        raise GateError(f"unknown run {run_id}")
    client = load_client(run["client_id"])
    period = Period.parse(run["period"])
    run_dir = Path(run["run_dir"])
    bundle = load_bundle(run_dir / "inputs")
    manifest = json.loads((run_dir / "inputs" / "inputs-manifest.json").read_text())
    index = EvidenceIndex(bundle, manifest["files"])
    pack = Pack.from_json(json.loads((run_dir / "outputs" / "pack.json").read_text()))
    papers = [Workpaper.from_json(p) for p in json.loads((run_dir / "outputs" / "workpapers.json").read_text())]
    notes = _read_notes(run_dir)
    for paper in papers:
        paper.preparer_notes = notes.get(paper.code, [])
        for row in paper.rows:
            index.add_workpaper_row(paper.code, row.ref_no, row.description, row.amount)
    return RunContext(run, client, period, bundle, pack, papers, index)


def _read_notes(run_dir: Path) -> dict[str, list[str]]:
    path = run_dir / "notes" / "workpaper-notes.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _render_workpapers(run_dir: Path, client: ClientConfig, pack: Pack, papers: list[Workpaper], bundle: SourceBundle, run_id: str) -> None:
    write_workpapers_xlsx(papers, pack, bundle, run_dir / "outputs" / "workpapers.xlsx", run_id)
    (run_dir / "outputs" / "workpapers.md").write_text(workpapers_markdown(papers, pack, run_id))


def _require_editable(ctx: RunContext) -> None:
    if ctx.run["state"] not in ("PREPARED", "BLOCKED", "CHANGES_REQUESTED"):
        raise GateError(f"run {ctx.run['run_id']} is {ctx.run['state']}; drafts can only change before submission "
                        "or after a reviewer requests changes")


# --------------------------------------------------------------------------- agent-facing operations

def context_for(run_id: str, line_key: str, store: Store | None = None) -> dict:
    ctx = load(run_id, store)
    return variance_context(ctx.pack, ctx.bundle, ctx.index, line_key, ctx.period.key, workpaper_rows_for_context(ctx.papers))


def all_contexts(ctx: RunContext) -> dict[str, dict]:
    rows = workpaper_rows_for_context(ctx.papers)
    return {l.key: variance_context(ctx.pack, ctx.bundle, ctx.index, l.key, ctx.period.key, rows) for l in ctx.pack.material_lines()}


def save_commentary(run_id: str, commentary: Commentary | dict, *, actor: str, store: Store | None = None) -> ValidationReport:
    store = store or default_store()
    ctx = load(run_id, store)
    _require_editable(ctx)
    if isinstance(commentary, dict):
        commentary = Commentary.model_validate(commentary)
    report = validate_commentary(commentary, ctx.pack, ctx.index)
    _write_json(ctx.outputs / "commentary.json", commentary.model_dump())
    _write_json(ctx.outputs / "commentary-validation.json", report.to_json())
    store.event(run_id, actor, "commentary_saved", {"author": commentary.author, "ok": report.ok,
                                                     "blocking": len(report.blocking), "metrics": report.metrics})
    if ctx.run["state"] == "CHANGES_REQUESTED":
        store.set_state(run_id, "PREPARED", actor, "commentary revised after review; needs re-submission")
    return report


def add_preparer_note(run_id: str, wp_code: str, note: str, *, actor: str, store: Store | None = None) -> list[str]:
    store = store or default_store()
    ctx = load(run_id, store)
    _require_editable(ctx)
    if wp_code not in {p.code for p in ctx.papers}:
        raise GateError(f"no workpaper {wp_code} in run {run_id}")
    notes = _read_notes(ctx.run_dir)
    notes.setdefault(wp_code, []).append(note.strip())
    _write_json(ctx.run_dir / "notes" / "workpaper-notes.json", notes)
    store.event(run_id, actor, "preparer_note_added", {"workpaper": wp_code, "note": note[:500]})
    return notes[wp_code]


def save_review_notes(run_id: str, findings: list[dict], *, actor: str, store: Store | None = None) -> None:
    """Independent (agent) reviewer findings. Advisory: shown to the human reviewer, never a decision."""
    store = store or default_store()
    ctx = load(run_id, store)
    _require_editable(ctx)
    clean = [{"severity": f.get("severity", "note"), "area": f.get("area", ""), "finding": f.get("finding", ""),
              "evidence": f.get("evidence", [])} for f in findings]
    _write_json(ctx.run_dir / "notes" / "independent-review.json", {"reviewer": actor, "findings": clean})
    store.event(run_id, actor, "independent_review_saved", {"findings": len(clean)})


# --------------------------------------------------------------------------- finalise

def finalise(run_id: str, *, actor: str, store: Store | None = None) -> dict:
    """Render deliverables, run every check, then submit for human review or mark BLOCKED."""
    store = store or default_store()
    ctx = load(run_id, store)
    _require_editable(ctx)
    commentary_path = ctx.outputs / "commentary.json"
    if not commentary_path.exists():
        raise GateError("no commentary drafted yet; the variance-analyst must save a draft first")
    commentary = Commentary.model_validate_json(commentary_path.read_text())
    commentary_report = validate_commentary(commentary, ctx.pack, ctx.index)

    from monthend.snapshot import verify_inputs

    blocking = [{"source": "pack", "code": c.code, "message": c.message} for c in ctx.pack.checks if c.severity == "block"]
    blocking += [{"source": f"workpaper {p.code}", "code": i.code, "message": i.message} for p in ctx.papers for i in p.issues if i.severity == "block"]
    blocking += [{"source": "commentary", "code": i.code, "message": i.message} for i in commentary_report.blocking]
    blocking += [{"source": "inputs", "code": "INPUT_CHANGED", "message": m} for m in verify_inputs(ctx.run_dir / "inputs")]
    warnings = [{"source": "pack", "code": c.code, "message": c.message} for c in ctx.pack.checks if c.severity == "warn"]
    warnings += [{"source": f"workpaper {p.code}", "code": i.code, "message": i.message} for p in ctx.papers for i in p.issues if i.severity == "warn"]
    warnings += [{"source": "commentary", "code": i.code, "message": i.message} for i in commentary_report.issues if i.severity == "warn"]

    meta = {"run_id": run_id, "prepared_at": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")}
    write_pack_xlsx(ctx.pack, ctx.client.template_path, ctx.outputs / "pack.xlsx", commentary=commentary.model_dump(), meta=meta)
    _render_workpapers(ctx.run_dir, ctx.client, ctx.pack, ctx.papers, ctx.bundle, run_id)
    write_payload(ctx.outputs, build_payload(ctx.client, ctx.period, commentary.summary))
    validation = {"blocking": blocking, "warnings": warnings, "commentary_metrics": commentary_report.metrics,
                  "independent_review": _independent_review(ctx.run_dir)}
    _write_json(ctx.outputs / "validation.json", validation)

    manifest = None
    if not blocking:
        try:
            manifest = submit_for_review(store, run_id, [ctx.client.path, ctx.client.mapping_path, ctx.client.template_path], actor)
        except GateError as exc:
            blocking.append({"source": "review gate", "code": "RESUBMITTED_UNCHANGED", "message": str(exc)})
            validation["blocking"] = blocking
            _write_json(ctx.outputs / "validation.json", validation)
    if blocking:
        store.set_state(run_id, "BLOCKED", actor, f"{len(blocking)} blocking issue(s)")
    from monthend.report import render_review_page

    run = store.run(run_id)
    render_review_page(load(run_id, store), run, validation, commentary, manifest, store)
    return {"run_id": run_id, "state": run["state"], "blocking": blocking, "warnings": warnings,
            "bundle_sha256": manifest["bundle_sha256"] if manifest else None,
            "review_page": str(ctx.outputs / "review.html")}


def _independent_review(run_dir: Path) -> dict | None:
    path = run_dir / "notes" / "independent-review.json"
    return json.loads(path.read_text()) if path.exists() else None


def release(run_id: str, *, actor: str, channel: str | None = None, store: Store | None = None, graph=None) -> str:
    from monthend.delivery import deliver
    from monthend.review import issue_release_ticket

    store = store or default_store()
    run = store.run(run_id)
    if run is None:
        raise GateError(f"unknown run {run_id}")
    ticket = issue_release_ticket(store, run_id)
    channel = channel or ("graph" if run["backend"] == "live" else "outbox")
    ref = deliver(ticket, Path(run["run_dir"]) / "outputs", channel, graph=graph)
    store.add_release(run_id, ticket.bundle_sha256, channel, ref, actor)
    store.set_state(run_id, "RELEASED", actor, ref)
    return ref
