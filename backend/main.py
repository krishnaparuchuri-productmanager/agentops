"""
AgentOps — FastAPI backend
Phase 1: single managed agent (SOP Deviation Review)

Endpoints:
  GET  /health
  GET  /agents
  POST /agents
  GET  /agents/{agent_id}
  GET  /agents/{agent_id}/versions
  POST /agents/{agent_id}/versions
  GET  /agents/{agent_id}/transitions          (allowed next stages)
  POST /agents/{agent_id}/transitions          (execute a transition)
  GET  /agents/{agent_id}/approvals
  POST /agents/{agent_id}/approvals            (maker: propose)
  POST /agents/{agent_id}/approvals/{req_id}/decision  (checker: approve/reject)
  GET  /agents/{agent_id}/evals
  POST /agents/{agent_id}/evals
  GET  /agents/{agent_id}/costs
  POST /agents/{agent_id}/costs
  POST /agents/{agent_id}/retire               (propose retirement)
  GET  /agents/{agent_id}/audit
  GET  /audit                                  (global audit log)
"""

import json
import os
import uuid
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, init_db
from lifecycle import validate_transition, allowed_next_stages, TransitionError

app = FastAPI(title="AgentOps", version="1.0.0")

# CORS — open for portfolio/demo use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    # Auto-seed on first run (no agents in DB = fresh deployment)
    from database import get_connection
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    conn.close()
    if count == 0:
        from seed import seed
        seed()


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _audit(conn, agent_id: Optional[str], actor: str, action: str, payload: dict):
    conn.execute(
        "INSERT INTO audit_log(event_time, agent_id, actor, action, payload) VALUES (?,?,?,?,?)",
        (_now(), agent_id, actor, action, json.dumps(payload)),
    )


def _row_to_dict(row) -> dict:
    return dict(row) if row else None


def _rows_to_list(rows) -> list:
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
#  Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9\-]+$", description="URL-safe slug")
    name: str
    description: Optional[str] = None
    owner: str
    classification: dict = Field(default_factory=dict)
    actor: str = "system"


class VersionCreate(BaseModel):
    version: str
    model: Optional[str] = None
    config_snapshot: Optional[dict] = None
    created_by: str


class TransitionRequest(BaseModel):
    to_stage: str
    triggered_by: str
    reason: Optional[str] = None


class ApprovalCreate(BaseModel):
    request_type: str = Field(..., pattern="^(promotion|retirement)$")
    from_stage: str
    to_stage: str
    proposed_by: str
    eval_result_id: Optional[int] = None


class ApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    reviewed_by: str
    reason: Optional[str] = None


class EvalCreate(BaseModel):
    version: str
    run_by: str
    pass_rate: float = Field(..., ge=0.0, le=1.0)
    avg_score: float
    total_cases: int
    passed_cases: int
    threshold_met: bool
    dimensions: dict = Field(default_factory=dict)


class CostRecord(BaseModel):
    recorded_date: str  # YYYY-MM-DD
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    review_count: int = 0


class RetirementProposal(BaseModel):
    proposed_by: str
    reason: str
    retirement_date: Optional[str] = None  # YYYY-MM-DD


# ─────────────────────────────────────────────────────────────────────────────
#  Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "agentops", "version": "1.0.0"}


# ─────────────────────────────────────────────────────────────────────────────
#  Registry
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents")
def list_agents():
    with db() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
    return _rows_to_list(rows)


@app.post("/agents", status_code=201)
def create_agent(body: AgentCreate):
    with db() as conn:
        existing = conn.execute("SELECT id FROM agents WHERE id=?", (body.id,)).fetchone()
        if existing:
            raise HTTPException(400, f"Agent '{body.id}' already exists")
        conn.execute(
            """INSERT INTO agents(id, name, description, owner, classification, current_stage, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                body.id, body.name, body.description, body.owner,
                json.dumps(body.classification), "Proposed", _now(), _now(),
            ),
        )
        conn.execute(
            "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason) VALUES (?,?,?,?,?)",
            (body.id, None, "Proposed", body.actor, "Initial registration"),
        )
        _audit(conn, body.id, body.actor, "AGENT_REGISTERED", {"agent_id": body.id, "name": body.name})
    return {"id": body.id, "stage": "Proposed"}


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Agent '{agent_id}' not found")
        agent = _row_to_dict(row)
        agent["classification"] = json.loads(agent["classification"])

        # Attach latest eval summary
        eval_row = conn.execute(
            "SELECT * FROM eval_results WHERE agent_id=? ORDER BY run_at DESC LIMIT 1", (agent_id,)
        ).fetchone()
        agent["latest_eval"] = _row_to_dict(eval_row)

        # Attach cost summary (last 30 days)
        cost_row = conn.execute(
            """SELECT SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS total_cost_usd,
                      SUM(review_count) AS total_reviews
               FROM cost_records WHERE agent_id=?
               AND recorded_date >= date('now', '-30 days')""",
            (agent_id,),
        ).fetchone()
        agent["cost_30d"] = _row_to_dict(cost_row)

        # Pending approval count
        pending = conn.execute(
            "SELECT COUNT(*) AS cnt FROM approval_requests WHERE agent_id=? AND decision IS NULL",
            (agent_id,),
        ).fetchone()["cnt"]
        agent["pending_approvals"] = pending

        agent["allowed_transitions"] = allowed_next_stages(agent["current_stage"])

    return agent


# ─────────────────────────────────────────────────────────────────────────────
#  Versions
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/versions")
def list_versions(agent_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_versions WHERE agent_id=? ORDER BY created_at DESC", (agent_id,)
        ).fetchall()
    return _rows_to_list(rows)


@app.post("/agents/{agent_id}/versions", status_code=201)
def create_version(agent_id: str, body: VersionCreate):
    with db() as conn:
        _ensure_agent(conn, agent_id)
        conn.execute(
            "INSERT INTO agent_versions(agent_id, version, model, config_snapshot, created_by) VALUES (?,?,?,?,?)",
            (agent_id, body.version, body.model, json.dumps(body.config_snapshot or {}), body.created_by),
        )
        _audit(conn, agent_id, body.created_by, "VERSION_REGISTERED",
               {"version": body.version, "model": body.model})
    return {"agent_id": agent_id, "version": body.version}


# ─────────────────────────────────────────────────────────────────────────────
#  Lifecycle transitions
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/transitions")
def get_allowed_transitions(agent_id: str):
    with db() as conn:
        agent = _ensure_agent(conn, agent_id)
    return {
        "current_stage": agent["current_stage"],
        "allowed_next": allowed_next_stages(agent["current_stage"]),
    }


@app.post("/agents/{agent_id}/transitions")
def execute_transition(agent_id: str, body: TransitionRequest):
    with db() as conn:
        agent = _ensure_agent(conn, agent_id)
        current = agent["current_stage"]

        # Check for approved request if transition requires one
        approved_req = conn.execute(
            """SELECT id FROM approval_requests
               WHERE agent_id=? AND to_stage=? AND decision='approved'
               ORDER BY reviewed_at DESC LIMIT 1""",
            (agent_id, body.to_stage),
        ).fetchone()
        has_approved = approved_req is not None

        # Check for passing eval
        passing_eval = conn.execute(
            "SELECT id FROM eval_results WHERE agent_id=? AND threshold_met=1 ORDER BY run_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        has_passing_eval = passing_eval is not None

        try:
            validate_transition(current, body.to_stage, has_approved, has_passing_eval)
        except TransitionError as e:
            raise HTTPException(422, str(e))

        now = _now()
        conn.execute(
            "UPDATE agents SET current_stage=?, updated_at=? WHERE id=?",
            (body.to_stage, now, agent_id),
        )
        conn.execute(
            "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason) VALUES (?,?,?,?,?)",
            (agent_id, current, body.to_stage, body.triggered_by, body.reason),
        )
        _audit(conn, agent_id, body.triggered_by, "STAGE_TRANSITION", {
            "from": current, "to": body.to_stage, "reason": body.reason
        })

    return {"agent_id": agent_id, "from_stage": current, "to_stage": body.to_stage}


# ─────────────────────────────────────────────────────────────────────────────
#  Maker-checker approval workflow
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/approvals")
def list_approvals(agent_id: str, pending_only: bool = Query(False)):
    with db() as conn:
        if pending_only:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE agent_id=? AND decision IS NULL ORDER BY proposed_at DESC",
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE agent_id=? ORDER BY proposed_at DESC",
                (agent_id,),
            ).fetchall()
    return _rows_to_list(rows)


@app.post("/agents/{agent_id}/approvals", status_code=201)
def propose_approval(agent_id: str, body: ApprovalCreate):
    with db() as conn:
        agent = _ensure_agent(conn, agent_id)
        # Validate the transition is conceptually valid before even creating the request
        try:
            validate_transition(agent["current_stage"], body.to_stage,
                                has_approved_request=False, has_passing_eval=False)
        except TransitionError as e:
            # Only block if transition is outright invalid (not just missing approval)
            if "not a valid transition" in str(e):
                raise HTTPException(422, str(e))

        # Block duplicate pending requests for same transition
        dup = conn.execute(
            """SELECT id FROM approval_requests
               WHERE agent_id=? AND to_stage=? AND decision IS NULL""",
            (agent_id, body.to_stage),
        ).fetchone()
        if dup:
            raise HTTPException(409, "A pending approval request already exists for this transition")

        cursor = conn.execute(
            """INSERT INTO approval_requests
               (agent_id, request_type, from_stage, to_stage, proposed_by, eval_result_id)
               VALUES (?,?,?,?,?,?)""",
            (agent_id, body.request_type, body.from_stage, body.to_stage,
             body.proposed_by, body.eval_result_id),
        )
        req_id = cursor.lastrowid
        _audit(conn, agent_id, body.proposed_by, "APPROVAL_REQUESTED", {
            "request_id": req_id,
            "type": body.request_type,
            "from": body.from_stage,
            "to": body.to_stage,
        })
    return {"request_id": req_id, "status": "pending"}


@app.post("/agents/{agent_id}/approvals/{req_id}/decision")
def decide_approval(agent_id: str, req_id: int, body: ApprovalDecision):
    with db() as conn:
        req = conn.execute(
            "SELECT * FROM approval_requests WHERE id=? AND agent_id=?", (req_id, agent_id)
        ).fetchone()
        if not req:
            raise HTTPException(404, "Approval request not found")
        if req["decision"] is not None:
            raise HTTPException(409, f"Request already decided: {req['decision']}")

        now = _now()
        conn.execute(
            "UPDATE approval_requests SET decision=?, reviewed_by=?, reviewed_at=?, reason=? WHERE id=?",
            (body.decision, body.reviewed_by, now, body.reason, req_id),
        )
        _audit(conn, agent_id, body.reviewed_by, "APPROVAL_DECIDED", {
            "request_id": req_id,
            "decision": body.decision,
            "reason": body.reason,
        })
    return {"request_id": req_id, "decision": body.decision}


# ─────────────────────────────────────────────────────────────────────────────
#  Eval results
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/evals")
def list_evals(agent_id: str):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM eval_results WHERE agent_id=? ORDER BY run_at DESC", (agent_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["dimensions"] = json.loads(d["dimensions"])
        result.append(d)
    return result


@app.post("/agents/{agent_id}/evals", status_code=201)
def submit_eval(agent_id: str, body: EvalCreate):
    with db() as conn:
        _ensure_agent(conn, agent_id)
        cursor = conn.execute(
            """INSERT INTO eval_results
               (agent_id, version, run_by, pass_rate, avg_score, total_cases, passed_cases, threshold_met, dimensions)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (agent_id, body.version, body.run_by, body.pass_rate, body.avg_score,
             body.total_cases, body.passed_cases, int(body.threshold_met),
             json.dumps(body.dimensions)),
        )
        eval_id = cursor.lastrowid
        _audit(conn, agent_id, body.run_by, "EVAL_SUBMITTED", {
            "eval_id": eval_id,
            "version": body.version,
            "pass_rate": body.pass_rate,
            "threshold_met": body.threshold_met,
        })
    return {"eval_id": eval_id, "threshold_met": body.threshold_met}


# ─────────────────────────────────────────────────────────────────────────────
#  Cost tracking
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/costs")
def get_costs(agent_id: str, days: int = Query(30, ge=1, le=365)):
    with db() as conn:
        rows = conn.execute(
            """SELECT * FROM cost_records WHERE agent_id=?
               AND recorded_date >= date('now', ? || ' days')
               ORDER BY recorded_date DESC""",
            (agent_id, f"-{days}"),
        ).fetchall()
        summary = conn.execute(
            """SELECT SUM(total_tokens) as total_tokens, SUM(cost_usd) as total_cost_usd,
                      SUM(review_count) as total_reviews,
                      ROUND(SUM(cost_usd)/MAX(SUM(review_count),1), 6) as cost_per_review
               FROM cost_records WHERE agent_id=?
               AND recorded_date >= date('now', ? || ' days')""",
            (agent_id, f"-{days}"),
        ).fetchone()
    return {
        "summary": _row_to_dict(summary),
        "daily": _rows_to_list(rows),
    }


@app.post("/agents/{agent_id}/costs", status_code=201)
def upsert_cost(agent_id: str, body: CostRecord):
    with db() as conn:
        _ensure_agent(conn, agent_id)
        conn.execute(
            """INSERT INTO cost_records(agent_id, recorded_date, total_tokens, input_tokens, output_tokens, cost_usd, review_count)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(agent_id, recorded_date) DO UPDATE SET
                 total_tokens=excluded.total_tokens,
                 input_tokens=excluded.input_tokens,
                 output_tokens=excluded.output_tokens,
                 cost_usd=excluded.cost_usd,
                 review_count=excluded.review_count""",
            (agent_id, body.recorded_date, body.total_tokens, body.input_tokens,
             body.output_tokens, body.cost_usd, body.review_count),
        )
    return {"status": "upserted", "date": body.recorded_date}


# ─────────────────────────────────────────────────────────────────────────────
#  Retirement workflow
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/agents/{agent_id}/retire")
def propose_retirement(agent_id: str, body: RetirementProposal):
    """
    Propose retirement: creates an approval request for Deprecated → Retired
    (or In Production → Deprecated if agent is still live).
    The caller still needs to go through maker-checker before the stage changes.
    """
    with db() as conn:
        agent = _ensure_agent(conn, agent_id)
        current = agent["current_stage"]

        # Determine the right target stage
        if current in ("In Production", "Under Monitoring"):
            to_stage = "Deprecated"
        elif current == "Deprecated":
            to_stage = "Retired"
        else:
            raise HTTPException(422, f"Cannot propose retirement from stage '{current}'")

        dup = conn.execute(
            "SELECT id FROM approval_requests WHERE agent_id=? AND to_stage=? AND decision IS NULL",
            (agent_id, to_stage),
        ).fetchone()
        if dup:
            raise HTTPException(409, "A pending retirement request already exists")

        cursor = conn.execute(
            """INSERT INTO approval_requests
               (agent_id, request_type, from_stage, to_stage, proposed_by)
               VALUES (?,?,?,?,?)""",
            (agent_id, "retirement", current, to_stage, body.proposed_by),
        )
        req_id = cursor.lastrowid
        _audit(conn, agent_id, body.proposed_by, "RETIREMENT_PROPOSED", {
            "request_id": req_id,
            "from": current,
            "to": to_stage,
            "reason": body.reason,
            "retirement_date": body.retirement_date,
        })

    return {
        "request_id": req_id,
        "status": "pending_approval",
        "proposed_transition": f"{current} → {to_stage}",
        "message": f"Retirement request created. Governance lead must approve before stage changes.",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Audit log
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/agents/{agent_id}/audit")
def agent_audit(agent_id: str, limit: int = Query(50, ge=1, le=500)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE agent_id=? ORDER BY event_time DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


@app.get("/audit")
def global_audit(limit: int = Query(100, ge=1, le=1000)):
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY event_time DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_agent(conn, agent_id: str) -> dict:
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return dict(row)
