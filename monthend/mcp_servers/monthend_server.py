"""MCP server: the month-end workflow (runs, pack, workpapers, commentary, submission).

Deliberately absent: approve, request changes, release. Those belong to people.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from monthend import pipeline
from monthend.config import list_clients
from monthend.extraction import read_document as read_doc
from monthend.mcp_servers._common import tool_errors
from monthend.store import default_store
from monthend.variance import validate_commentary, Commentary

mcp = FastMCP("monthend", instructions=(
    "Month-end workflow tools. Figures come only from these tools; never compute or invent a figure yourself. "
    "Every commentary driver must cite evidence ids returned by get_variance_context or read_document. "
    "Approval and release are human-only and are not available here."))


@mcp.tool()
@tool_errors
def list_configured_clients() -> list[str]:
    """Client ids that have a configuration file."""
    return list_clients()


@mcp.tool()
@tool_errors
def prepare_run(client_id: str, period: str, skip_if_unchanged: bool = True) -> dict:
    """Snapshot Xero and Microsoft 365 data for a period (YYYY-MM) and build the pack and workpapers.

    Returns the run id and every check raised. If the source data is unchanged since the
    latest active run, that run is returned instead of creating a new one.
    """
    run = pipeline.prepare(client_id, period, skip_if_unchanged=skip_if_unchanged, actor="agent:pack-assembler")
    ctx = pipeline.load(run["run_id"])
    return {"run_id": run["run_id"], "state": run["state"],
            "checks": [{"severity": c.severity, "code": c.code, "message": c.message} for c in ctx.pack.checks],
            "workpaper_issues": [{"workpaper": p.code, "severity": i.severity, "message": i.message} for p in ctx.papers for i in p.issues],
            "material_lines": [l.key for l in ctx.pack.material_lines()]}


@mcp.tool()
@tool_errors
def get_run_status(run_id: str) -> dict:
    """Current state of a run and the review decisions recorded so far."""
    store = default_store()
    return {"run": store.run(run_id), "decisions": store.decisions(run_id)}


@mcp.tool()
@tool_errors
def get_pack(run_id: str, statement: str = "all") -> dict:
    """Pack lines with actual, budget, variance and materiality. statement: 'pl', 'bs' or 'all'."""
    ctx = pipeline.load(run_id)
    lines = [l for l in ctx.pack.lines if statement == "all" or l.statement == statement]
    return {"client": ctx.pack.client_name, "period": ctx.pack.period_label, "currency": ctx.pack.currency,
            "lines": [{"key": l.key, "label": l.label, "type": l.type, "values": l.values, "material": l.material,
                       "favourable": l.favourable, "accounts": l.accounts} for l in lines],
            "checks": [{"severity": c.severity, "code": c.code, "message": c.message} for c in ctx.pack.checks]}


@mcp.tool()
@tool_errors
def get_variance_context(run_id: str, line_key: str) -> dict:
    """Figures, account split, this period's transactions, related emails and workpaper rows for one pack line."""
    return pipeline.context_for(run_id, line_key)


@mcp.tool()
@tool_errors
def get_workpapers(run_id: str) -> dict:
    """Workpapers as markdown plus their issues and any preparer notes."""
    ctx = pipeline.load(run_id)
    from monthend.workpapers import workpapers_markdown

    return {"markdown": workpapers_markdown(ctx.papers, ctx.pack, run_id),
            "issues": [{"workpaper": p.code, "severity": i.severity, "message": i.message} for p in ctx.papers for i in p.issues]}


@mcp.tool()
@tool_errors
def list_documents(run_id: str) -> list[dict]:
    """Source documents in the run snapshot, with their SHA-256 prefix."""
    ctx = pipeline.load(run_id)
    return [{"doc_id": d.doc_id, "filename": d.filename, "sha256": d.short_hash, "type": d.media_type} for d in ctx.bundle.documents.values()]


@mcp.tool()
@tool_errors
def read_document(run_id: str, doc_id: str) -> dict:
    """Text of a snapshot document. Each line is prefixed with its locator; cite it as doc:<doc_id>#<locator>."""
    ctx = pipeline.load(run_id)
    doc = ctx.bundle.documents[doc_id]
    content = read_doc(doc)
    if content.kind == "csv":
        lines = [f"r{n}:{col} = {value}" for n, row in enumerate(content.rows, start=1) for col, value in row.items()]
    else:
        lines = [f"p{p}:L{i}  {text}" for p, page in enumerate(content.pages, start=1) for i, text in enumerate(page, start=1)]
    return {"doc_id": doc_id, "sha256": doc.short_hash, "lines": lines}


@mcp.tool()
@tool_errors
def resolve_evidence(run_id: str, evidence_id: str) -> dict:
    """Look up one evidence id and return its text and amounts, or an error if it does not exist."""
    ev = pipeline.load(run_id).index.resolve(evidence_id)
    if ev is None:
        return {"error": "not_found", "message": f"{evidence_id} does not exist in this run"}
    return {"id": ev.id, "kind": ev.kind, "title": ev.title, "text": ev.text, "amounts": list(ev.amounts), "date": ev.date}


@mcp.tool()
@tool_errors
def add_workpaper_note(run_id: str, workpaper: str, note: str) -> dict:
    """Add a preparer note (judgement, follow-up, proposed adjustment) to a workpaper. Notes never change figures."""
    return {"workpaper": workpaper, "notes": pipeline.add_preparer_note(run_id, workpaper, note, actor="agent:workpaper-preparer")}


@mcp.tool()
@tool_errors
def save_commentary_draft(run_id: str, commentary: dict) -> dict:
    """Save a commentary draft and get the validator's verdict.

    commentary = {"summary": str, "author": str, "items": [{"line_key": str, "text": str,
    "drivers": [{"description": str, "amount": number|null, "evidence": [evidence ids]}], "follow_up": [str]}]}.
    If 'ok' is false, fix every blocking issue and save again.
    """
    return pipeline.save_commentary(run_id, commentary, actor="agent:variance-analyst").to_json()


@mcp.tool()
@tool_errors
def validate_saved_commentary(run_id: str) -> dict:
    """Re-run the validator on the commentary currently saved for this run."""
    ctx = pipeline.load(run_id)
    commentary = Commentary.model_validate_json((ctx.outputs / "commentary.json").read_text())
    return validate_commentary(commentary, ctx.pack, ctx.index).to_json()


@mcp.tool()
@tool_errors
def save_independent_review(run_id: str, findings: list[dict]) -> dict:
    """Record the independent reviewer's findings: [{"severity": "high|medium|low", "area": str, "finding": str, "evidence": [ids]}].

    Advisory only. Shown to the human reviewer; does not approve or reject anything.
    """
    pipeline.save_review_notes(run_id, findings, actor="agent:independent-reviewer")
    return {"saved": len(findings)}


@mcp.tool()
@tool_errors
def finalise_run(run_id: str) -> dict:
    """Render the pack, workpapers and review page, run every check, and submit for human review (or mark BLOCKED)."""
    return pipeline.finalise(run_id, actor="agent:orchestrator")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
