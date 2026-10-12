#!/usr/bin/env python3
"""PostToolUse: append every agent tool call to the hash-chained audit log."""

from __future__ import annotations

import hashlib
import json

from _lib import read_input


def main() -> None:
    data = read_input()
    tool = data.get("tool_name", "")
    args = data.get("tool_input", {}) or {}
    try:
        from monthend.store import default_store

        blob = json.dumps(args, sort_keys=True, default=str)
        response = data.get("tool_response")
        is_error = isinstance(response, dict) and bool(response.get("error"))
        default_store().event(args.get("run_id"), f"claude-code:{str(data.get('session_id', ''))[:8]}", f"tool:{tool}",
                              {"input_sha256": hashlib.sha256(blob.encode()).hexdigest(), "input_preview": blob[:300],
                               "error": is_error})
    except Exception:
        pass  # auditing must never break the session; gaps are visible in the log's tool sequence


if __name__ == "__main__":
    main()
