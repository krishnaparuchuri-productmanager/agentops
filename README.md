# AgentOps — Phase 1

A minimum viable **agent governance platform** managing exactly one agent: [SOP Deviation Review](https://krishnaparuchuri.com).

Built as a learning-by-doing exercise in regulated-domain AI governance. The goal is not another agent — it's the governance layer above agents: lifecycle control, maker-checker approval, eval-gated promotion, cost tracking, and an immutable audit trail.

---

## What it does

| Capability | Status |
|---|---|
| Agent Registry | ✅ |
| Lifecycle state machine (7 stages) | ✅ |
| Maker-checker approval workflow | ✅ |
| Eval-gated promotion | ✅ |
| Cost tracking (per-agent, daily) | ✅ |
| Retirement workflow | ✅ |
| Immutable audit log | ✅ |

### Lifecycle

```
Proposed → Under Review → Approved → In Production → Under Monitoring → Deprecated → Retired
```

Every transition is validated against an explicit rule table. Approvals require a separate maker and checker. Promotion to Approved is blocked until eval results meet threshold.

---

## Stack

- **Backend:** FastAPI + SQLite (WAL mode)
- **Frontend:** Single-file React SPA (no build step)
- **Python:** 3.10+

---

## Quickstart

```bash
cd backend
pip install -r requirements.txt
python seed.py          # registers SOP Deviation Review with live eval/cost data
uvicorn main:app --reload --port 8000
```

Open `frontend/index.html` in your browser. Backend API docs at `http://localhost:8000/docs`.

---

## Structure

```
agentops/
├── backend/
│   ├── main.py          # FastAPI app — all endpoints
│   ├── database.py      # SQLite schema + connection helpers
│   ├── lifecycle.py     # Explicit transition table state machine
│   ├── seed.py          # Seeds SOP Deviation Review agent
│   └── requirements.txt
├── frontend/
│   └── index.html       # Single-file React SPA (Registry / Agent Detail / Governance Queue)
├── DECISIONS.md         # Product decision log (D-01 through D-06)
├── start.sh             # One-command startup
└── .gitignore
```

---

## Key design decisions

See [`DECISIONS.md`](DECISIONS.md) for full rationale. Summary:

- **Explicit transition table** over conditional logic — every valid `(from, to)` pair with its gate requirements in one place
- **Maker-checker** transplanted from financial transaction safety systems — same person cannot propose and approve
- **Eval gate enforced at API level** — state machine rejects the transition even with an approved request if no passing eval is attached
- **INSERT-only audit log** — no update/delete endpoint exists anywhere in the codebase
- **SQLite for Phase 1** — one agent, no concurrent write load; Postgres migration is a one-day task when Phase 2 warrants it
- **One agent deliberately** — validate patterns against a real production agent before generalizing

---

## Phase 2

Onboard MedAssist as the second managed agent. This surfaces every SOP-specific assumption hardcoded in Phase 1 — fixing those is what makes the platform genuinely multi-agent.

---

*Built by Krishna Paruchuri. Product decisions are mine; implementation is AI-assisted. That's modern senior PM work.*
