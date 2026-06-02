# AgentOps Phase 1 — Decision Log

Every product decision that shaped the platform, with rationale.
These are interview artifacts as much as they are engineering docs.

---

## D-01: Lifecycle stages (why 7, why these)

**Decision:** Proposed → Under Review → Approved → In Production → Under Monitoring → Deprecated → Retired

**Rationale:** Healthcare and fintech both treat agent/system lifecycle as a regulated artifact — you don't go from "idea" to "live" in one step. The 7-stage model mirrors the change-control workflows I worked in at IBM Watson Health (EHR system updates required: proposal, clinical review, technical approval, UAT, go-live, post-go-live monitoring). *Under Monitoring* is explicit because production agents need a watch period before they're considered stable — a lesson from claims processing systems where silent failures only surfaced after 2–3 weeks. *Deprecated* is a separate stage from *Retired* to allow a transition window: stakeholders are notified, integrations can be migrated, data is archived cleanly before final retirement.

**Trade-off accepted:** More stages = more workflow steps. Deliberate. A governance platform that collapses stages for convenience defeats its own purpose.

---

## D-02: Maker-checker approval (why two-actor gate)

**Decision:** Every lifecycle promotion and retirement requires a separate proposer (maker) and approver (checker). The same person cannot both propose and approve.

**Rationale:** Transplanted directly from TPSS (transaction processing safety systems) and CAPA workflows. In regulated domains, a single actor approving their own change is an audit finding, not just bad practice. The checker provides: (1) an independent evidence review, (2) a required written reason, (3) a second name on the audit log. This pattern also matches how I'd explain it to a CISO or compliance auditor — they recognize it immediately.

**Trade-off accepted:** Slightly more friction per transition. That friction is the product — it's what makes governance real rather than ceremonial.

---

## D-03: Eval-gated promotion (why threshold blocks the gate)

**Decision:** An agent cannot transition from *Under Review* to *Approved* without an attached eval result where `threshold_met = true`. This is enforced at the API level — the state machine rejects the transition even with an approved maker-checker request if no passing eval is attached.

**Rationale:** Eval results are the evidence base for approval. Without them, "approved" means nothing. The SOP Deviation agent has a live eval framework (87% pass / 6.67 avg across 15 golden cases vs. an always-escalate baseline of 13%). That bar exists; the governance platform simply enforces it as a gate. Any future agent onboarded must meet its own defined threshold — the threshold is per-agent, not global.

**Trade-off accepted:** Teams must run evals before requesting approval. This is a feature, not a bug.

---

## D-04: Immutable audit log (why INSERT-only)

**Decision:** The `audit_log` table is INSERT-only. No UPDATE or DELETE statements ever reference it. The API exposes no edit or delete endpoint for audit entries.

**Rationale:** An editable audit log is not an audit log — it's a mutable record that provides false assurance. This pattern is standard in HIPAA-covered systems and PCI-DSS environments. In the TPSS context I know, audit immutability was a hard compliance requirement. For AgentOps: every governance action (registration, stage transition, approval decision, eval submission) writes a timestamped, actor-attributed record. If something went wrong, you reconstruct it from the log. The log doesn't get cleaned up.

**Trade-off accepted:** No correcting typos in audit entries. Corrections are new entries.

---

## D-05: SQLite for Phase 1 (why not Postgres)

**Decision:** SQLite with WAL mode for Phase 1.

**Rationale:** Phase 1 manages exactly one agent. There is no multi-user concurrent write load that SQLite can't handle. Using Postgres would require a running server, connection pooling, and dev environment setup — all friction with no benefit for the scope. When Phase 2 adds a second agent and concurrent governance workflows, migrating to Postgres is a one-day task (schema is portable, FastAPI uses the same interface). WAL mode gives safe concurrent reads.

**Trade-off accepted:** Not web-scale. Intentionally. Shipping Phase 1 is more valuable than a Phase-1-ready-for-10,000-agents infrastructure.

---

## D-06: Single managed agent in Phase 1 (why not onboard MedAssist now)

**Decision:** Phase 1 governs exactly one agent: SOP Deviation Review. MedAssist is Phase 2.

**Rationale:** The platform's patterns (lifecycle, approval, eval gate, audit log) must be validated against a real production agent before generalizing. SOP Deviation is live, has real eval data, has real cost data, has a defined owner. Onboarding a second agent before Phase 1 patterns are proven forces premature generalization — every hardcoded assumption about SOP Deviation becomes a bug when MedAssist arrives. The right sequence is: prove the patterns on one agent, then surface the SOP-specific assumptions by onboarding a different one. That surfaces what needs to be abstracted.

**Trade-off accepted:** The platform looks narrow in Phase 1. That's accurate — it is narrow. Narrow and working beats broad and fragile.
