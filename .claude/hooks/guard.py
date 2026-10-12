#!/usr/bin/env python3
"""PreToolUse guard: keeps agents on the right side of the review gate.

This is a second layer. The authoritative controls live in monthend/review.py (approval
and release tickets) and in each agent's tool list. If this hook fails while checking a
gated action, it denies (fails closed).
"""

from __future__ import annotations

import re

from _lib import PROJECT, decide, operate_mode, read_input

# The monthend CLI invoked with a human-only subcommand (optionally after global flags), e.g.
# "monthend review approve ...", ".venv/bin/python -m monthend release ...". Matched per line so that
# prose mentioning these words is not caught; the code-level gate catches anything this misses.
HUMAN_ONLY_COMMANDS = re.compile(
    r"(?:^|[\s;&|(/])monthend[ \t]+(?:-\S+[ \t]+)*(?:review[ \t]+(?:approve|request-changes)|release)\b", re.M)
DATABASE_TAMPERING = re.compile(r"\bsqlite3?\b[^|;&]*monthend\.db|monthend\.db[^|;&]*\b(DELETE|UPDATE|INSERT|DROP)\b", re.I)
RUN_TAMPERING = re.compile(r"(\brm\b|\bmv\b|\bcp\b|>|\btee\b|\bsed\s+-i)[^|;&]*\bvar/(runs|monthend\.db|outbox)")
XERO_WRITE = re.compile(r"mcp__xero__.*(create|update|delete|post|put|void|approve|send)", re.I)
PROTECTED_WHEN_OPERATING = ("evals/", "config/", ".claude/", "monthend/", "templates/", "fixtures/")


def main() -> None:
    data = read_input()
    tool = data.get("tool_name", "")
    args = data.get("tool_input", {}) or {}

    if tool == "Bash":
        command = args.get("command", "")
        if HUMAN_ONLY_COMMANDS.search(command):
            decide("deny", "Approving, requesting changes and releasing are human-only actions. "
                           "Tell the user the run is ready and give them the review page and command to run themselves.")
        if DATABASE_TAMPERING.search(command) or RUN_TAMPERING.search(command):
            decide("deny", "Run folders and the review database are evidence and may only change through monthend tools.")
        if operate_mode() and not re.match(r"^\s*(\.venv/bin/python -m monthend|monthend)\s+(runs|context|commentary validate|eval|audit)\b", command):
            decide("deny", "In operate mode the shell is limited to read-only monthend commands. Use the monthend MCP tools.")
        return

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = str(args.get("file_path") or args.get("notebook_path") or "")
        rel = path.replace(str(PROJECT) + "/", "")
        if rel.startswith("var/") or "/var/runs/" in path:
            decide("deny", "Run outputs are immutable evidence. Change drafts through the monthend MCP tools, which re-validate them.")
        if operate_mode() and rel.startswith(PROTECTED_WHEN_OPERATING):
            decide("deny", f"{rel} is part of the controlled configuration, code or evaluation set and cannot be edited during an operating run.")
        return

    if XERO_WRITE.search(tool):
        decide("deny", "The Xero connection is read-only.")

    if tool == "mcp__m365__deliver_approved_pack":
        run_id = args.get("run_id", "")
        try:
            from monthend.review import approval_status

            ok, reason = approval_status(None, run_id)
        except Exception as exc:  # fail closed
            decide("deny", f"Could not verify approval for {run_id}: {exc}")
        if not ok:
            decide("deny", f"Not releasable: {reason}")
        decide("ask", f"Run {run_id} is approved and unchanged. Confirm you want to deliver it now.")


if __name__ == "__main__":
    main()
