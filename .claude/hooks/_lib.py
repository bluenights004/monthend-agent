"""Shared helpers for hook scripts. Standard library only: hooks must run even if the venv is broken."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PROJECT))


def read_input() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def decide(decision: str, reason: str) -> None:
    """Emit a PreToolUse permission decision and exit."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def operate_mode() -> bool:
    return os.environ.get("MONTHEND_MODE", "").lower() == "operate"
