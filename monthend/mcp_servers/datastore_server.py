"""MCP server: the run register, review decisions and audit log (read-only)."""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from monthend.mcp_servers._common import tool_errors
from monthend.store import default_store

mcp = FastMCP("datastore", instructions="Read-only view of runs, review decisions, releases and the audit trail.")


@mcp.tool()
@tool_errors
def list_runs(client_id: str = "", period: str = "", state: str = "") -> list[dict]:
    """Runs, newest first. Filter by client, period (YYYY-MM) or state."""
    rows = default_store().runs(client_id or None, period or None, (state,) if state else ())
    return [{k: r[k] for k in ("run_id", "client_id", "period", "state", "state_reason", "bundle_sha256", "created_at")} for r in rows]


@mcp.tool()
@tool_errors
def get_review_history(run_id: str) -> dict:
    """Human review decisions and releases for a run."""
    store = default_store()
    return {"decisions": store.decisions(run_id), "releases": store.releases(run_id)}


@mcp.tool()
@tool_errors
def get_audit_events(run_id: str = "", limit: int = 50) -> list[dict]:
    """Audit trail entries (who did what, when), newest first."""
    return [{k: e[k] for k in ("ts", "run_id", "actor", "kind", "detail")} for e in default_store().events(run_id or None, limit)]


@mcp.tool()
@tool_errors
def get_validation_report(run_id: str) -> dict:
    """The checks recorded when the run was finalised."""
    run = default_store().run(run_id)
    path = Path(run["run_dir"]) / "outputs" / "validation.json"
    return json.loads(path.read_text()) if path.exists() else {"error": "not_finalised"}


@mcp.tool()
@tool_errors
def verify_audit_log() -> dict:
    """Recompute the audit log hash chain. Any edited or deleted entry is reported."""
    problems = default_store().verify_audit_chain()
    return {"intact": not problems, "problems": problems}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
