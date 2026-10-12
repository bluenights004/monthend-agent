"""SQLite run register, review decisions and a hash-chained audit log (standard library only).

Hooks import this module, so it must not depend on anything outside the standard
library. The schema in SCHEMA is portable to Postgres/Supabase (docs/06-architecture.md).
"""

from __future__ import annotations

import getpass
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    period TEXT NOT NULL,
    state TEXT NOT NULL,
    backend TEXT NOT NULL,
    run_dir TEXT NOT NULL,
    inputs_sha256 TEXT NOT NULL,
    bundle_sha256 TEXT,
    state_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_client_period ON runs (client_id, period);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'changes_requested')),
    notes TEXT NOT NULL,
    bundle_sha256 TEXT NOT NULL,
    os_user TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    bundle_sha256 TEXT NOT NULL,
    channel TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    released_by TEXT NOT NULL,
    released_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

STATES = ("PREPARED", "BLOCKED", "READY_FOR_REVIEW", "APPROVED", "CHANGES_REQUESTED", "RELEASED", "SUPERSEDED")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def os_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - containers without a passwd entry
        return "unknown"


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    # ------------------------------------------------------------------ runs

    def create_run(self, run_id: str, client_id: str, period: str, backend: str, run_dir: Path, inputs_sha256: str) -> None:
        stamp = now()
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, client_id, period, "PREPARED", backend, str(run_dir), inputs_sha256, None, None, stamp, stamp))
        self.event(run_id, "system", "run_prepared", {"client_id": client_id, "period": period, "inputs_sha256": inputs_sha256})

    def run(self, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def runs(self, client_id: str | None = None, period: str | None = None, states: tuple[str, ...] = ()) -> list[dict]:
        sql, args = "SELECT * FROM runs WHERE 1=1", []
        if client_id:
            sql, args = sql + " AND client_id = ?", args + [client_id]
        if period:
            sql, args = sql + " AND period = ?", args + [period]
        if states:
            sql += f" AND state IN ({','.join('?' * len(states))})"
            args += list(states)
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql + " ORDER BY created_at DESC, run_id DESC", args)]

    def set_state(self, run_id: str, state: str, actor: str, reason: str = "", bundle_sha256: str | None = None) -> None:
        if state not in STATES:
            raise ValueError(state)
        with self.connect() as db:
            if bundle_sha256 is None:
                db.execute("UPDATE runs SET state = ?, state_reason = ?, updated_at = ? WHERE run_id = ?", (state, reason, now(), run_id))
            else:
                db.execute("UPDATE runs SET state = ?, state_reason = ?, bundle_sha256 = ?, updated_at = ? WHERE run_id = ?",
                           (state, reason, bundle_sha256, now(), run_id))
        self.event(run_id, actor, "state_changed", {"state": state, "reason": reason, "bundle_sha256": bundle_sha256})

    # ------------------------------------------------------------------ decisions and releases

    def add_decision(self, run_id: str, reviewer: str, decision: str, notes: str, bundle_sha256: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO decisions (run_id, reviewer, decision, notes, bundle_sha256, os_user, decided_at) VALUES (?,?,?,?,?,?,?)",
                       (run_id, reviewer, decision, notes, bundle_sha256, os_user(), now()))
        self.event(run_id, f"reviewer:{reviewer}", f"review_{decision}", {"notes": notes, "bundle_sha256": bundle_sha256})

    def decisions(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM decisions WHERE run_id = ? ORDER BY id", (run_id,))]

    def add_release(self, run_id: str, bundle_sha256: str, channel: str, external_ref: str, released_by: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO releases (run_id, bundle_sha256, channel, external_ref, released_by, released_at) VALUES (?,?,?,?,?,?)",
                       (run_id, bundle_sha256, channel, external_ref, released_by, now()))
        self.event(run_id, released_by, "released", {"channel": channel, "external_ref": external_ref, "bundle_sha256": bundle_sha256})

    def releases(self, run_id: str) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM releases WHERE run_id = ? ORDER BY id", (run_id,))]

    # ------------------------------------------------------------------ audit log

    def event(self, run_id: str | None, actor: str, kind: str, detail: dict) -> None:
        body = json.dumps(detail, sort_keys=True, default=str)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev = last["hash"] if last else "GENESIS"
            ts = now()
            digest = hashlib.sha256(json.dumps([prev, ts, run_id, actor, kind, body]).encode()).hexdigest()
            db.execute("INSERT INTO events (ts, run_id, actor, kind, detail, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
                       (ts, run_id, actor, kind, body, prev, digest))
            db.execute("COMMIT")

    def events(self, run_id: str | None = None, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            if run_id:
                rows = db.execute("SELECT * FROM events WHERE run_id = ? ORDER BY id DESC LIMIT ?", (run_id, limit))
            else:
                rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in rows]

    def verify_audit_chain(self) -> list[str]:
        """Recompute every hash. Any edit or deletion in the middle of the log breaks the chain."""
        problems, prev = [], "GENESIS"
        with self.connect() as db:
            for row in db.execute("SELECT * FROM events ORDER BY id"):
                expected = hashlib.sha256(json.dumps([prev, row["ts"], row["run_id"], row["actor"], row["kind"], row["detail"]]).encode()).hexdigest()
                if row["prev_hash"] != prev or row["hash"] != expected:
                    problems.append(f"event {row['id']} does not match the chain")
                prev = row["hash"]
        return problems


def default_store() -> Store:
    from monthend.config import var_dir

    return Store(var_dir() / "monthend.db")
