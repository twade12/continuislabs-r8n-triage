"""SQLite-backed audit log, codex KB, and operational state for hgm-web.

Schema is intentionally minimal — every table is queried via small typed
helpers below rather than via an ORM. The diagnosis/symptom blobs are
stored as JSON in TEXT columns; SQLite's json1 functions make them
queryable enough for this scale.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_default_db = Path(__file__).resolve().parent / "hgm-web.sqlite"
DB_PATH = Path(os.environ.get("DB_PATH", str(_default_db)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS triage_sessions (
  id              TEXT PRIMARY KEY,
  ts              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  iccid           TEXT,
  vendor          TEXT,
  module          TEXT,
  raw_log         TEXT NOT NULL,
  customer_msg    TEXT,
  diagnosis_json  TEXT NOT NULL,
  top_rule_id     TEXT,
  top_confidence  TEXT,
  reply_drafted   TEXT,
  reply_sent      TEXT,
  outcome         TEXT,
  outcome_cause   TEXT,
  ticket_ref      TEXT
);

CREATE INDEX IF NOT EXISTS idx_triage_ts ON triage_sessions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_triage_rule ON triage_sessions(top_rule_id);
CREATE INDEX IF NOT EXISTS idx_triage_vendor ON triage_sessions(vendor, module);

CREATE TABLE IF NOT EXISTS codex_entries (
  id                TEXT PRIMARY KEY,
  source_session_id TEXT,
  title             TEXT NOT NULL,
  vendor            TEXT,
  module            TEXT,
  carrier           TEXT,
  rat               TEXT,
  symptom_tags      TEXT,
  diagnosis         TEXT,
  fix               TEXT,
  upvotes           INTEGER DEFAULT 0,
  created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  ticket_refs       TEXT
);

CREATE INDEX IF NOT EXISTS idx_codex_vendor ON codex_entries(vendor, module);
CREATE INDEX IF NOT EXISTS idx_codex_created ON codex_entries(created_at DESC);

CREATE TABLE IF NOT EXISTS bulk_operations (
  id            TEXT PRIMARY KEY,
  ts            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  op_type       TEXT,
  target_count  INTEGER,
  details_json  TEXT
);

CREATE TABLE IF NOT EXISTS conductor_policies (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  scope            TEXT,
  rule             TEXT,
  enabled          INTEGER DEFAULT 1,
  triggered_count  INTEGER DEFAULT 0,
  created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conductor_switches (
  id           TEXT PRIMARY KEY,
  ts           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  iccid        TEXT,
  old_profile  TEXT,
  new_profile  TEXT,
  trigger      TEXT
);
"""


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.execute("PRAGMA journal_mode=WAL")  # safe for single-worker; prevents reader/writer contention
        c.executescript(SCHEMA)


def new_id() -> str:
    return str(uuid.uuid4())


# ---- triage sessions ---------------------------------------------------


def save_triage(
    *,
    raw_log: str,
    customer_msg: str | None,
    iccid: str | None,
    vendor: str | None,
    module: str | None,
    diagnosis: dict,
    reply_drafted: str | None,
) -> str:
    sid = new_id()
    top = (diagnosis.get("hypotheses") or [{}])[0]
    with conn() as c:
        c.execute(
            """
            INSERT INTO triage_sessions
              (id, iccid, vendor, module, raw_log, customer_msg,
               diagnosis_json, top_rule_id, top_confidence, reply_drafted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sid, iccid, vendor, module, raw_log, customer_msg,
                json.dumps(diagnosis), top.get("rule_id"), top.get("confidence"),
                reply_drafted,
            ),
        )
    return sid


def list_triage(limit: int = 100, offset: int = 0, rule_id: str | None = None) -> list[dict]:
    with conn() as c:
        if rule_id:
            rows = c.execute(
                "SELECT * FROM triage_sessions WHERE top_rule_id = ? "
                "ORDER BY ts DESC LIMIT ? OFFSET ?",
                (rule_id, limit, offset),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM triage_sessions ORDER BY ts DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def get_triage(sid: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM triage_sessions WHERE id = ?", (sid,)).fetchone()
        return _row_to_dict(row) if row else None


def update_triage_outcome(sid: str, outcome: str, cause: str | None, ticket_ref: str | None) -> None:
    with conn() as c:
        c.execute(
            "UPDATE triage_sessions SET outcome = ?, outcome_cause = ?, ticket_ref = ? WHERE id = ?",
            (outcome, cause, ticket_ref, sid),
        )


def aggregate_by_rule(days: int = 7) -> list[dict]:
    """Return counts grouped by top_rule_id over the last N days."""
    with conn() as c:
        rows = c.execute(
            """
            SELECT top_rule_id, COUNT(*) as n
            FROM triage_sessions
            WHERE ts >= datetime('now', ? || ' days')
              AND top_rule_id IS NOT NULL
            GROUP BY top_rule_id
            ORDER BY n DESC
            """,
            (f"-{days}",),
        ).fetchall()
        return [{"rule_id": r["top_rule_id"], "count": r["n"]} for r in rows]


def aggregate_by_module() -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """
            SELECT vendor, module, COUNT(*) as n,
                   SUM(CASE WHEN top_rule_id NOT IN ('healthy_baseline', 'appears_attached', 'unknown') THEN 1 ELSE 0 END) AS faults
            FROM triage_sessions
            WHERE vendor IS NOT NULL
            GROUP BY vendor, module
            ORDER BY n DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


# ---- codex KB ----------------------------------------------------------


def save_codex(
    *,
    title: str,
    vendor: str | None,
    module: str | None,
    carrier: str | None,
    rat: str | None,
    symptom_tags: list[str],
    diagnosis: str,
    fix: str,
    source_session_id: str | None = None,
    ticket_refs: list[str] | None = None,
) -> str:
    cid = new_id()
    with conn() as c:
        c.execute(
            """
            INSERT INTO codex_entries
              (id, source_session_id, title, vendor, module, carrier, rat,
               symptom_tags, diagnosis, fix, ticket_refs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid, source_session_id, title, vendor, module, carrier, rat,
                json.dumps(symptom_tags), diagnosis, fix,
                json.dumps(ticket_refs or []),
            ),
        )
    return cid


def list_codex(
    *,
    vendor: str | None = None,
    module: str | None = None,
    symptom: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[dict]:
    sql = "SELECT * FROM codex_entries WHERE 1=1"
    args: list[Any] = []
    if vendor:
        sql += " AND vendor = ?"
        args.append(vendor)
    if module:
        sql += " AND module = ?"
        args.append(module)
    if symptom:
        sql += " AND symptom_tags LIKE ?"
        args.append(f"%{symptom}%")
    if q:
        sql += " AND (title LIKE ? OR diagnosis LIKE ? OR fix LIKE ?)"
        args.extend([f"%{q}%"] * 3)
    sql += " ORDER BY upvotes DESC, created_at DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        rows = c.execute(sql, args).fetchall()
        return [_codex_row(r) for r in rows]


def get_codex(cid: str) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM codex_entries WHERE id = ?", (cid,)).fetchone()
        return _codex_row(row) if row else None


def upvote_codex(cid: str) -> None:
    with conn() as c:
        c.execute("UPDATE codex_entries SET upvotes = upvotes + 1 WHERE id = ?", (cid,))


def find_similar_codex(
    *,
    vendor: str | None,
    module: str | None,
    rule_id: str | None,
    limit: int = 3,
) -> list[dict]:
    """Heuristic similarity: same vendor/module + rule_id appears in symptom_tags."""
    if vendor is None and rule_id is None:
        return []
    sql = "SELECT * FROM codex_entries WHERE 1=1"
    args: list[Any] = []
    if vendor:
        sql += " AND (vendor = ? OR vendor IS NULL)"
        args.append(vendor)
    if module:
        sql += " AND (module = ? OR module IS NULL)"
        args.append(module)
    if rule_id:
        sql += " AND symptom_tags LIKE ?"
        args.append(f"%{rule_id}%")
    sql += " ORDER BY upvotes DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        rows = c.execute(sql, args).fetchall()
        return [_codex_row(r) for r in rows]


# ---- bulk operations ---------------------------------------------------


def save_bulk_op(op_type: str, target_count: int, details: dict) -> str:
    bid = new_id()
    with conn() as c:
        c.execute(
            "INSERT INTO bulk_operations (id, op_type, target_count, details_json) VALUES (?, ?, ?, ?)",
            (bid, op_type, target_count, json.dumps(details)),
        )
    return bid


def list_bulk_ops(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM bulk_operations ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {**dict(r), "details": json.loads(r["details_json"])}
            for r in rows
        ]


# ---- conductor ---------------------------------------------------------


def save_policy(name: str, scope: str, rule: str) -> str:
    pid = new_id()
    with conn() as c:
        c.execute(
            "INSERT INTO conductor_policies (id, name, scope, rule) VALUES (?, ?, ?, ?)",
            (pid, name, scope, rule),
        )
    return pid


def list_policies() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM conductor_policies ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def toggle_policy(pid: str) -> None:
    with conn() as c:
        c.execute("UPDATE conductor_policies SET enabled = 1 - enabled WHERE id = ?", (pid,))


def save_switch(iccid: str, old_profile: str, new_profile: str, trigger: str) -> str:
    sid = new_id()
    with conn() as c:
        c.execute(
            "INSERT INTO conductor_switches (id, iccid, old_profile, new_profile, trigger) VALUES (?, ?, ?, ?, ?)",
            (sid, iccid, old_profile, new_profile, trigger),
        )
    return sid


def list_switches(limit: int = 30) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM conductor_switches ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---- internals ---------------------------------------------------------


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    if d.get("diagnosis_json"):
        d["diagnosis"] = json.loads(d["diagnosis_json"])
    return d


def _codex_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["symptom_tags"] = json.loads(d.get("symptom_tags") or "[]")
    d["ticket_refs"] = json.loads(d.get("ticket_refs") or "[]")
    return d
