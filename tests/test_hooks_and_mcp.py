"""Claude Code layer: hook decisions, MCP tool surface, agent and skill definitions."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"


def guard(tool_name: str, tool_input: dict, **env) -> dict | None:
    result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
                            capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT), **env}, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


@pytest.mark.parametrize("command", [
    ".venv/bin/python -m monthend review approve --run x --code abc",
    "monthend review request-changes --run x",
    "cd /tmp && monthend release --run x",
    "sqlite3 var/monthend.db 'UPDATE runs SET state=\"APPROVED\"'",
    "rm -rf var/runs/harbour-joinery",
])
def test_guard_denies_human_only_and_tampering_commands(command):
    decision = guard("Bash", {"command": command})
    assert decision and decision["permissionDecision"] == "deny"


def test_guard_allows_ordinary_development_commands():
    assert guard("Bash", {"command": ".venv/bin/python -m pytest -q"}) is None
    # Regression: prose that mentions the words must not be mistaken for the command.
    assert guard("Bash", {"command": "cat > notes.txt <<'EOF'\nmonthend-agent: versions this release was tested with\nEOF"}) is None
    assert guard("Bash", {"command": ".venv/bin/python -m monthend nightly --agent none"}) is None
    assert guard("Edit", {"file_path": str(ROOT / "monthend" / "pack.py")}) is None


def test_operate_mode_locks_down_shell_and_config():
    assert guard("Bash", {"command": "ls"}, MONTHEND_MODE="operate")["permissionDecision"] == "deny"
    assert guard("Bash", {"command": ".venv/bin/python -m monthend runs"}, MONTHEND_MODE="operate") is None
    assert guard("Edit", {"file_path": str(ROOT / "evals" / "thresholds.json")}, MONTHEND_MODE="operate")["permissionDecision"] == "deny"


def test_guard_denies_writes_to_run_evidence():
    decision = guard("Write", {"file_path": str(ROOT / "var" / "runs" / "x" / "outputs" / "commentary.json")})
    assert decision["permissionDecision"] == "deny"


def test_guard_refuses_delivery_without_approval(tmp_path):
    decision = guard("mcp__m365__deliver_approved_pack", {"run_id": "no-such-run"}, MONTHEND_VAR_DIR=str(tmp_path))
    assert decision["permissionDecision"] == "deny" and "unknown run" in decision["permissionDecisionReason"]


def test_mcp_servers_expose_no_approval_tools():
    from monthend.mcp_servers import datastore_server, m365_server, monthend_server, xero_server

    names = []
    for module in (monthend_server, xero_server, m365_server, datastore_server):
        names += [t.name for t in asyncio.run(module.mcp.list_tools())]
    gated = {"deliver_approved_pack"}  # takes only a run id; refuses unless a person approved that exact bundle
    assert not [n for n in names if n not in gated and re.search(r"approve|reject|request_changes|post_journal|update|delete|send", n)]
    assert [n for n in names if "deliver" in n] == ["deliver_approved_pack"]


def test_mcp_tool_returns_gate_refusal_as_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTHEND_VAR_DIR", str(tmp_path))
    from monthend.mcp_servers.m365_server import deliver_approved_pack

    result = deliver_approved_pack("no-such-run")
    assert result["error"] == "refused_by_review_gate"


def _frontmatter(path: Path) -> dict:
    text = path.read_text()
    block = text.split("---")[1]
    return {k.strip(): v.strip() for k, v in (line.split(":", 1) for line in block.strip().splitlines() if ":" in line)}


def test_subagents_are_least_privilege():
    agents = {p.stem: _frontmatter(p) for p in (ROOT / ".claude" / "agents").glob("*.md")}
    assert set(agents) == {"pack-assembler", "workpaper-preparer", "variance-analyst", "independent-reviewer"}
    for name, meta in agents.items():
        tools = [t.strip() for t in meta["tools"].split(",")]
        assert "Bash" not in tools and "Write" not in tools and "Edit" not in tools, name
        assert "mcp__m365__deliver_approved_pack" not in tools, name
    assert "mcp__monthend__save_commentary_draft" not in agents["independent-reviewer"]["tools"]


def test_skills_present_and_release_is_human_invoked():
    skills = {p.parent.name: _frontmatter(p) for p in (ROOT / ".claude" / "skills").glob("*/SKILL.md")}
    assert {"month-end-close", "variance-commentary", "workpaper-standards", "review-checklist", "release-approved-pack"} <= set(skills)
    assert skills["release-approved-pack"]["disable-model-invocation"] == "true"


def test_mcp_config_points_at_real_modules():
    config = json.loads((ROOT / ".mcp.json").read_text())
    for name, server in config["mcpServers"].items():
        module = server["args"][1]
        assert (ROOT / (module.replace(".", "/") + ".py")).exists(), name
