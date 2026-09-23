"""
AgentOps — Push seed cost / trace / audit data to production via REST API.
Run this from any machine — it calls the public API, no DB access needed.

What it pushes (for all 7 agents):
  • 30 days of daily cost records ending TODAY (upsert — safe to re-run)
  • 7 days of execution traces ending now (deterministic trace_ids — re-runs are no-ops)
  • Fresh audit events: a regression eval run + a monitoring alert that is
    triggered and resolved (the API writes EVAL_SUBMITTED / ALERT_TRIGGERED /
    ALERT_RESOLVED to the audit log with today's timestamp)

Pricing (per 1M tokens):  Haiku 4.5 $1 in / $5 out · Sonnet 4.6 $3 in / $15 out

Usage:
  python push_seed_data.py                      # pushes to production Railway
  python push_seed_data.py --env local          # pushes to localhost:8000
  python push_seed_data.py --skip-audit         # costs + traces only
"""
import json, os, random, uuid, argparse, time
from datetime import datetime, timedelta, timezone
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

ENVS = {
    "production": "https://agentops-production-980c.up.railway.app",
    "local":      "http://localhost:8000",
}

PRICING = {  # USD per token
    "claude-haiku-4-5":  (1.00 / 1e6, 5.00 / 1e6),
    "claude-sonnet-4-6": (3.00 / 1e6, 15.00 / 1e6),
}

def cost_of(model, inp, out):
    pi, po = PRICING[model]
    return round(inp * pi + out * po, 6)

# ── Agent profiles ─────────────────────────────────────────────────────────────
# weekday_calls: calls/day Mon–Fri · weekend: multiplier Sat/Sun
# in_tok / out_tok: per-call token ranges · latency: ms range
AGENTS = {
    "gmp-deviation-review": dict(model="claude-haiku-4-5",  weekday_calls=85,   weekend=0.20,
                                 in_tok=(1800, 2800), out_tok=(500, 800),  latency=(2200, 4800)),
    "medassist-router":     dict(model="claude-haiku-4-5",  weekday_calls=2200, weekend=0.45,
                                 in_tok=(700, 1100),  out_tok=(80, 160),   latency=(350, 900)),
    "medassist-scheduler":  dict(model="claude-haiku-4-5",  weekday_calls=650,  weekend=0.40,
                                 in_tok=(900, 1400),  out_tok=(200, 350),  latency=(800, 1900)),
    "medassist-scribe":     dict(model="claude-sonnet-4-6", weekday_calls=180,  weekend=0.25,
                                 in_tok=(3500, 6000), out_tok=(700, 1100), latency=(6500, 14000)),
    "medassist-results":    dict(model="claude-sonnet-4-6", weekday_calls=240,  weekend=0.50,
                                 in_tok=(1800, 3000), out_tok=(500, 800),  latency=(3500, 8000)),
    # Approved — running in shadow/pilot mode ahead of production cutover
    "medassist-orders":     dict(model="claude-haiku-4-5",  weekday_calls=60,   weekend=0.30,
                                 in_tok=(800, 1200),  out_tok=(200, 320),  latency=(900, 2000)),
    # Under Review — UAT traffic from the billing QA team only
    "medassist-billing":    dict(model="claude-sonnet-4-6", weekday_calls=25,   weekend=0.0,
                                 in_tok=(3000, 4500), out_tok=(600, 900),  latency=(5000, 11000)),
}

# ── Trace scenarios per agent ──────────────────────────────────────────────────
# (user_input, classification, severity, qa_escalation, model_output dict)
SCENARIOS = {
    "gmp-deviation-review": [
        ("Batch record incomplete — patient-impacting process step unsigned", "documentation_gap", "Critical", True,
         {"severity": "Critical", "sop": "SOP-QA-042 §5.3.1", "escalate_flag": True, "capa_items": 3}),
        ("Temperature excursion: cold-chain product at 11°C for 4h", "temp_excursion", "Critical", True,
         {"severity": "Critical", "sop": "SOP-WH-011 §4.2", "escalate_flag": True, "capa_items": 4}),
        ("Equipment calibration overdue by 6 days, batch released before detection", "calibration_oos", "Major", True,
         {"severity": "Major", "sop": "SOP-ENG-007 §3.1", "escalate_flag": True, "regulatory_flag": True}),
        ("SOP-QA-018 Rev 2 used instead of current Rev 5", "wrong_sop_version", "Major", False,
         {"severity": "Major", "sop": "SOP-DOC-003 §2.4", "escalate_flag": False, "capa_items": 2}),
        ("Mixing speed 10 RPM below lower control limit for 8 minutes", "process_param_deviation", "Minor", False,
         {"severity": "Minor", "sop": "SOP-MFG-021 §6.1", "escalate_flag": False, "capa_items": 1}),
        ("Particulate matter in 2/5000 vials, root cause unknown", "contamination_risk", "Critical", True,
         {"severity": "Critical", "root_cause": "undetermined — investigation required", "escalate_flag": True}),
        ("Raw material COA discrepancy: supplier vs in-house retest", "coa_discrepancy", "Major", True,
         {"severity": "Major", "sop": "SOP-QC-015 §4.4", "escalate_flag": True, "capa_items": 2}),
        ("Label reconciliation: 12 labels unaccounted after batch", "label_reconciliation", "Major", False,
         {"severity": "Major", "sop": "SOP-PKG-009 §7.2", "escalate_flag": False, "capa_items": 2}),
        ("Water system TOC above alert limit, conductivity in range", "water_system_alert", "Minor", False,
         {"severity": "Minor", "sop": "SOP-UT-004 §3.3", "escalate_flag": False, "capa_items": 1}),
        ("HVAC filter pressure drop below minimum — cleanroom risk", "hvac_deviation", "Major", True,
         {"severity": "Major", "sop": "SOP-FAC-012 §5.1", "escalate_flag": True, "capa_items": 3}),
    ],
    "medassist-router": [
        ("Book cardiology follow-up for next week", "scheduling", None, False, {"route": "medassist-scheduler", "confidence": 0.97}),
        ("Doctor-patient consult audio: chest pain evaluation", "scribe", None, False, {"route": "medassist-scribe", "confidence": 0.95}),
        ("Interpret CBC panel uploaded from lab portal", "results", None, False, {"route": "medassist-results", "confidence": 0.96}),
        ("Order lipid panel and HbA1c for diabetic review", "orders", None, False, {"route": "medassist-orders", "confidence": 0.93}),
        ("Code visit: Type 2 diabetes management, 45 min", "billing", None, False, {"route": "medassist-billing", "confidence": 0.94}),
        ("Refill request plus question about lab results", "multi_intent", None, True, {"route": "human_review", "confidence": 0.58}),
        ("Reschedule MRI and send prep instructions", "scheduling", None, False, {"route": "medassist-scheduler", "confidence": 0.91}),
        ("Transcribe telehealth follow-up for hypertension", "scribe", None, False, {"route": "medassist-scribe", "confidence": 0.96}),
    ],
    "medassist-scheduler": [
        ("Schedule cardiology follow-up — no Monday availability", "new_appointment", None, False, {"slot_found": True, "days_out": 3}),
        ("Patient requests same-day urgent appointment", "urgent_request", None, True, {"slot_found": False, "escalated_to": "front_desk"}),
        ("Reschedule annual physical — conflict with existing slot", "reschedule", None, False, {"slot_found": True, "days_out": 9}),
        ("Cancel dermatology appointment and add to waitlist", "cancellation", None, False, {"waitlist_position": 4}),
        ("Book post-op check 14 days after surgery date", "new_appointment", None, False, {"slot_found": True, "days_out": 14}),
    ],
    "medassist-scribe": [
        ("SOAP note: 58yo M, chief complaint chest tightness", "soap_note", None, False, {"sections": ["S", "O", "A", "P"], "hpi_present": True}),
        ("SOAP note: annual wellness visit, no acute complaints", "soap_note", None, False, {"sections": ["S", "O", "A", "P"], "hpi_present": True}),
        ("SOAP note: pediatric fever, 3 days, OCR'd intake form", "soap_note", None, False, {"sections": ["S", "O", "A", "P"], "hpi_present": True}),
        ("SOAP note: low-quality audio, partial transcript", "soap_note", None, True, {"sections": ["S", "A", "P"], "hpi_present": False, "flag": "incomplete_audio"}),
        ("Progress note: diabetes follow-up, med adjustment", "progress_note", None, False, {"sections": ["S", "O", "A", "P"], "hpi_present": True}),
    ],
    "medassist-results": [
        ("CBC: WBC 14.2 (H), Hgb 11.1 (L), Plt 420 (H)", "abnormal", "Major", False, {"status": "ABNORMAL", "follow_up_suggestions": 2}),
        ("HbA1c 8.9% — above target for T2DM management", "abnormal", "Major", False, {"status": "ABNORMAL", "follow_up_suggestions": 2}),
        ("Creatinine 2.1 — elevated, prior baseline 1.2", "abnormal", "Major", True, {"status": "ABNORMAL", "follow_up_suggestions": 3}),
        ("Potassium 6.4 mmol/L", "critical", "Critical", True, {"status": "CRITICAL", "follow_up_suggestions": 2, "notify": "ordering_physician"}),
        ("Lipid panel within reference ranges", "normal", "Minor", False, {"status": "NORMAL", "follow_up_suggestions": 0}),
        ("Chest X-ray report: no acute cardiopulmonary process", "normal", "Minor", False, {"status": "NORMAL", "follow_up_suggestions": 0}),
    ],
    "medassist-orders": [
        ("Order lipid panel and HbA1c", "loinc_mapped", None, False, {"loinc": ["57698-3", "4548-4"], "priority": "medium"}),
        ("Stat troponin and BMP", "loinc_mapped", None, False, {"loinc": ["6598-7", "51990-0"], "priority": "high"}),
        ("TSH with reflex free T4", "loinc_mapped", None, False, {"loinc": ["3016-3"], "priority": "low"}),
        ("'The usual kidney labs' — ambiguous dictation", "unmappable", None, True, {"loinc": [], "priority": "medium", "flag": "unmappable_order"}),
    ],
    "medassist-billing": [
        ("Code visit: T2DM management, 45 min, established patient", "icd10_cpt", None, False, {"icd10": ["E11.9"], "cpt": ["99215"], "denial_risk": "low"}),
        ("Code visit: hypertension follow-up with ECG", "icd10_cpt", None, False, {"icd10": ["I10"], "cpt": ["99214", "93000"], "denial_risk": "low"}),
        ("Code visit: chest pain workup, documentation incomplete", "icd10_cpt", None, True, {"icd10": ["R07.9"], "cpt": ["99214"], "denial_risk": "high"}),
        ("Code procedure: skin lesion excision 1.2 cm", "icd10_cpt", None, False, {"icd10": ["D48.5"], "cpt": ["11402"], "denial_risk": "medium"}),
    ],
}

# ── Audit-producing events (evals + alerts) ────────────────────────────────────
EVALS = {
    "gmp-deviation-review": ("Krishna Paruchuri", 0.88, 7.1, 25, True,
        {"severity_classification": 7.6, "sop_citation": 7.3, "capa_quality": 6.8, "escalation_behavior": 7.4,
         "groundedness": 7.2, "output_structure": 8.3, "regulatory_flag": 6.6, "clarity": 6.4}),
    "medassist-router":     ("QA / Krishna Paruchuri", 0.90, 7.4, 40, True,
        {"routing_accuracy": 8.1, "multi_intent_handling": 6.6, "latency_compliance": 7.8, "hipaa_adherence": 7.2}),
    "medassist-scheduler":  ("QA / Krishna Paruchuri", 0.95, 7.9, 30, True,
        {"scheduling_accuracy": 8.2, "conflict_detection": 7.9, "urgent_escalation": 7.6, "hipaa_adherence": 7.8}),
    "medassist-scribe":     ("QA / Krishna Paruchuri", 0.86, 7.0, 25, True,
        {"documentation_completeness": 6.9, "clinical_accuracy": 7.3, "hpi_presence": 6.6, "hipaa_adherence": 7.6}),
    "medassist-results":    ("QA / Krishna Paruchuri", 0.92, 7.6, 30, True,
        {"critical_value_flagging": 8.4, "follow_up_suggestions": 7.3, "no_definitive_diagnosis": 7.8, "report_date_present": 8.0}),
    "medassist-orders":     ("QA / Krishna Paruchuri", 0.90, 7.3, 30, True,
        {"loinc_mapping": 7.8, "priority_explicit": 7.6, "clinical_rationale": 6.7, "unmappable_flagging": 7.0}),
    "medassist-billing":    ("QA / Krishna Paruchuri", 0.81, 6.7, 26, False,
        {"code_accuracy": 6.9, "documentation_link": 6.4, "denial_risk_analysis": 7.1, "similar_case_matching": 6.2}),
}

ALERTS = {
    "gmp-deviation-review": ("escalation_spike", "warning", "Escalation Rate Above Baseline",
        "QA escalation rate 46% over the last 24h vs 38% 7-day baseline — driven by 3 cold-chain excursions.", "QA Lead"),
    "medassist-router":     ("cost_threshold", "info", "Daily Spend at 72% of Cap",
        "Router spend reached $3.60 of $5.00 daily cap by 16:00 UTC. Within tolerance.", "Platform / Krishna Paruchuri"),
    "medassist-scheduler":  ("eval_degradation", "info", "Urgent-Escalation Score Recovered",
        "urgent_escalation dimension back above 7.5 after prompt fix in v1.0.0 config.", "QA / Krishna Paruchuri"),
    "medassist-scribe":     ("golden_rule_violation", "warning", "SOAP Note Missing HPI",
        "1 of 180 notes yesterday missing HPI section (low-quality audio). Flagged for clinician review.", "Clinical / Krishna Paruchuri"),
    "medassist-results":    ("escalation_spike", "info", "Critical Values Flagged Correctly",
        "4 critical potassium/troponin values flagged CRITICAL and routed to ordering physician within SLA.", "Clinical / Krishna Paruchuri"),
    "medassist-orders":     ("golden_rule_violation", "warning", "Unmappable Order in Shadow Mode",
        "2 dictated orders could not be mapped to LOINC; correctly flagged, no auto-submission.", "Clinical / Krishna Paruchuri"),
    "medassist-billing":    ("eval_degradation", "warning", "UAT Eval Below Threshold",
        "UAT pass rate 0.81 vs 0.85 threshold — documentation_link dimension lagging. Promotion blocked.", "Billing / Krishna Paruchuri"),
}

# ── HTTP helper ────────────────────────────────────────────────────────────────
def api(base, method, path, body=None, retries=3):
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(1, retries + 1):
        req = urlrequest.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urlrequest.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except HTTPError as e:
            err = e.read().decode()
            if e.code in (502, 503, 504) and attempt < retries:
                time.sleep(3 * attempt)
                continue
            try:   detail = json.loads(err).get("detail", err)
            except Exception: detail = err
            if e.code == 409 or "already exists" in str(detail).lower():
                return {"skipped": True}
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail}")
        except (URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(f"{method} {path}: {e}")

# ── Volume helper ──────────────────────────────────────────────────────────────
def daily_volume(p, day, now):
    vol = p["weekday_calls"] * (p["weekend"] if day.weekday() >= 5 else 1.0)
    vol *= random.uniform(0.88, 1.12)
    if day.date() == now.date():               # today: only the part of the day elapsed
        vol *= (now.hour * 60 + now.minute) / 1440
    return int(round(vol))

# ── Costs ──────────────────────────────────────────────────────────────────────
def push_costs(base, agent_id, p, now, days=30):
    pushed, total = 0, 0.0
    for i in range(days - 1, -1, -1):          # includes today
        day = now - timedelta(days=i)
        vol = daily_volume(p, day, now)
        inp = sum(random.randint(*p["in_tok"]) for _ in range(vol))
        out = sum(random.randint(*p["out_tok"]) for _ in range(vol))
        c = cost_of(p["model"], inp, out)
        api(base, "POST", f"/agents/{agent_id}/costs", {
            "recorded_date": day.strftime("%Y-%m-%d"),
            "total_tokens":  inp + out,
            "input_tokens":  inp,
            "output_tokens": out,
            "cost_usd":      c,
            "review_count":  vol,
        })
        pushed += 1
        total += c
    return pushed, total

# ── Traces ─────────────────────────────────────────────────────────────────────
TRACE_NS = uuid.UUID("6f1c7a52-3b1e-4d0c-9a57-2f5e8c1d4b90")

def push_traces(base, agent_id, p, now, days=7, per_day=12):
    scenarios = SCENARIOS[agent_id]
    pushed = 0
    for i in range(days - 1, -1, -1):
        day = now - timedelta(days=i)
        n = per_day if day.weekday() < 5 else max(2, int(per_day * max(p["weekend"], 0.25)))
        if p["weekend"] == 0 and day.weekday() >= 5:
            continue
        start = day.replace(hour=7, minute=0, second=0, microsecond=0)
        for j in range(n):
            ts = start + timedelta(minutes=j * 55 + random.randint(0, 40), seconds=random.randint(0, 59))
            if ts > now:
                break
            text, cls, sev, esc, out_obj = scenarios[(i * 3 + j) % len(scenarios)]
            inp = random.randint(*p["in_tok"])
            out = random.randint(*p["out_tok"])
            fallback = random.random() < 0.015
            body = {
                "trace_id":       str(uuid.uuid5(TRACE_NS, f"{agent_id}|{day:%Y-%m-%d}|{j}")),
                "timestamp":      ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "user_input":     text[:500],
                "severity":       sev,
                "qa_escalation":  esc,
                "classification": cls,
                "input_tokens":   inp,
                "output_tokens":  out,
                "cost_usd":       cost_of(p["model"], inp, out),
                "latency_ms":     random.randint(*p["latency"]) * (2 if fallback else 1),
                "is_fallback":    fallback,
                "model_output":   json.dumps(out_obj),
                "source_app":     agent_id,
            }
            api(base, "POST", f"/agents/{agent_id}/traces", body)
            pushed += 1
    return pushed

# ── Audit (via evals + alerts) ─────────────────────────────────────────────────
def push_audit(base, agent_id):
    run_by, pass_rate, avg, total, met, dims = EVALS[agent_id]
    api(base, "POST", f"/agents/{agent_id}/evals", {
        "version": "1.0.0", "run_by": run_by, "pass_rate": pass_rate, "avg_score": avg,
        "total_cases": total, "passed_cases": round(total * pass_rate),
        "threshold_met": met, "dimensions": dims,
    })
    a_type, sev, title, msg, resolver = ALERTS[agent_id]
    r = api(base, "POST", f"/agents/{agent_id}/alerts", {
        "alert_type": a_type, "severity": sev, "title": title, "message": msg,
        "metadata": {"source": "daily-monitor"},
    })
    alert_id = r.get("alert_id")
    if alert_id:
        from urllib.parse import quote
        api(base, "POST", f"/agents/{agent_id}/alerts/{alert_id}/resolve?resolved_by={quote(resolver)}")
    return 3 if alert_id else 2

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["production", "local"], default="production")
    parser.add_argument("--skip-audit", action="store_true")
    args = parser.parse_args()
    base = os.environ.get("AGENTOPS_API_URL", ENVS[args.env])
    now = datetime.now(timezone.utc)
    print(f"Pushing seed data → {base}   (as of {now:%Y-%m-%d %H:%M} UTC)\n")

    for agent_id, p in AGENTS.items():
        print(f"── {agent_id}  [{p['model']}]")
        try:
            n, total = push_costs(base, agent_id, p, now)
            print(f"  ✓ costs:  {n} days, ${total:,.2f} total (${total/30:,.2f}/day avg)")
        except RuntimeError as e:
            print(f"  ⚠ costs:  {e}")
        try:
            print(f"  ✓ traces: {push_traces(base, agent_id, p, now)} pushed")
        except RuntimeError as e:
            print(f"  ⚠ traces: {e}")
        if not args.skip_audit:
            try:
                print(f"  ✓ audit:  {push_audit(base, agent_id)} events")
            except RuntimeError as e:
                print(f"  ⚠ audit:  {e}")

    print("\n✓ Done.\n")

if __name__ == "__main__":
    random.seed(42)
    main()
