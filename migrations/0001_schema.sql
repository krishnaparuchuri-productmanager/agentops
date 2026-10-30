-- AgentOps — D1 schema (port of backend/database.py SCHEMA + migrate_db columns)
-- audit_log is INSERT-only; no endpoint issues UPDATE/DELETE on it.

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
    eval_result_id  INTEGER REFERENCES eval_results(id),  -- required for Approved promotions
    notes           TEXT                       -- maker's comment / rationale
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

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_alerts_agent ON agent_alerts(agent_id, resolved_at);
CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_time  ON audit_log(event_time);
CREATE INDEX IF NOT EXISTS idx_approval_agent ON approval_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_cost_agent_date ON cost_records(agent_id, recorded_date);
CREATE INDEX IF NOT EXISTS idx_traces_agent ON agent_traces(agent_id, timestamp);
