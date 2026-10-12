#!/usr/bin/env python3
"""SessionStart: tell Claude what is waiting, so it starts from the real state of the work."""

from __future__ import annotations

from _lib import operate_mode, read_input


def main() -> None:
    read_input()
    try:
        from monthend.store import default_store

        runs = default_store().runs(states=("PREPARED", "BLOCKED", "READY_FOR_REVIEW", "CHANGES_REQUESTED", "APPROVED"))
    except Exception as exc:
        print(f"monthend: could not read the run register ({exc}).")
        return
    print(f"monthend mode: {'operate' if operate_mode() else 'develop'}.")
    if not runs:
        print("No active month-end runs.")
        return
    print("Active month-end runs:")
    for r in runs[:15]:
        print(f"- {r['run_id']} {r['state']}{(' - ' + r['state_reason']) if r['state_reason'] else ''}")


if __name__ == "__main__":
    main()
