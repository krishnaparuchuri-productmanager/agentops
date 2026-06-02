"""
AgentOps — Database layer (SQLite, stdlib only, no ORM)
All writes to audit_log are INSERT-only. No UPDATE or DELETE ever touches that table.
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("AGENTOPS_DB", "agentops.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
-- ─────────────────────────────────────────────
--  Core registry
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,          -- e.g. "sop-deviation-review"
    name            TEXT NOT NULL,
    description     TEXT,
    owner           TEXT NOT NULL,             -- team / person accountable
    classification  TEXT NOT NULL DEFAULT '{}', -- JSON: {pii_access, production_critical, ...}
    current_stage   TEXT NOT NULL DEFAULT 'Proposed',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
--  Versioned snapshots — one row per version
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    version         TEXT NOT NULL,             -- semver string e.g. "1.0.0"
    model           TEXT,                      -- e.g. "claude-haiku-4-5"
    config_snapshot TEXT,                      -- JSON dump of agent config at this version
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    created_by      TEXT NOT NULL,
    UNIQUE(agent_id, version)
);

-- ─────────────────────────────────────────────
--  Lifecycle transitions (every stage change recorded)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lifecycle_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    from_stage      TEXT,
    to_stage        TEXT NOT NULL,
    triggered_by    TEXT NOT NULL,             -- user / role
    reason          TEXT,
    transitioned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
--  Maker-checker approval requests
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approval_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    request_type    TEXT NOT NULL,             -- 'promotion' | 'retirement'
    from_stage      TEXT NOT NULL,
    to_stage        TEXT NOT NULL,
    proposed_by     TEXT NOT NULL,             -- maker
    proposed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_by     TEXT,                      -- checker (NULL until decided)
    reviewed_at     TEXT,
    decision        TEXT,                      -- 'approved' | 'rejected' | NULL (pending)
    reason          TEXT,                      -- checker's reason
    eval_result_id  INTEGER REFERENCES eval_results(id)  -- required for Approved promotions
);

-- ─────────────────────────────────────────────
--  Eval results — one row per eval run
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    version         TEXT NOT NULL,
    run_at          TEXT NOT NULL DEFAULT (datetime('now')),
    run_by          TEXT NOT NULL,
    pass_rate       REAL NOT NULL,             -- 0.0–1.0
    avg_score       REAL NOT NULL,             -- e.g. 6.67 / 8.0
    total_cases     INTEGER NOT NULL,
    passed_cases    INTEGER NOT NULL,
    threshold_met   INTEGER NOT NULL,          -- 1 = yes, 0 = no  (gate)
    dimensions      TEXT NOT NULL DEFAULT '{}' -- JSON: per-dimension scores
);

-- ─────────────────────────────────────────────
--  Cost tracking — per-agent daily rollup
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cost_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    recorded_date   TEXT NOT NULL,             -- YYYY-MM-DD
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    review_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(agent_id, recorded_date)
);

-- ─────────────────────────────────────────────
--  Immutable audit log — INSERT ONLY, never UPDATE/DELETE
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time      TEXT NOT NULL DEFAULT (datetime('now')),
    agent_id        TEXT,
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,             -- e.g. "STAGE_TRANSITION", "APPROVAL_REQUESTED"
    payload         TEXT NOT NULL DEFAULT '{}' -- JSON with full before/after context
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_time  ON audit_log(event_time);
CREATE INDEX IF NOT EXISTS idx_approval_agent ON approval_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_cost_agent_date ON cost_records(agent_id, recorded_date);
"""


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
