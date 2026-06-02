"""
AgentOps — Seed script
Registers SOP Deviation Review with realistic Phase 1 data:
  - Agent record (In Production stage, reflecting current reality)
  - Version 1.0.0 snapshot
  - Eval result from the live framework (87% pass rate, 6.67/8.0 avg)
  - 7 days of cost data (sample, matches analytics dashboard figures)
  - Lifecycle history mirroring the real approval path
  - Audit log entries for each governance action
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import db, init_db
import json
from datetime import datetime, timedelta

AGENT_ID = "sop-deviation-review"

def seed():
    init_db()

    with db() as conn:
        existing = conn.execute("SELECT id FROM agents WHERE id=?", (AGENT_ID,)).fetchone()
        if existing:
            print(f"Agent '{AGENT_ID}' already exists — skipping seed.")
            return

        now = datetime.utcnow()

        # ── 1. Register agent ──────────────────────────────────────────────
        conn.execute(
            """INSERT INTO agents(id, name, description, owner, classification, current_stage, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "SOP Deviation Review Assistant",
                "Pharmaceutical GMP deviation-review agent. Classifies deviation severity, "
                "identifies applicable SOPs, recommends CAPA actions, and escalates by default "
                "when evidence is ambiguous.",
                "Quality Assurance / Krishna Paruchuri",
                json.dumps({
                    "pii_access": False,
                    "production_critical": True,
                    "regulated_domain": True,
                    "data_classification": "confidential",
                    "escalates_to_human": True,
                }),
                "In Production",
                (now - timedelta(days=30)).isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            ),
        )

        # ── 2. Register version 1.0.0 ─────────────────────────────────────
        conn.execute(
            """INSERT INTO agent_versions(agent_id, version, model, config_snapshot, created_at, created_by)
               VALUES (?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "1.0.0",
                "claude-haiku-4-5",
                json.dumps({
                    "retrieval": "TF-IDF over 5 SOPs",
                    "output_format": "structured JSON, 7 fields",
                    "tool_use": "forced",
                    "fallback": "escalate by default",
                    "retry_policy": "retry-with-validation on parse error",
                }),
                (now - timedelta(days=30)).isoformat(timespec="seconds"),
                "Krishna Paruchuri",
            ),
        )

        # ── 3. Lifecycle history ───────────────────────────────────────────
        transitions = [
            (None,             "Proposed",         "Krishna Paruchuri", "Initial agent registration",         -30),
            ("Proposed",       "Under Review",     "Krishna Paruchuri", "Submitted for governance review",    -28),
            ("Under Review",   "Approved",         "Governance Lead",   "Eval results meet threshold. Approved for production.", -20),
            ("Approved",       "In Production",    "Governance Lead",   "Deployment approved. Live as of today.", -15),
        ]
        for (frm, to, by, reason, days_ago) in transitions:
            conn.execute(
                "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason, transitioned_at) VALUES (?,?,?,?,?,?)",
                (AGENT_ID, frm, to, by, reason, (now + timedelta(days=days_ago)).isoformat(timespec="seconds")),
            )

        # ── 4. Eval result (live metrics from existing framework) ──────────
        conn.execute(
            """INSERT INTO eval_results(agent_id, version, run_at, run_by, pass_rate, avg_score, total_cases, passed_cases, threshold_met, dimensions)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "1.0.0",
                (now - timedelta(days=21)).isoformat(timespec="seconds"),
                "Krishna Paruchuri",
                0.87,        # 87% pass rate
                6.67,        # avg 6.67 / 8.0
                15,          # 15 golden cases
                13,          # 13 passed
                1,           # threshold met ✓
                json.dumps({
                    "groundedness": 7.2,
                    "classification": 6.8,
                    "escalation": 6.9,
                    "clarity": 5.9,
                    "baseline_pass_rate": 0.13,  # always-escalate baseline
                }),
            ),
        )

        # ── 5. Approval requests (historical) ─────────────────────────────
        # Under Review → Approved (with eval attached)
        conn.execute(
            """INSERT INTO approval_requests(agent_id, request_type, from_stage, to_stage, proposed_by, proposed_at, reviewed_by, reviewed_at, decision, reason, eval_result_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "promotion",
                "Under Review",
                "Approved",
                "Krishna Paruchuri",
                (now - timedelta(days=22)).isoformat(timespec="seconds"),
                "Governance Lead",
                (now - timedelta(days=20)).isoformat(timespec="seconds"),
                "approved",
                "Eval results exceed threshold (87% pass / 6.67 avg). Output quality reviewed across 15 golden cases. Escalation behavior verified. Approved for production deployment.",
                1,
            ),
        )
        # Approved → In Production
        conn.execute(
            """INSERT INTO approval_requests(agent_id, request_type, from_stage, to_stage, proposed_by, proposed_at, reviewed_by, reviewed_at, decision, reason, eval_result_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "promotion",
                "Approved",
                "In Production",
                "Krishna Paruchuri",
                (now - timedelta(days=16)).isoformat(timespec="seconds"),
                "Governance Lead",
                (now - timedelta(days=15)).isoformat(timespec="seconds"),
                "approved",
                "Production deployment approved. Monitoring dashboard confirmed. Cost tracking active.",
                None,
            ),
        )

        # ── 6. Cost records (last 7 days, realistic usage) ─────────────────
        # ~$0.0003 per review, ~50 reviews/day, claude-haiku-4-5 pricing
        daily_data = [
            # (days_ago, total_tokens, input_tokens, output_tokens, cost_usd, reviews)
            (1, 312000, 250000, 62000, 0.0156, 48),
            (2, 285000, 228000, 57000, 0.0143, 44),
            (3, 341000, 273000, 68000, 0.0171, 52),
            (4, 298000, 238000, 60000, 0.0149, 46),
            (5, 325000, 260000, 65000, 0.0163, 50),
            (6, 156000, 125000, 31000, 0.0078, 24),  # weekend
            (7, 143000, 114000, 29000, 0.0072, 22),  # weekend
        ]
        for (days_ago, tt, it, ot, cost, reviews) in daily_data:
            d = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            conn.execute(
                """INSERT OR IGNORE INTO cost_records(agent_id, recorded_date, total_tokens, input_tokens, output_tokens, cost_usd, review_count)
                   VALUES (?,?,?,?,?,?,?)""",
                (AGENT_ID, d, tt, it, ot, cost, reviews),
            )

        # ── 7. Audit log entries ───────────────────────────────────────────
        audit_events = [
            ("AGENT_REGISTERED",     "Krishna Paruchuri", -30, {"name": "SOP Deviation Review Assistant"}),
            ("VERSION_REGISTERED",   "Krishna Paruchuri", -30, {"version": "1.0.0", "model": "claude-haiku-4-5"}),
            ("STAGE_TRANSITION",     "Krishna Paruchuri", -28, {"from": None, "to": "Proposed"}),
            ("STAGE_TRANSITION",     "Krishna Paruchuri", -28, {"from": "Proposed", "to": "Under Review"}),
            ("EVAL_SUBMITTED",       "Krishna Paruchuri", -21, {"version": "1.0.0", "pass_rate": 0.87, "threshold_met": True}),
            ("APPROVAL_REQUESTED",   "Krishna Paruchuri", -22, {"type": "promotion", "from": "Under Review", "to": "Approved"}),
            ("APPROVAL_DECIDED",     "Governance Lead",   -20, {"decision": "approved", "reason": "Eval results exceed threshold"}),
            ("STAGE_TRANSITION",     "Governance Lead",   -20, {"from": "Under Review", "to": "Approved"}),
            ("APPROVAL_REQUESTED",   "Krishna Paruchuri", -16, {"type": "promotion", "from": "Approved", "to": "In Production"}),
            ("APPROVAL_DECIDED",     "Governance Lead",   -15, {"decision": "approved", "reason": "Production deployment approved"}),
            ("STAGE_TRANSITION",     "Governance Lead",   -15, {"from": "Approved", "to": "In Production"}),
        ]
        for (action, actor, days_ago, payload) in audit_events:
            conn.execute(
                "INSERT INTO audit_log(event_time, agent_id, actor, action, payload) VALUES (?,?,?,?,?)",
                (
                    (now + timedelta(days=days_ago)).isoformat(timespec="seconds"),
                    AGENT_ID,
                    actor,
                    action,
                    json.dumps(payload),
                ),
            )

    print(f"✓ Seeded agent '{AGENT_ID}' successfully.")
    print(f"  Stage: In Production")
    print(f"  Version: 1.0.0")
    print(f"  Eval: 87% pass / 6.67 avg / threshold met ✓")
    print(f"  Cost records: last 7 days")
    print(f"  Audit log: {len(audit_events)} entries")


if __name__ == "__main__":
    seed()
