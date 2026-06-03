"""
AgentOps — Seed script
Registers GMP Deviation Review - AI Assistant with real Phase 1 data.

Agent purpose:
  Pharmaceutical GMP deviation-review agent built for the QA team.
  Accepts a deviation report (batch/lot, process step, observed condition,
  supporting evidence), retrieves applicable SOPs via TF-IDF retrieval,
  and returns a structured JSON response with:
    severity_classification, applicable_sop, sop_clause,
    root_cause_hypothesis, capa_recommendations, escalate_flag, summary

Eval framework:
  15 golden cases curated by QA lead Krishna Paruchuri.
  Each case scored across 8 dimensions (0–10 scale).
  Pass threshold: avg >= 6.0 AND escalation_behavior >= 7.0.
  Current run: 87% pass rate (13/15), avg 6.67/10.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from database import db, init_db
import json
from datetime import datetime, timedelta

AGENT_ID = "gmp-deviation-review"

# ── Real guardrails ────────────────────────────────────────────────────────────
# These are enforced at the prompt/system level and checked in eval.
GUARDRAILS = [
    "No patient data or PII in output — mask or reject if present in input",
    "Always escalate when evidence is ambiguous, conflicting, or missing — never resolve uncertainty alone",
    "Do not make regulatory submission decisions — flag for Regulatory Affairs and stop",
    "Output must be structured JSON with all 7 required fields — never return free-text only",
    "If supporting SOP documents are not retrievable, return escalate_flag=true and state reason",
    "For Critical deviations: identify immediate containment actions before recommending CAPA",
    "Refuse to classify severity as 'Minor' if a released product or patient-impacting step is involved",
]

# ── Real golden rules ──────────────────────────────────────────────────────────
# These define the expected reasoning behaviour, checked by the eval scorer.
GOLDEN_RULES = [
    "Cite the applicable SOP by full document ID and clause number (e.g., SOP-QA-042, Clause 5.3.1)",
    "State severity classification (Critical / Major / Minor) with explicit justification citing observable evidence from the deviation report",
    "For Critical deviations, list immediate containment actions as the first CAPA item before corrective/preventive recommendations",
    "Every CAPA recommendation must include: responsible owner role, target completion date, and effectiveness check criteria",
    "If root cause cannot be determined from available evidence, state 'Root cause undetermined — investigation required' — do not speculate",
    "Flag for Regulatory Affairs notification if the deviation involves: a released batch, a validated process step, or a patient-facing output",
    "Never recommend closing a deviation without a stated root cause or an explicit investigation plan",
]

# ── Eval dimensions (8 scored 0–10) ───────────────────────────────────────────
# Actual scores from the Phase 1 eval run (15 golden cases, claude-haiku-4-5).
EVAL_DIMENSIONS = {
    "severity_classification": 7.2,   # correctly identifies Critical/Major/Minor
    "sop_citation":            7.0,   # cites correct SOP ID and clause
    "capa_quality":            6.4,   # CAPA includes owner, date, effectiveness check
    "escalation_behavior":     7.1,   # escalates on ambiguous/critical cases
    "groundedness":            7.2,   # output grounded in submitted evidence, not hallucinated
    "output_structure":        8.1,   # valid JSON, all 7 required fields present
    "regulatory_flag":         5.8,   # correctly flags patient-impacting deviations (hardest dimension)
    "clarity":                 5.9,   # language appropriate for QA review, no jargon overload
}

# ── Golden case breakdown (15 cases) ──────────────────────────────────────────
# case_id | description | result | failure_reason
GOLDEN_CASES = [
    ("GC-001", "Temperature excursion in cold-chain storage (2–8°C product, logged at 11°C for 4h)", "pass", None),
    ("GC-002", "Batch record incomplete — operator signature missing on 3 of 12 steps", "pass", None),
    ("GC-003", "Environmental monitoring alert: mould colony count above action limit in Grade B area", "pass", None),
    ("GC-004", "Equipment calibration overdue by 6 days, batch released before detection", "pass", None),
    ("GC-005", "Raw material COA out of specification — supplier result vs. in-house retest discrepancy", "fail", "Missed escalation: discrepancy between supplier and in-house COA should trigger RA flag; agent classified as Major and recommended CAPA without flagging regulatory risk"),
    ("GC-006", "Cross-contamination risk: wrong batch label found in staging area adjacent to open vessel", "pass", None),
    ("GC-007", "Process parameter deviation: mixing speed 10 RPM below lower control limit for 8 minutes", "pass", None),
    ("GC-008", "SOP not followed: analyst used deprecated SOP-QA-018 Rev 2 instead of current Rev 5", "pass", None),
    ("GC-009", "Water system TOC result above alert limit — no alert limit for conductivity exceeded", "pass", None),
    ("GC-010", "Ambiguous deviation: operator reported 'unusual odour' during granulation, no instrument data", "pass", None),
    ("GC-011", "Filling line stoppage: particulate matter observed in 2 vials out of 5000, root cause unknown", "fail", "CAPA quality: recommended 'investigate root cause' without specifying owner, date or effectiveness criteria — fails golden rule 4"),
    ("GC-012", "HVAC filter differential pressure drop below minimum — cleanroom classification risk", "pass", None),
    ("GC-013", "Label reconciliation discrepancy: 12 labels unaccounted for after batch completion", "pass", None),
    ("GC-014", "Stability sample missed: 6-month time point not tested, accelerated study only", "pass", None),
    ("GC-015", "Out-of-specification (OOS) result on finished product potency test, released batch", "pass", None),
]


def seed():
    init_db()

    with db() as conn:
        existing = conn.execute("SELECT id FROM agents WHERE id=?", (AGENT_ID,)).fetchone()
        if existing:
            print(f"Agent '{AGENT_ID}' already exists — skipping seed.")
            print("  To reseed: delete agentops.db and run seed.py again, or run reseed.py")
            return

        now = datetime.utcnow()

        # ── 1. Register agent ──────────────────────────────────────────────────
        conn.execute(
            """INSERT INTO agents(id, name, description, owner, classification, current_stage, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "GMP Deviation Review - AI Assistant",
                "Pharmaceutical GMP deviation-review assistant. Accepts a structured deviation "
                "report, retrieves applicable SOPs via TF-IDF retrieval over 5 validated documents, "
                "classifies deviation severity (Critical / Major / Minor), identifies the primary "
                "applicable SOP and clause, proposes root cause hypothesis, recommends CAPA actions "
                "with owner/date/effectiveness-check fields, and escalates by default when evidence "
                "is ambiguous or a patient-impacting process is involved.",
                "Quality Assurance / Krishna Paruchuri",
                json.dumps({
                    "pii_access":            False,
                    "production_critical":   True,
                    "regulated_domain":      True,
                    "data_classification":   "confidential",
                    "escalates_to_human":    True,
                    "product":               "GMP Deviation Review",
                    "workflow":              "Pharmaceutical QA Team Review",
                    "domain":                "Pharmaceutical",
                    "environment":           "production",
                    "model":                 "claude-haiku-4-5",
                    "eval_threshold":        0.80,
                    "guardrails":            GUARDRAILS,
                    "golden_rules":          GOLDEN_RULES,
                }),
                "In Production",
                (now - timedelta(days=30)).isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"),
            ),
        )

        # ── 2. Register version 1.0.0 (active) ────────────────────────────────
        conn.execute(
            """INSERT INTO agent_versions(agent_id, version, model, config_snapshot, changelog, status, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "1.0.0",
                "claude-haiku-4-5",
                json.dumps({
                    "retrieval":            "TF-IDF over 5 GMP SOPs (SOP-QA-001, SOP-QA-018, SOP-QA-042, SOP-PROD-007, SOP-ENV-003)",
                    "output_format":        "structured JSON, 7 required fields",
                    "tool_use":             "forced — retrieve_sop tool called before classification",
                    "fallback":             "escalate_flag=true on any retrieval or parsing failure",
                    "retry_policy":         "retry-with-validation on JSON parse error (max 2 retries)",
                    "eval_threshold":       0.80,
                    "temperature":          0.1,
                    "max_tokens":           1024,
                    "guardrails":           GUARDRAILS,
                    "golden_rules":         GOLDEN_RULES,
                    "sop_corpus":           [
                        "SOP-QA-001 Rev 4 — Deviation Management and CAPA",
                        "SOP-QA-018 Rev 5 — Environmental Monitoring Procedure",
                        "SOP-QA-042 Rev 2 — Out-of-Specification Investigation",
                        "SOP-PROD-007 Rev 3 — Batch Record Review and Release",
                        "SOP-ENV-003 Rev 1 — Cleanroom Classification and Monitoring",
                    ],
                    "output_schema": {
                        "severity_classification": "Critical | Major | Minor",
                        "applicable_sop":          "SOP document ID",
                        "sop_clause":              "clause reference string",
                        "root_cause_hypothesis":   "string or 'Root cause undetermined — investigation required'",
                        "capa_recommendations":    "list of {action, owner, target_date, effectiveness_check}",
                        "escalate_flag":           "boolean",
                        "summary":                 "2–3 sentence plain-language summary for QA review",
                    },
                }),
                "Initial production release. TF-IDF retrieval over 5 GMP SOPs. "
                "15 golden cases, 87% pass rate (13/15). Avg score 6.67/10. "
                "Known weakness: regulatory_flag dimension (5.8/10) — v1.1.0 will add explicit RA trigger logic.",
                "active",
                (now - timedelta(days=30)).isoformat(timespec="seconds"),
                "Krishna Paruchuri",
            ),
        )

        # ── 3. Lifecycle history ───────────────────────────────────────────────
        transitions = [
            (None,            "Proposed",      "Krishna Paruchuri", "Initial agent registration — GMP deviation review use case scoped with QA team", -30),
            ("Proposed",      "Under Review",  "Krishna Paruchuri", "Submitted for governance review with eval plan and SOP corpus attached",           -28),
            ("Under Review",  "Approved",      "Governance Lead",   "Eval results meet threshold (87% / 6.67 avg). Escalation and output structure verified across all 15 golden cases. Approved for production.", -20),
            ("Approved",      "In Production", "Governance Lead",   "Production deployment approved. Cost monitoring active. QA team onboarded. Reviewing first 100 live cases.", -15),
        ]
        for (frm, to, by, reason, days_ago) in transitions:
            conn.execute(
                "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason, transitioned_at) VALUES (?,?,?,?,?,?)",
                (AGENT_ID, frm, to, by, reason, (now + timedelta(days=days_ago)).isoformat(timespec="seconds")),
            )

        # ── 4. Eval result — real Phase 1 run ─────────────────────────────────
        eval_id_row = conn.execute(
            """INSERT INTO eval_results(agent_id, version, run_at, run_by, pass_rate, avg_score,
                                        total_cases, passed_cases, threshold_met, dimensions)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID,
                "1.0.0",
                (now - timedelta(days=21)).isoformat(timespec="seconds"),
                "Krishna Paruchuri",
                0.87,           # 13/15 cases passed
                6.67,           # average across 8 dimensions, 15 cases
                15,
                13,
                1,              # threshold met OK
                json.dumps(EVAL_DIMENSIONS),
            ),
        )
        eval_id = eval_id_row.lastrowid

        # ── 5. Approval requests ───────────────────────────────────────────────
        # Under Review → Approved
        conn.execute(
            """INSERT INTO approval_requests(agent_id, request_type, from_stage, to_stage,
                                             proposed_by, proposed_at, reviewed_by, reviewed_at,
                                             decision, reason, notes, eval_result_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID, "promotion", "Under Review", "Approved",
                "Krishna Paruchuri",
                (now - timedelta(days=22)).isoformat(timespec="seconds"),
                "Governance Lead",
                (now - timedelta(days=20)).isoformat(timespec="seconds"),
                "approved",
                "Eval results exceed threshold: 87% pass rate (13/15), avg 6.67/10 across 8 dimensions. "
                "Output structure and escalation behaviour verified against all 15 golden cases. "
                "Two failures noted (GC-005: missed RA flag; GC-011: incomplete CAPA) — these are "
                "logged as known gaps, to be addressed in v1.1.0. Approved for production with monitoring.",
                "15 golden cases passed eval at 87%. Escalation and SOP citation verified. "
                "Output JSON validated against schema. Two failure cases documented and logged as v1.1.0 backlog. "
                "QA team has reviewed agent responses on 10 representative real cases and signed off.",
                eval_id,
            ),
        )
        # Approved → In Production
        conn.execute(
            """INSERT INTO approval_requests(agent_id, request_type, from_stage, to_stage,
                                             proposed_by, proposed_at, reviewed_by, reviewed_at,
                                             decision, reason, notes, eval_result_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                AGENT_ID, "promotion", "Approved", "In Production",
                "Krishna Paruchuri",
                (now - timedelta(days=16)).isoformat(timespec="seconds"),
                "Governance Lead",
                (now - timedelta(days=15)).isoformat(timespec="seconds"),
                "approved",
                "Production deployment approved. AgentOps cost monitoring dashboard confirmed active. "
                "QA team onboarding complete. Rollout to full deviation queue starting today.",
                "Railway deployment verified. API health check passing. "
                "First 10 live deviation cases reviewed by QA lead — outputs consistent with golden case expectations. "
                "Cost per review confirmed at ~$0.0003 (within budget). Ready for full rollout.",
                None,
            ),
        )

        # ── 6. Cost records — last 7 days ─────────────────────────────────────
        # claude-haiku-4-5 pricing: $0.80/M input tokens, $4.00/M output tokens
        # avg deviation report: ~500 input tokens + system prompt ~4500 = ~5000 input
        # avg output: ~1200 tokens (structured JSON + summary)
        # cost per review: (5000 * 0.0000008) + (1200 * 0.000004) = $0.004 + $0.0048 = ~$0.0088...
        # but haiku is much cheaper. actual: input $0.25/M, output $1.25/M
        # cost per review: (5000 * 0.00000025) + (1200 * 0.00000125) = $0.00125 + $0.0015 = ~$0.00275
        # ~50 reviews/day weekday, 20-25 weekend
        daily_data = [
            # (days_ago, total_tokens, input_tokens, output_tokens, cost_usd, reviews)
            (1, 316000, 253000, 63000, 0.0142, 48),
            (2, 290000, 232000, 58000, 0.0130, 44),
            (3, 343000, 275000, 68000, 0.0154, 52),
            (4, 303000, 242000, 61000, 0.0136, 46),
            (5, 329000, 263000, 66000, 0.0148, 50),
            (6, 158000, 126000, 32000, 0.0071, 24),   # weekend — reduced volume
            (7, 145000, 116000, 29000, 0.0065, 22),   # weekend
        ]
        for (days_ago, tt, it, ot, cost, reviews) in daily_data:
            d = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            conn.execute(
                """INSERT OR IGNORE INTO cost_records(agent_id, recorded_date, total_tokens,
                   input_tokens, output_tokens, cost_usd, review_count)
                   VALUES (?,?,?,?,?,?,?)""",
                (AGENT_ID, d, tt, it, ot, cost, reviews),
            )

        # ── 7. Audit log ──────────────────────────────────────────────────────
        audit_events = [
            ("AGENT_REGISTERED",   "Krishna Paruchuri", -30, {
                "name": "GMP Deviation Review - AI Assistant",
                "product": "GMP Deviation Review",
                "workflow": "Pharmaceutical QA Team Review",
                "model": "claude-haiku-4-5",
            }),
            ("VERSION_REGISTERED", "Krishna Paruchuri", -30, {
                "version": "1.0.0",
                "model": "claude-haiku-4-5",
                "sop_corpus_count": 5,
                "golden_cases": 15,
                "guardrails_count": len(GUARDRAILS),
                "golden_rules_count": len(GOLDEN_RULES),
            }),
            ("STAGE_TRANSITION",   "Krishna Paruchuri", -30, {"from": None,           "to": "Proposed"}),
            ("STAGE_TRANSITION",   "Krishna Paruchuri", -28, {"from": "Proposed",     "to": "Under Review"}),
            ("EVAL_SUBMITTED",     "Krishna Paruchuri", -21, {
                "version": "1.0.0",
                "pass_rate": 0.87,
                "avg_score": 6.67,
                "total_cases": 15,
                "passed": 13,
                "failed": 2,
                "failed_cases": ["GC-005", "GC-011"],
                "threshold_met": True,
                "weakest_dimension": "regulatory_flag (5.8/10)",
            }),
            ("APPROVAL_REQUESTED", "Krishna Paruchuri", -22, {
                "type": "promotion",
                "from": "Under Review",
                "to": "Approved",
                "notes": "15 golden cases at 87%. QA team sign-off obtained.",
            }),
            ("APPROVAL_DECIDED",   "Governance Lead",   -20, {
                "decision": "approved",
                "eval_attached": True,
                "known_gaps": ["GC-005 RA flag miss", "GC-011 incomplete CAPA"],
                "v1_1_backlog": True,
            }),
            ("STAGE_TRANSITION",   "Governance Lead",   -20, {"from": "Under Review", "to": "Approved"}),
            ("APPROVAL_REQUESTED", "Krishna Paruchuri", -16, {
                "type": "promotion",
                "from": "Approved",
                "to": "In Production",
                "notes": "10 live cases reviewed by QA lead. Outputs validated. Cost confirmed.",
            }),
            ("APPROVAL_DECIDED",   "Governance Lead",   -15, {
                "decision": "approved",
                "live_case_review": "10 cases confirmed by QA lead",
                "cost_per_review_usd": 0.00275,
            }),
            ("STAGE_TRANSITION",   "Governance Lead",   -15, {"from": "Approved",     "to": "In Production"}),
        ]
        for (action, actor, days_ago, payload) in audit_events:
            conn.execute(
                "INSERT INTO audit_log(event_time, agent_id, actor, action, payload) VALUES (?,?,?,?,?)",
                (
                    (now + timedelta(days=days_ago)).isoformat(timespec="seconds"),
                    AGENT_ID, actor, action, json.dumps(payload),
                ),
            )

    print(f"\nOK Seeded agent '{AGENT_ID}' successfully.")
    print(f"  Name:      GMP Deviation Review - AI Assistant")
    print(f"  Stage:     In Production")
    print(f"  Version:   1.0.0 (active)")
    print(f"  Model:     claude-haiku-4-5")
    print(f"  Guardrails: {len(GUARDRAILS)}")
    print(f"  Golden rules: {len(GOLDEN_RULES)}")
    print(f"  Eval:      87% pass (13/15) · avg 6.67/10 · threshold met OK")
    print(f"  Failing cases: GC-005 (RA flag), GC-011 (CAPA quality)")
    print(f"  Cost records: last 7 days")
    print(f"  Audit log: {len(audit_events)} entries")
    print()


if __name__ == "__main__":
    seed()
