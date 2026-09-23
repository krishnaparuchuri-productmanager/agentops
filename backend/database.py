"""
AgentOps — Database layer (SQLite, stdlib only, no ORM)
All writes to audit_log are INSERT-only. No UPDATE or DELETE ever touches that table.

Security notes:
  - audit_log is INSERT-only; no endpoint issues UPDATE/DELETE on it.
  - agent_id path params are always validated via _ensure_agent() before use.
  - Column names in UPDATE statements are built from a fixed dict keyset, not user input.
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
    status          TEXT NOT NULL DEFAULT 'draft', -- draft | active | rolled_back
    changelog       TEXT,                      -- what changed in this version
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

-- ─────────────────────────────────────────────
--  Execution traces — per-call record pushed from agent apps
--  (e.g. GMP Deviation Review pushes one row per /api/review call)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    trace_id        TEXT NOT NULL UNIQUE,              -- UUID from the source app
    timestamp       TEXT NOT NULL,                     -- ISO-8601 UTC
    user_input      TEXT,                              -- sanitised excerpt (first 500 chars)
    severity        TEXT,                              -- Critical | Major | Minor | null
    qa_escalation   INTEGER DEFAULT 0,                 -- 1 = escalated
    classification  TEXT,                              -- deviation classification label
    input_tokens    INTEGER DEFAULT 0,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        REAL DEFAULT 0.0,
    latency_ms      INTEGER DEFAULT 0,
    is_fallback     INTEGER DEFAULT 0,                 -- 1 = LLM returned safe fallback
    model_output    TEXT,                              -- JSON string of full LLM response
    source_app      TEXT,                              -- e.g. "sop-deviation-review"
    received_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
--  Agent alerts — policy violations, threshold breaches, rule failures
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     TEXT NOT NULL REFERENCES agents(id),
    alert_type   TEXT NOT NULL,   -- 'cost_threshold' | 'golden_rule_violation' | 'escalation_spike' | 'eval_degradation'
    severity     TEXT NOT NULL,   -- 'critical' | 'warning' | 'info'
    title        TEXT NOT NULL,
    message      TEXT NOT NULL,
    triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT,            -- NULL = still active
    resolved_by  TEXT,
    metadata     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_alerts_agent ON agent_alerts(agent_id, resolved_at);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_time  ON audit_log(event_time);
CREATE INDEX IF NOT EXISTS idx_approval_agent ON approval_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_cost_agent_date ON cost_records(agent_id, recorded_date);
CREATE INDEX IF NOT EXISTS idx_traces_agent ON agent_traces(agent_id, timestamp);
"""


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)


def migrate_db():
    """Safely add new columns / tables to existing DB without dropping data."""
    with db() as conn:
        existing_cols = [r[1] for r in conn.execute("PRAGMA table_info(agent_versions)").fetchall()]
        if "status" not in existing_cols:
            conn.execute("ALTER TABLE agent_versions ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'")
        if "changelog" not in existing_cols:
            conn.execute("ALTER TABLE agent_versions ADD COLUMN changelog TEXT")

        approval_cols = [r[1] for r in conn.execute("PRAGMA table_info(approval_requests)").fetchall()]
        if "notes" not in approval_cols:
            conn.execute("ALTER TABLE approval_requests ADD COLUMN notes TEXT")

        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]

        if "agent_alerts" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_alerts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id     TEXT NOT NULL,
                    alert_type   TEXT NOT NULL,
                    severity     TEXT NOT NULL,
                    title        TEXT NOT NULL,
                    message      TEXT NOT NULL,
                    triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
                    resolved_at  TEXT,
                    resolved_by  TEXT,
                    metadata     TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_alerts_agent ON agent_alerts(agent_id, resolved_at);
            """)

        # agent_traces table — created by init_db() if schema is fresh; add via DDL for
        # existing deployments that don't have it yet.
        if "agent_traces" not in tables:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_traces (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id        TEXT NOT NULL,
                    trace_id        TEXT NOT NULL UNIQUE,
                    timestamp       TEXT NOT NULL,
                    user_input      TEXT,
                    severity        TEXT,
                    qa_escalation   INTEGER DEFAULT 0,
                    classification  TEXT,
                    input_tokens    INTEGER DEFAULT 0,
                    output_tokens   INTEGER DEFAULT 0,
                    cost_usd        REAL DEFAULT 0.0,
                    latency_ms      INTEGER DEFAULT 0,
                    is_fallback     INTEGER DEFAULT 0,
                    model_output    TEXT,
                    source_app      TEXT,
                    received_at     TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_traces_agent ON agent_traces(agent_id, timestamp);
            """)

        _backfill_approver_names(conn)


# ─────────────────────────────────────────────────────────────────────────────
#  One-time data fix: replace placeholder maker/checker identities
#  ('seed-script', 'Governance Lead') on seeded approvals with named users,
#  keeping approval_requests, audit_log and lifecycle_transitions consistent.
#  Idempotent — only matches rows that still carry the placeholder values.
# ─────────────────────────────────────────────────────────────────────────────
_MAKERS = {
    "medassist-router":    "Anjali Mehta",
    "medassist-scheduler": "Anjali Mehta",
    "medassist-scribe":    "Dr. Michael Torres",
    "medassist-results":   "Dr. Michael Torres",
    "medassist-orders":    "Dr. Michael Torres",
    "medassist-billing":   "Anjali Mehta",
}
_CHECKERS = {  # (from_stage, to_stage) → checker
    ("Under Review",     "Approved"):         "Sarah Mitchell",
    ("Approved",         "Under Monitoring"): "Rajesh Iyer",
    ("Under Monitoring", "In Production"):    "Dr. Emily Chen",
}
_GMP_CHECKER = "Laura Bennett"
_COMMENTS = {  # (from_stage, to_stage) → (maker notes, checker reason)
    ("Under Review", "Approved"): (
        "Golden-set eval meets threshold. Guardrails and golden rules reviewed with clinical SMEs; "
        "PHI handling verified. Requesting approval to start shadow deployment.",
        "Eval evidence and guardrail coverage reviewed. Segregation of PHI confirmed. "
        "Approved for shadow deployment.",
    ),
    ("Approved", "Under Monitoring"): (
        "Shadow run complete — 2 weeks of mirrored traffic, no guardrail breaches. Cost alerts and "
        "monitoring dashboards configured. Requesting limited rollout under monitoring.",
        "Monitoring, alerting and rollback plan verified. Approved for limited rollout under monitoring.",
    ),
    ("Under Monitoring", "In Production"): (
        "Monitored rollout stable — latency, cost and escalation rates within targets; no open critical "
        "alerts. Requesting full production release.",
        "Clinical sign-off received and metrics reviewed against SLOs. Approved for full production "
        "with weekly eval regression.",
    ),
}


def _backfill_approver_names(conn):
    rows = conn.execute(
        "SELECT id, agent_id, from_stage, to_stage FROM approval_requests WHERE proposed_by='seed-script'"
    ).fetchall()
    for req_id, agent_id, frm, to in rows:
        maker = _MAKERS.get(agent_id, "Anjali Mehta")
        checker = _CHECKERS.get((frm, to), "Sarah Mitchell")
        notes, reason = _COMMENTS.get((frm, to), (None, None))
        conn.execute(
            """UPDATE approval_requests
               SET proposed_by=?, notes=COALESCE(?, notes),
                   reviewed_by=CASE WHEN reviewed_by='seed-script' THEN ? ELSE reviewed_by END,
                   reason=CASE WHEN reviewed_by='seed-script' THEN COALESCE(?, reason) ELSE reason END
               WHERE id=?""",
            (maker, notes, checker, reason, req_id),
        )
        _backfill_audit(conn, agent_id, req_id, frm, to, maker, checker, notes, reason, "seed-script")
        conn.execute(
            """UPDATE lifecycle_transitions SET triggered_by=?
               WHERE agent_id=? AND from_stage=? AND to_stage=? AND triggered_by IN ('seed-script', 'Governance Lead')""",
            (checker, agent_id, frm, to),
        )

    # Remaining seeded actions with no approval (registration, Proposed → Under Review)
    # were performed by the agent's owner, i.e. the maker.
    for agent_id, maker in _MAKERS.items():
        conn.execute("UPDATE audit_log SET actor=? WHERE agent_id=? AND actor='seed-script'", (maker, agent_id))
        conn.execute(
            "UPDATE lifecycle_transitions SET triggered_by=? WHERE agent_id=? AND triggered_by='seed-script'",
            (maker, agent_id),
        )

    gmp = conn.execute(
        """SELECT id, from_stage, to_stage FROM approval_requests
           WHERE agent_id='gmp-deviation-review' AND reviewed_by='Governance Lead'"""
    ).fetchall()
    for req_id, frm, to in gmp:
        conn.execute("UPDATE approval_requests SET reviewed_by=? WHERE id=?", (_GMP_CHECKER, req_id))
        _backfill_audit(conn, "gmp-deviation-review", req_id, frm, to, None, _GMP_CHECKER, None, None, "Governance Lead")
        conn.execute(
            """UPDATE lifecycle_transitions SET triggered_by=?
               WHERE agent_id='gmp-deviation-review' AND from_stage=? AND to_stage=? AND triggered_by='Governance Lead'""",
            (_GMP_CHECKER, frm, to),
        )


def _backfill_audit(conn, agent_id, req_id, frm, to, maker, checker, notes, reason, placeholder):
    import json

    events = conn.execute(
        """SELECT id, action, payload FROM audit_log
           WHERE agent_id=? AND actor=? AND action IN ('APPROVAL_REQUESTED', 'APPROVAL_DECIDED', 'STAGE_TRANSITION')""",
        (agent_id, placeholder),
    ).fetchall()
    for ev_id, action, raw in events:
        try:
            p = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if action == "APPROVAL_REQUESTED" and p.get("request_id") == req_id and maker:
            if notes:
                p["notes"] = notes
            conn.execute("UPDATE audit_log SET actor=?, payload=? WHERE id=?", (maker, json.dumps(p), ev_id))
        elif action == "APPROVAL_DECIDED" and p.get("request_id") == req_id:
            if reason:
                p["reason"] = reason
            conn.execute("UPDATE audit_log SET actor=?, payload=? WHERE id=?", (checker, json.dumps(p), ev_id))
        elif action == "STAGE_TRANSITION" and p.get("from") == frm and p.get("to") == to:
            conn.execute("UPDATE audit_log SET actor=? WHERE id=?", (checker, ev_id))
