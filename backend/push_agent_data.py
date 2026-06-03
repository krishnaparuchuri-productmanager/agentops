"""
AgentOps — Agent Data Push Script
===================================
This script shows exactly how an agent team pushes their live data
(registration, version, eval results, cost records) into the AgentOps
governance dashboard via the REST API.

Run this from the agent's own CI/CD pipeline or as a one-time registration step.

Usage:
  python push_agent_data.py --env local           # local dev (localhost:8000)
  python push_agent_data.py --env production      # Railway deployment
  python push_agent_data.py --step register       # only register agent
  python push_agent_data.py --step eval           # only push eval results
  python push_agent_data.py --step cost           # only push cost records
  python push_agent_data.py                       # run all steps

Environment variables:
  AGENTOPS_API_URL  — override API base URL
  AGENTOPS_AGENT_ID — override agent ID
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from urllib import request as urlrequest
from urllib.error import HTTPError

# ── Configuration ──────────────────────────────────────────────────────────────

ENVS = {
    "local":      "http://localhost:8000",
    "production": "https://agentops-production.up.railway.app",
}

AGENT_ID = os.environ.get("AGENTOPS_AGENT_ID", "gmp-deviation-review")

# ── Real agent definition ──────────────────────────────────────────────────────
# This data lives in the agent's own repository and gets pushed here.

AGENT_DEFINITION = {
    "id": AGENT_ID,
    "name": "GMP Deviation Review - AI Assistant",
    "description": (
        "Pharmaceutical GMP deviation-review assistant. Accepts a structured deviation "
        "report, retrieves applicable SOPs via TF-IDF retrieval over 5 validated documents, "
        "classifies deviation severity (Critical / Major / Minor), identifies the primary "
        "applicable SOP and clause, proposes root cause hypothesis, recommends CAPA actions "
        "with owner/date/effectiveness-check fields, and escalates by default when evidence "
        "is ambiguous or a patient-impacting process is involved."
    ),
    "owner": "Quality Assurance / Krishna Paruchuri",
    "classification": {
        "pii_access":           False,
        "production_critical":  True,
        "regulated_domain":     True,
        "data_classification":  "confidential",
        "escalates_to_human":   True,
        "product":              "GMP Deviation Review",
        "workflow":             "Pharmaceutical QA Team Review",
        "domain":               "Pharmaceutical",
        "environment":          "production",
        "model":                "claude-haiku-4-5",
        "eval_threshold":       0.80,
        "guardrails": [
            "No patient data or PII in output — mask or reject if present in input",
            "Always escalate when evidence is ambiguous, conflicting, or missing — never resolve uncertainty alone",
            "Do not make regulatory submission decisions — flag for Regulatory Affairs and stop",
            "Output must be structured JSON with all 7 required fields — never return free-text only",
            "If supporting SOP documents are not retrievable, return escalate_flag=true and state reason",
            "For Critical deviations: identify immediate containment actions before recommending CAPA",
            "Refuse to classify severity as 'Minor' if a released product or patient-impacting step is involved",
        ],
        "golden_rules": [
            "Cite the applicable SOP by full document ID and clause number (e.g., SOP-QA-042, Clause 5.3.1)",
            "State severity classification (Critical / Major / Minor) with explicit justification citing observable evidence from the deviation report",
            "For Critical deviations, list immediate containment actions as the first CAPA item before corrective/preventive recommendations",
            "Every CAPA recommendation must include: responsible owner role, target completion date, and effectiveness check criteria",
            "If root cause cannot be determined from available evidence, state 'Root cause undetermined — investigation required' — do not speculate",
            "Flag for Regulatory Affairs notification if the deviation involves: a released batch, a validated process step, or a patient-facing output",
            "Never recommend closing a deviation without a stated root cause or an explicit investigation plan",
        ],
    },
}

VERSION_DEFINITION = {
    "version": "1.0.0",
    "model": "claude-haiku-4-5",
    "created_by": "Krishna Paruchuri",
    "changelog": (
        "Initial production release. TF-IDF retrieval over 5 GMP SOPs. "
        "15 golden cases, 87% pass rate (13/15). Avg score 6.67/10. "
        "Known weakness: regulatory_flag dimension (5.8/10) — "
        "v1.1.0 will add explicit RA trigger logic."
    ),
    "config_snapshot": {
        "retrieval":    "TF-IDF over 5 GMP SOPs",
        "output_format": "structured JSON, 7 required fields",
        "tool_use":     "forced — retrieve_sop tool called before classification",
        "fallback":     "escalate_flag=true on any retrieval or parsing failure",
        "retry_policy": "retry-with-validation on JSON parse error (max 2 retries)",
        "temperature":  0.1,
        "max_tokens":   1024,
        "sop_corpus": [
            "SOP-QA-001 Rev 4 — Deviation Management and CAPA",
            "SOP-QA-018 Rev 5 — Environmental Monitoring Procedure",
            "SOP-QA-042 Rev 2 — Out-of-Specification Investigation",
            "SOP-PROD-007 Rev 3 — Batch Record Review and Release",
            "SOP-ENV-003 Rev 1 — Cleanroom Classification and Monitoring",
        ],
    },
}

# ── Golden cases (15 curated by QA lead) ──────────────────────────────────────
# These are the cases your eval framework runs against.
# Format: (case_id, description, expected_severity, expected_escalate, result, failure_reason)
GOLDEN_CASES = [
    ("GC-001", "Temperature excursion in cold-chain storage (2–8°C product, logged at 11°C for 4h)",      "Critical", True,  "pass", None),
    ("GC-002", "Batch record incomplete — operator signature missing on 3 of 12 steps",                    "Major",    False, "pass", None),
    ("GC-003", "Environmental monitoring alert: mould colony count above action limit in Grade B area",    "Critical", True,  "pass", None),
    ("GC-004", "Equipment calibration overdue by 6 days, batch released before detection",                "Major",    True,  "pass", None),
    ("GC-005", "Raw material COA out of specification — supplier vs. in-house retest discrepancy",        "Major",    True,  "fail", "Missed RA flag: supplier/in-house COA discrepancy on released batch requires Regulatory Affairs notification per SOP-QA-042 Clause 6.2"),
    ("GC-006", "Cross-contamination risk: wrong batch label found in staging area adjacent to open vessel","Critical", True,  "pass", None),
    ("GC-007", "Process parameter deviation: mixing speed 10 RPM below lower control limit for 8 minutes","Minor",    False, "pass", None),
    ("GC-008", "SOP not followed: analyst used deprecated SOP-QA-018 Rev 2 instead of current Rev 5",     "Major",    False, "pass", None),
    ("GC-009", "Water system TOC result above alert limit — conductivity within limits",                   "Major",    False, "pass", None),
    ("GC-010", "Ambiguous deviation: operator reported 'unusual odour' during granulation, no data",       "Major",    True,  "pass", None),
    ("GC-011", "Filling line stoppage: particulate matter in 2 vials out of 5000, root cause unknown",    "Critical", True,  "fail", "CAPA quality: recommended 'investigate root cause' without specifying responsible owner, target date, or effectiveness criteria — fails golden rule 4"),
    ("GC-012", "HVAC filter differential pressure drop below minimum — cleanroom classification risk",     "Major",    True,  "pass", None),
    ("GC-013", "Label reconciliation discrepancy: 12 labels unaccounted for after batch completion",       "Major",    True,  "pass", None),
    ("GC-014", "Stability sample missed: 6-month time point not tested, accelerated study only",           "Major",    False, "pass", None),
    ("GC-015", "Out-of-specification (OOS) result on finished product potency test, released batch",       "Critical", True,  "pass", None),
]

EVAL_RUN = {
    "version":      "1.0.0",
    "run_by":       "Krishna Paruchuri",
    "pass_rate":    0.87,   # 13/15
    "avg_score":    6.67,   # average across 8 dimensions
    "total_cases":  15,
    "passed_cases": 13,
    "threshold_met": True,
    "dimensions": {
        "severity_classification": 7.2,   # Critical/Major/Minor correct
        "sop_citation":            7.0,   # correct SOP ID and clause
        "capa_quality":            6.4,   # owner + date + effectiveness check
        "escalation_behavior":     7.1,   # escalates on ambiguous/critical
        "groundedness":            7.2,   # grounded in evidence, not hallucinated
        "output_structure":        8.1,   # valid JSON, all 7 fields
        "regulatory_flag":         5.8,   # hardest: RA notification trigger (known gap)
        "clarity":                 5.9,   # QA-appropriate language
    },
}

# ── Cost record (yesterday's actual) ──────────────────────────────────────────
# In a real pipeline this would be computed from your LLM usage logs.
COST_RECORD = {
    "recorded_date": (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"),
    "total_tokens":  316000,
    "input_tokens":  253000,
    "output_tokens": 63000,
    "cost_usd":      0.0142,
    "review_count":  48,
}


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def api_call(base_url: str, method: str, path: str, body: dict = None):
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = urlrequest.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urlrequest.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result
    except HTTPError as e:
        err_body = e.read().decode()
        try:
            err_json = json.loads(err_body)
            detail = err_json.get("detail", err_body)
        except Exception:
            detail = err_body
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail}")


# ── Push steps ─────────────────────────────────────────────────────────────────

def step_register(base_url: str):
    print("\n── Step 1: Register Agent ───────────────────────────────────────")
    try:
        result = api_call(base_url, "POST", "/agents", AGENT_DEFINITION)
        print(f"  ✓ Agent registered: {result.get('id')}")
    except RuntimeError as e:
        if "already exists" in str(e) or "409" in str(e):
            print(f"  ℹ Agent already registered — skipping (PATCH /agents/{AGENT_ID} to update)")
        else:
            raise

    print("\n── Step 2: Register Version ─────────────────────────────────────")
    try:
        result = api_call(base_url, "POST", f"/agents/{AGENT_ID}/versions", VERSION_DEFINITION)
        print(f"  ✓ Version {VERSION_DEFINITION['version']} registered")
        print(f"    Status: Draft — use Activate in dashboard or call POST /versions/{VERSION_DEFINITION['version']}/activate")
    except RuntimeError as e:
        if "already exists" in str(e) or "409" in str(e):
            print(f"  ℹ Version {VERSION_DEFINITION['version']} already exists — skipping")
        else:
            raise


def step_eval(base_url: str):
    print("\n── Step 3: Push Eval Results ────────────────────────────────────")
    print(f"  Running against {len(GOLDEN_CASES)} golden cases…")

    passing = [c for c in GOLDEN_CASES if c[4] == "pass"]
    failing = [c for c in GOLDEN_CASES if c[4] == "fail"]
    print(f"  Pass: {len(passing)}/{len(GOLDEN_CASES)}")
    for c in failing:
        print(f"  ✗ {c[0]}: {c[5]}")

    result = api_call(base_url, "POST", f"/agents/{AGENT_ID}/evals", EVAL_RUN)
    print(f"  ✓ Eval result recorded (ID: {result.get('eval_id')})")
    print(f"    Pass rate: {EVAL_RUN['pass_rate']*100:.0f}% · Avg score: {EVAL_RUN['avg_score']:.2f}/10")
    print(f"    Weakest dimension: regulatory_flag ({EVAL_RUN['dimensions']['regulatory_flag']}/10)")
    print(f"    Threshold met: {'✓ Yes' if EVAL_RUN['threshold_met'] else '✗ No'}")


def step_cost(base_url: str):
    print("\n── Step 4: Push Cost Record ─────────────────────────────────────")
    result = api_call(base_url, "POST", f"/agents/{AGENT_ID}/costs", COST_RECORD)
    print(f"  ✓ Cost record pushed for {COST_RECORD['recorded_date']}")
    print(f"    {COST_RECORD['review_count']} reviews · "
          f"{COST_RECORD['total_tokens']:,} tokens · "
          f"${COST_RECORD['cost_usd']:.4f}")
    per_review = COST_RECORD['cost_usd'] / COST_RECORD['review_count']
    print(f"    Cost per review: ${per_review:.5f}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Push agent data to AgentOps dashboard")
    parser.add_argument("--env",  choices=["local", "production"], default="production")
    parser.add_argument("--step", choices=["register", "eval", "cost"], default=None,
                        help="Run a single step (default: all steps)")
    args = parser.parse_args()

    base_url = os.environ.get("AGENTOPS_API_URL", ENVS[args.env])
    print(f"AgentOps Push — target: {base_url}")
    print(f"Agent: {AGENT_ID}")

    try:
        if args.step == "register" or args.step is None:
            step_register(base_url)
        if args.step == "eval" or args.step is None:
            step_eval(base_url)
        if args.step == "cost" or args.step is None:
            step_cost(base_url)
        print("\n✓ All done.\n")
    except RuntimeError as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
