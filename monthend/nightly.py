"""Overnight unattended run.

For each scheduled client: snapshot the previous month (skipped if the source data is
unchanged), run the Claude agent team through the Claude Agent SDK with a spend cap,
fall back to rule-based commentary if the agent stage fails, finalise, and write a
status file a person reads in the morning. Nothing is approved or sent overnight.

Schedule it with cron, launchd, systemd or Windows Task Scheduler (deploy/).
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from monthend import pipeline
from monthend.config import CONFIG_DIR, ROOT, Period, var_dir
from monthend.sources.http import ReauthorisationRequired
from monthend.store import default_store

log = logging.getLogger("monthend.nightly")

# The agent may read and draft; it may not use a shell, edit files, browse, or release.
AGENT_ALLOWED_TOOLS = [
    "Read", "Glob", "Grep", "Task", "Agent", "Skill",
    "mcp__monthend__list_configured_clients", "mcp__monthend__get_run_status", "mcp__monthend__get_pack",
    "mcp__monthend__get_variance_context", "mcp__monthend__get_workpapers", "mcp__monthend__list_documents",
    "mcp__monthend__read_document", "mcp__monthend__resolve_evidence", "mcp__monthend__add_workpaper_note",
    "mcp__monthend__save_commentary_draft", "mcp__monthend__validate_saved_commentary",
    "mcp__monthend__save_independent_review", "mcp__monthend__finalise_run",
    "mcp__xero__xero_get_trial_balance", "mcp__xero__xero_list_invoices", "mcp__xero__xero_list_bank_transactions",
    "mcp__xero__xero_get_budget", "mcp__xero__xero_list_accounts",
    "mcp__m365__outlook_search_messages", "mcp__m365__sharepoint_list_client_documents", "mcp__m365__excel_read_range",
    "mcp__datastore__list_runs", "mcp__datastore__get_validation_report",
]
AGENT_DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch",
                          "mcp__m365__deliver_approved_pack", "mcp__monthend__prepare_run"]


def _schedule() -> dict:
    return json.loads((CONFIG_DIR / "schedule.json").read_text())


def _agent_prompt(run_id: str, client_id: str, period: str) -> str:
    return (f"/month-end-close {client_id} {period} run_id={run_id}\n\n"
            f"Unattended overnight run. The run {run_id} is already prepared; do not prepare another. "
            "Follow the month-end-close skill: workpaper-preparer, then variance-analyst, then independent-reviewer, "
            "then finalise_run. Nobody is available to answer questions, so record open questions as follow-ups. "
            "Approval and release are for a person in the morning.")


async def _run_agent(run_id: str, client_id: str, period: str, budget: float, max_turns: int, model: str) -> dict:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        cwd=str(ROOT),
        setting_sources=["project"],          # CLAUDE.md, .claude/agents, .claude/skills, hooks
        mcp_servers=str(ROOT / ".mcp.json"),
        permission_mode="dontAsk",            # anything not allow-listed is denied, never prompted
        allowed_tools=AGENT_ALLOWED_TOOLS,
        disallowed_tools=AGENT_DISALLOWED_TOOLS,
        max_turns=max_turns,
        max_budget_usd=budget,
        model=model or None,
        env={"MONTHEND_AGENT_SESSION": "nightly", "MONTHEND_MODE": "operate"},
    )
    result = None
    async for message in query(prompt=_agent_prompt(run_id, client_id, period), options=options):
        if isinstance(message, ResultMessage):
            result = message
    if result is None:
        return {"ok": False, "error": "agent produced no result"}
    return {"ok": not result.is_error and result.subtype == "success", "subtype": result.subtype,
            "turns": result.num_turns, "cost_usd": result.total_cost_usd, "session_id": result.session_id,
            "permission_denials": len(result.permission_denials or [])}


def _fallback_commentary(run_id: str, reason: str) -> None:
    from monthend.variance import draft_rule_based

    ctx = pipeline.load(run_id)
    commentary = draft_rule_based(ctx.pack, pipeline.all_contexts(ctx))
    commentary.author = f"rules-baseline (agent stage unavailable: {reason[:120]})"
    pipeline.save_commentary(run_id, commentary, actor="nightly:fallback")


def process_client(client_id: str, period: Period, agent: str, budget: float, max_turns: int, model: str) -> dict:
    store = default_store()
    entry: dict = {"client_id": client_id, "period": period.key}
    run = pipeline.prepare(client_id, period.key, skip_if_unchanged=True, actor="nightly")
    entry["run_id"] = run["run_id"]
    if run["state"] != "PREPARED":
        entry.update(state=run["state"], action="source data unchanged; nothing to do")
        return entry

    ctx = pipeline.load(run["run_id"])
    data_blocked = [c.message for c in ctx.pack.checks if c.severity == "block"]
    if data_blocked:
        _fallback_commentary(run["run_id"], "data checks failed")
        entry["agent"] = {"skipped": "data checks failed; no model spend"}
    elif agent == "sdk":
        try:
            entry["agent"] = asyncio.run(_run_agent(run["run_id"], client_id, period.key, budget, max_turns, model))
        except Exception as exc:  # the SDK or CLI is missing, or the session crashed
            entry["agent"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not (ctx.outputs / "commentary.json").exists():
            _fallback_commentary(run["run_id"], entry["agent"].get("error") or entry["agent"].get("subtype", "no draft saved"))
            entry["agent"]["fallback"] = "rule-based commentary used"
    else:
        _fallback_commentary(run["run_id"], "agent disabled")
        entry["agent"] = {"skipped": "agent disabled (--agent none)"}

    current = store.run(run["run_id"])
    if current["state"] == "PREPARED":
        result = pipeline.finalise(run["run_id"], actor="nightly")
    else:  # the agent already finalised; report what it recorded
        validation_path = ctx.outputs / "validation.json"
        validation = json.loads(validation_path.read_text()) if validation_path.exists() else {}
        result = {"blocking": validation.get("blocking", []), "warnings": validation.get("warnings", []),
                  "review_page": str(ctx.outputs / "review.html")}
    entry.update(state=store.run(run["run_id"])["state"], blocking=[b["message"] for b in result.get("blocking", [])],
                 warnings=len(result.get("warnings", [])), review_page=result.get("review_page"))
    return entry


def run_nightly(clients: list[str] | None = None, period: str | None = None, agent: str = "sdk",
                max_budget_usd: float | None = None) -> dict:
    schedule = _schedule()
    tz = ZoneInfo(schedule.get("timezone", "UTC"))
    target = Period.parse(period) if period else Period.previous_to(datetime.now(tz).date())
    status_dir = var_dir() / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    lock_path = var_dir() / "nightly.lock"
    started = datetime.now(timezone.utc)
    status = {"started_at": started.isoformat(timespec="seconds"), "period": target.key, "clients": [], "ok": True}

    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            status.update(ok=False, error="another nightly run is still in progress")
            return status
        agent_cfg = schedule.get("agent", {})
        for client_id in clients or schedule["clients"]:
            try:
                entry = process_client(client_id, target, agent, max_budget_usd or agent_cfg.get("max_budget_usd_per_client", 5.0),
                                       agent_cfg.get("max_turns", 80), agent_cfg.get("model", ""))
            except ReauthorisationRequired as exc:
                entry = {"client_id": client_id, "error": str(exc), "action": "a person must reconnect Xero"}
                status["ok"] = False
            except Exception as exc:
                entry = {"client_id": client_id, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
                status["ok"] = False
            status["clients"].append(entry)

    status["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = json.dumps(status, indent=2, default=str)
    (status_dir / f"nightly-{started:%Y%m%d}.json").write_text(text)
    (status_dir / "latest.json").write_text(text)
    (status_dir / "heartbeat").write_text(status["finished_at"])
    (status_dir / "latest.md").write_text(morning_summary(status))
    _notify(status)
    return status


def morning_summary(status: dict) -> str:
    lines = [f"# Overnight run {status['started_at'][:10]} - period {status['period']}", ""]
    for c in status["clients"]:
        if "error" in c:
            lines.append(f"- **{c['client_id']}**: FAILED - {c['error']}. {c.get('action', 'See logs.')}")
            continue
        agent = c.get("agent", {})
        spend = f", agent cost ~USD {agent['cost_usd']:.2f}" if agent.get("cost_usd") else ""
        lines.append(f"- **{c['client_id']}**: {c['state'].replace('_', ' ').lower()}{spend}. "
                     + (f"Blocking: {'; '.join(c['blocking'])}. " if c.get("blocking") else "")
                     + (f"Review page: {c['review_page']}" if c.get("review_page") else c.get("action", "")))
    return "\n".join(lines) + "\n"


def _notify(status: dict) -> None:
    """Optional: post the morning summary to an internal Teams/Slack incoming webhook. No client figures are sent."""
    url = os.environ.get("MONTHEND_NOTIFY_WEBHOOK")
    if not url:
        return
    try:
        import httpx

        lines = [f"{c['client_id']}: {c.get('state', 'FAILED')}" for c in status["clients"]]
        httpx.post(url, json={"text": f"Month-end overnight run {status['period']}: " + "; ".join(lines)}, timeout=15)
    except Exception as exc:  # notification failure must never fail the run
        log.warning("notification failed: %s", exc)
