#!/usr/bin/env python3
"""Stop hook: don't let a session end with a commentary draft that fails validation.

Gives the agent one more turn to fix it (or to record follow-up questions and tell the
user). stop_hook_active prevents an endless loop.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _lib import read_input


def main() -> None:
    data = read_input()
    if data.get("stop_hook_active"):
        return
    try:
        from monthend.store import default_store

        store = default_store()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
        for run in store.runs(states=("PREPARED", "CHANGES_REQUESTED")):
            if datetime.fromisoformat(run["updated_at"]) < cutoff:
                continue
            path = Path(run["run_dir"]) / "outputs" / "commentary-validation.json"
            if not path.exists():
                continue
            report = json.loads(path.read_text())
            blocking = [i["message"] for i in report.get("issues", []) if i["severity"] == "block"]
            if blocking:
                print(json.dumps({"decision": "block", "reason":
                    f"Commentary for {run['run_id']} still fails validation: " + " | ".join(blocking[:5])
                    + " Fix it with save_commentary_draft, or explain to the user what evidence is missing."}))
                return
    except Exception:
        return


if __name__ == "__main__":
    main()
