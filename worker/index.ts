/**
 * AgentOps — Cloudflare Worker API (port of backend/main.py, FastAPI → Workers + D1)
 *
 * Static frontend files are served by Workers Static Assets (wrangler.jsonc "assets");
 * this Worker only runs for paths that don't match a file.
 *
 * Routes are served both under /api (used by the frontend, same origin) and at the
 * root (kept for external callers such as the GMP app and the push_*.py scripts).
 *
 * Endpoints:
 *   GET  /health
 *   GET  /agents                              POST /agents
 *   GET  /agents/{id}                         PATCH /agents/{id}     DELETE /agents/{id}
 *   GET  /agents/{id}/versions                POST /agents/{id}/versions
 *   POST /agents/{id}/versions/{v}/activate
 *   GET  /agents/{id}/transitions             POST /agents/{id}/transitions
 *   GET  /agents/{id}/approvals               POST /agents/{id}/approvals
 *   POST /agents/{id}/approvals/{req}/decision
 *   GET  /approvals
 *   GET  /agents/{id}/evals                   POST /agents/{id}/evals
 *   GET  /agents/{id}/costs                   POST /agents/{id}/costs
 *   POST /agents/{id}/retire
 *   GET  /agents/{id}/audit                   GET  /audit
 *   GET  /agents/{id}/traces                  POST /agents/{id}/traces
 *   GET  /agents/{id}/alerts                  POST /agents/{id}/alerts
 *   POST /agents/{id}/alerts/{alert}/resolve  GET  /alerts
 */

import { allowedNextStages, getTransition, pyList, TransitionError, validateTransition } from "./lifecycle";

// Minimal D1 typings so the Worker needs no extra packages.
interface D1Result<T = Row> { results: T[]; meta: { last_row_id: number; changes: number } }
interface D1Stmt {
  bind(...values: unknown[]): D1Stmt;
  first<T = Row>(): Promise<T | null>;
  all<T = Row>(): Promise<D1Result<T>>;
  run(): Promise<D1Result>;
}
interface D1Database { prepare(sql: string): D1Stmt; batch(stmts: D1Stmt[]): Promise<D1Result[]> }
interface Env { DB: D1Database }
type Row = Record<string, any>;

// ─────────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────────

class HttpError extends Error {
  constructor(public status: number, public detail: unknown) { super(String(detail)); }
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "*",
  "Access-Control-Allow-Headers": "*",
};

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...CORS } });

// Same format as the Python _now(): UTC, seconds precision, no timezone suffix.
const now = () => new Date().toISOString().slice(0, 19);

// Same text as Python's json.dumps() (", " / ": " separators, ASCII-only), so stored JSON
// columns look identical whichever backend wrote them.
function dumps(v: unknown): string {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return `[${v.map(dumps).join(", ")}]`;
  if (typeof v === "object") {
    return `{${Object.entries(v as Row).map(([k, x]) => `${dumps(k)}: ${dumps(x)}`).join(", ")}}`;
  }
  if (typeof v === "string") {
    return JSON.stringify(v).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  }
  return JSON.stringify(v);
}

const parseJson = (raw: unknown, fallback: unknown) => {
  try { return JSON.parse(raw as string); } catch { return fallback; }
};

function audit(env: Env, agentId: string | null, actor: string, action: string, payload: Row): D1Stmt {
  return env.DB.prepare("INSERT INTO audit_log(event_time, agent_id, actor, action, payload) VALUES (?,?,?,?,?)")
    .bind(now(), agentId, actor, action, dumps(payload));
}

async function ensureAgent(env: Env, agentId: string): Promise<Row> {
  const row = await env.DB.prepare("SELECT * FROM agents WHERE id=?").bind(agentId).first();
  if (!row) throw new HttpError(404, `Agent '${agentId}' not found`);
  return row;
}

// ── Request-body validation (stands in for the Pydantic models) ──────────────

type FieldType = "str" | "int" | "float" | "bool" | "dict";
interface FieldSpec { type: FieldType; required?: boolean; default?: unknown; pattern?: RegExp; min?: number; max?: number }

function validate(body: unknown, spec: Record<string, FieldSpec>): Row {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new HttpError(422, "Request body must be a JSON object");
  }
  const src = body as Row;
  const out: Row = {};
  for (const [key, f] of Object.entries(spec)) {
    let v = src[key];
    if (v === undefined || v === null) {
      if (f.required) throw new HttpError(422, `Field '${key}' is required`);
      out[key] = typeof f.default === "function" ? (f.default as () => unknown)() : (f.default ?? null);
      continue;
    }
    const bad = () => new HttpError(422, `Field '${key}' must be of type ${f.type}`);
    switch (f.type) {
      case "str": if (typeof v !== "string") throw bad(); break;
      case "int": if (typeof v !== "number" || !Number.isInteger(v)) throw bad(); break;
      case "float": if (typeof v !== "number") throw bad(); break;
      case "bool": if (typeof v !== "boolean") throw bad(); break;
      case "dict": if (typeof v !== "object" || Array.isArray(v)) throw bad(); break;
    }
    if (f.pattern && !f.pattern.test(v)) throw new HttpError(422, `Field '${key}' does not match ${f.pattern}`);
    if (f.min !== undefined && v < f.min) throw new HttpError(422, `Field '${key}' must be >= ${f.min}`);
    if (f.max !== undefined && v > f.max) throw new HttpError(422, `Field '${key}' must be <= ${f.max}`);
    out[key] = v;
  }
  return out;
}

const str = (required = false, def: unknown = null, pattern?: RegExp): FieldSpec => ({ type: "str", required, default: def, pattern });
const dict = (): FieldSpec => ({ type: "dict", default: () => ({}) });

// ── Query-string parsing (stands in for FastAPI Query()) ─────────────────────

function qInt(url: URL, name: string, def: number, min?: number, max?: number): number {
  const raw = url.searchParams.get(name);
  if (raw === null) return def;
  const n = Number(raw);
  if (!Number.isInteger(n)) throw new HttpError(422, `Query '${name}' must be an integer`);
  if ((min !== undefined && n < min) || (max !== undefined && n > max)) {
    throw new HttpError(422, `Query '${name}' must be between ${min} and ${max}`);
  }
  return n;
}

function qBool(url: URL, name: string, def: boolean): boolean {
  const raw = url.searchParams.get(name);
  if (raw === null) return def;
  const v = raw.toLowerCase();
  if (["true", "1", "yes", "on"].includes(v)) return true;
  if (["false", "0", "no", "off"].includes(v)) return false;
  throw new HttpError(422, `Query '${name}' must be a boolean`);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Handlers
// ─────────────────────────────────────────────────────────────────────────────

interface Ctx { env: Env; url: URL; params: Record<string, string>; body: () => Promise<unknown> }
type Handler = (c: Ctx) => Promise<Response>;

// ── Registry ──

const listAgents: Handler = async ({ env }) =>
  json((await env.DB.prepare("SELECT * FROM agents ORDER BY created_at DESC").all()).results);

const createAgent: Handler = async ({ env, body }) => {
  const b = validate(await body(), {
    id: str(true, null, /^[a-z0-9-]+$/), name: str(true), description: str(), owner: str(true),
    classification: dict(), actor: str(false, "system"),
  });
  const existing = await env.DB.prepare("SELECT id FROM agents WHERE id=?").bind(b.id).first();
  if (existing) throw new HttpError(400, `Agent '${b.id}' already exists`);
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO agents(id, name, description, owner, classification, current_stage, created_at, updated_at)
       VALUES (?,?,?,?,?,?,?,?)`,
    ).bind(b.id, b.name, b.description, b.owner, dumps(b.classification), "Proposed", now(), now()),
    env.DB.prepare(
      "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason) VALUES (?,?,?,?,?)",
    ).bind(b.id, null, "Proposed", b.actor, "Initial registration"),
    audit(env, b.id, b.actor, "AGENT_REGISTERED", { agent_id: b.id, name: b.name }),
  ]);
  return json({ id: b.id, stage: "Proposed" }, 201);
};

const updateAgent: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    name: str(), description: str(), owner: str(),
    classification: { type: "dict" }, actor: str(false, "system"),
  });
  await ensureAgent(env, agentId);
  const updates: Row = {};
  if (b.name !== null) updates.name = b.name;
  if (b.description !== null) updates.description = b.description;
  if (b.owner !== null) updates.owner = b.owner;
  if (b.classification !== null) updates.classification = dumps(b.classification);
  if (!Object.keys(updates).length) return json({ id: agentId, status: "no changes" });
  const changed = { ...updates };
  updates.updated_at = now();
  // Column names come from the fixed keyset above, never from user input.
  const setClause = Object.keys(updates).map((k) => `${k}=?`).join(", ");
  await env.DB.batch([
    env.DB.prepare(`UPDATE agents SET ${setClause} WHERE id=?`).bind(...Object.values(updates), agentId),
    audit(env, agentId, b.actor, "AGENT_UPDATED", changed),
  ]);
  return json({ id: agentId, status: "updated" });
};

const getAgent: Handler = async ({ env, params }) => {
  const agentId = params.agent_id;
  const agent = await env.DB.prepare("SELECT * FROM agents WHERE id=?").bind(agentId).first();
  if (!agent) throw new HttpError(404, `Agent '${agentId}' not found`);
  agent.classification = parseJson(agent.classification, {});

  // Attach latest eval summary
  agent.latest_eval = await env.DB.prepare(
    "SELECT * FROM eval_results WHERE agent_id=? ORDER BY run_at DESC LIMIT 1",
  ).bind(agentId).first();

  // Attach cost summary (last 30 days)
  agent.cost_30d = await env.DB.prepare(
    `SELECT SUM(total_tokens) AS total_tokens, SUM(cost_usd) AS total_cost_usd,
            SUM(review_count) AS total_reviews
     FROM cost_records WHERE agent_id=?
     AND recorded_date >= date('now', '-30 days')`,
  ).bind(agentId).first();

  // Pending approval count
  const pending = await env.DB.prepare(
    "SELECT COUNT(*) AS cnt FROM approval_requests WHERE agent_id=? AND decision IS NULL",
  ).bind(agentId).first();
  agent.pending_approvals = pending?.cnt ?? 0;

  agent.allowed_transitions = allowedNextStages(agent.current_stage);
  return json(agent);
};

const deleteAgent: Handler = async ({ env, params }) => {
  // Hard-delete an agent and all its related data. Use only to remove stale / incorrectly-registered agents.
  const agentId = params.agent_id;
  await ensureAgent(env, agentId);
  const tables = ["audit_log", "approval_requests", "cost_records", "eval_results",
    "lifecycle_transitions", "agent_versions", "agent_traces", "agent_alerts"];
  await env.DB.batch([
    ...tables.map((t) => env.DB.prepare(`DELETE FROM ${t} WHERE agent_id=?`).bind(agentId)),
    env.DB.prepare("DELETE FROM agents WHERE id=?").bind(agentId),
  ]);
  return json({ deleted: agentId });
};

// ── Versions ──

const listVersions: Handler = async ({ env, params }) =>
  json((await env.DB.prepare("SELECT * FROM agent_versions WHERE agent_id=? ORDER BY created_at DESC")
    .bind(params.agent_id).all()).results);

const createVersion: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    version: str(true), model: str(), config_snapshot: { type: "dict" }, changelog: str(), created_by: str(true),
  });
  await ensureAgent(env, agentId);
  await env.DB.batch([
    env.DB.prepare(
      "INSERT INTO agent_versions(agent_id, version, model, config_snapshot, changelog, status, created_by) VALUES (?,?,?,?,?,?,?)",
    ).bind(agentId, b.version, b.model, dumps(b.config_snapshot ?? {}), b.changelog, "draft", b.created_by),
    audit(env, agentId, b.created_by, "VERSION_REGISTERED", { version: b.version, model: b.model, changelog: b.changelog }),
  ]);
  return json({ agent_id: agentId, version: b.version, status: "draft" }, 201);
};

const activateVersion: Handler = async ({ env, params, body }) => {
  const { agent_id: agentId, version } = params;
  const raw = await body();
  const b = validate(raw ?? {}, { activated_by: str(false, "Governance User") });
  await ensureAgent(env, agentId);
  const ver = await env.DB.prepare("SELECT * FROM agent_versions WHERE agent_id=? AND version=?")
    .bind(agentId, version).first();
  if (!ver) throw new HttpError(404, `Version '${version}' not found for agent '${agentId}'`);
  await env.DB.batch([
    // Roll back any currently active version, then activate this one
    env.DB.prepare("UPDATE agent_versions SET status='rolled_back' WHERE agent_id=? AND status='active'").bind(agentId),
    env.DB.prepare("UPDATE agent_versions SET status='active' WHERE agent_id=? AND version=?").bind(agentId, version),
    audit(env, agentId, b.activated_by, "VERSION_ACTIVATED", { version }),
  ]);
  return json({ agent_id: agentId, version, status: "active" });
};

// ── Lifecycle transitions ──

const getAllowedTransitions: Handler = async ({ env, params }) => {
  const agent = await ensureAgent(env, params.agent_id);
  return json({ current_stage: agent.current_stage, allowed_next: allowedNextStages(agent.current_stage) });
};

const executeTransition: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), { to_stage: str(true), triggered_by: str(true), reason: str() });
  const agent = await ensureAgent(env, agentId);
  const current = agent.current_stage;

  // Check for approved request if transition requires one
  const approvedReq = await env.DB.prepare(
    `SELECT id FROM approval_requests
     WHERE agent_id=? AND to_stage=? AND decision='approved'
     ORDER BY reviewed_at DESC LIMIT 1`,
  ).bind(agentId, b.to_stage).first();

  // Check for passing eval
  const passingEval = await env.DB.prepare(
    "SELECT id FROM eval_results WHERE agent_id=? AND threshold_met=1 ORDER BY run_at DESC LIMIT 1",
  ).bind(agentId).first();

  try {
    validateTransition(current, b.to_stage, approvedReq !== null, passingEval !== null);
  } catch (e) {
    if (e instanceof TransitionError) throw new HttpError(422, e.message);
    throw e;
  }

  const ts = now();
  await env.DB.batch([
    env.DB.prepare("UPDATE agents SET current_stage=?, updated_at=? WHERE id=?").bind(b.to_stage, ts, agentId),
    env.DB.prepare(
      "INSERT INTO lifecycle_transitions(agent_id, from_stage, to_stage, triggered_by, reason) VALUES (?,?,?,?,?)",
    ).bind(agentId, current, b.to_stage, b.triggered_by, b.reason),
    audit(env, agentId, b.triggered_by, "STAGE_TRANSITION", { from: current, to: b.to_stage, reason: b.reason }),
  ]);
  return json({ agent_id: agentId, from_stage: current, to_stage: b.to_stage });
};

// ── Maker-checker approval workflow ──

const listApprovals: Handler = async ({ env, params, url }) => {
  const pendingOnly = qBool(url, "pending_only", false);
  const sql = pendingOnly
    ? "SELECT * FROM approval_requests WHERE agent_id=? AND decision IS NULL ORDER BY proposed_at DESC"
    : "SELECT * FROM approval_requests WHERE agent_id=? ORDER BY proposed_at DESC";
  return json((await env.DB.prepare(sql).bind(params.agent_id).all()).results);
};

// Inserts an approval request and its audit event atomically; the audit payload
// gets the new row id via last_insert_rowid() inside the same batch.
async function insertApproval(env: Env, agentId: string, cols: Row, actor: string, action: string, payload: Row) {
  const keys = Object.keys(cols);
  const [ins] = await env.DB.batch([
    env.DB.prepare(`INSERT INTO approval_requests (${keys.join(", ")}) VALUES (${keys.map(() => "?").join(",")})`)
      .bind(...Object.values(cols)),
    env.DB.prepare(
      `INSERT INTO audit_log(event_time, agent_id, actor, action, payload)
       VALUES (?,?,?,?, json_set(?, '$.request_id', last_insert_rowid()))`,
    ).bind(now(), agentId, actor, action, dumps(payload)),
  ]);
  return ins.meta.last_row_id;
}

const proposeApproval: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    request_type: str(true, null, /^(promotion|retirement)$/), from_stage: str(true), to_stage: str(true),
    proposed_by: str(true), eval_result_id: { type: "int" }, notes: str(),
  });
  const agent = await ensureAgent(env, agentId);
  // Only check the transition rule exists; valid-but-gated transitions need approval, not a 422.
  if (!getTransition(agent.current_stage, b.to_stage)) {
    const valid = allowedNextStages(agent.current_stage);
    throw new HttpError(422,
      `'${agent.current_stage}' → '${b.to_stage}' is not a valid transition. ` +
      `Valid next stages: ${pyList(valid.length ? valid : ["none (terminal state)"])}`);
  }

  // Block duplicate pending requests for same transition
  const dup = await env.DB.prepare(
    "SELECT id FROM approval_requests WHERE agent_id=? AND to_stage=? AND decision IS NULL",
  ).bind(agentId, b.to_stage).first();
  if (dup) throw new HttpError(409, "A pending approval request already exists for this transition");

  const reqId = await insertApproval(env, agentId, {
    agent_id: agentId, request_type: b.request_type, from_stage: b.from_stage, to_stage: b.to_stage,
    proposed_by: b.proposed_by, eval_result_id: b.eval_result_id, notes: b.notes,
  }, b.proposed_by, "APPROVAL_REQUESTED", {
    type: b.request_type, from: b.from_stage, to: b.to_stage, notes: b.notes,
  });
  return json({ request_id: reqId, status: "pending" }, 201);
};

const decideApproval: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const reqId = Number(params.req_id);
  if (!Number.isInteger(reqId)) throw new HttpError(422, "req_id must be an integer");
  const b = validate(await body(), {
    decision: str(true, null, /^(approved|rejected)$/), reviewed_by: str(true), reason: str(),
  });
  const req = await env.DB.prepare("SELECT * FROM approval_requests WHERE id=? AND agent_id=?")
    .bind(reqId, agentId).first();
  if (!req) throw new HttpError(404, "Approval request not found");
  if (req.decision !== null) throw new HttpError(409, `Request already decided: ${req.decision}`);

  await env.DB.batch([
    env.DB.prepare("UPDATE approval_requests SET decision=?, reviewed_by=?, reviewed_at=?, reason=? WHERE id=?")
      .bind(b.decision, b.reviewed_by, now(), b.reason, reqId),
    audit(env, agentId, b.reviewed_by, "APPROVAL_DECIDED", { request_id: reqId, decision: b.decision, reason: b.reason }),
  ]);
  return json({ request_id: reqId, decision: b.decision });
};

// Global approvals feed (for Governance Queue activity view)
const listAllApprovals: Handler = async ({ env, url }) => {
  const decidedOnly = qBool(url, "decided_only", false);
  const limit = qInt(url, "limit", 50);
  const sql = decidedOnly
    ? `SELECT ar.*, a.name AS agent_name FROM approval_requests ar
       JOIN agents a ON a.id = ar.agent_id
       WHERE ar.decision IS NOT NULL ORDER BY ar.reviewed_at DESC LIMIT ?`
    : `SELECT ar.*, a.name AS agent_name FROM approval_requests ar
       JOIN agents a ON a.id = ar.agent_id
       ORDER BY ar.proposed_at DESC LIMIT ?`;
  return json((await env.DB.prepare(sql).bind(limit).all()).results);
};

// ── Eval results ──

const listEvals: Handler = async ({ env, params }) => {
  const { results } = await env.DB.prepare("SELECT * FROM eval_results WHERE agent_id=? ORDER BY run_at DESC")
    .bind(params.agent_id).all();
  return json(results.map((r) => ({ ...r, dimensions: parseJson(r.dimensions, {}) })));
};

const submitEval: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    version: str(true), run_by: str(true),
    pass_rate: { type: "float", required: true, min: 0, max: 1 }, avg_score: { type: "float", required: true },
    total_cases: { type: "int", required: true }, passed_cases: { type: "int", required: true },
    threshold_met: { type: "bool", required: true }, dimensions: dict(),
  });
  await ensureAgent(env, agentId);
  const [ins] = await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO eval_results
       (agent_id, version, run_by, pass_rate, avg_score, total_cases, passed_cases, threshold_met, dimensions)
       VALUES (?,?,?,?,?,?,?,?,?)`,
    ).bind(agentId, b.version, b.run_by, b.pass_rate, b.avg_score, b.total_cases, b.passed_cases,
      b.threshold_met ? 1 : 0, dumps(b.dimensions)),
    env.DB.prepare(
      `INSERT INTO audit_log(event_time, agent_id, actor, action, payload)
       VALUES (?,?,?,?, json_set(?, '$.eval_id', last_insert_rowid()))`,
    ).bind(now(), agentId, b.run_by, "EVAL_SUBMITTED",
      dumps({ version: b.version, pass_rate: b.pass_rate, threshold_met: b.threshold_met })),
  ]);
  return json({ eval_id: ins.meta.last_row_id, threshold_met: b.threshold_met }, 201);
};

// ── Cost tracking ──

const getCosts: Handler = async ({ env, params, url }) => {
  const days = qInt(url, "days", 30, 1, 365);
  const agentId = params.agent_id;
  const [daily, summary] = await Promise.all([
    env.DB.prepare(
      `SELECT * FROM cost_records WHERE agent_id=?
       AND recorded_date >= date('now', ? || ' days')
       ORDER BY recorded_date DESC`,
    ).bind(agentId, `-${days}`).all(),
    env.DB.prepare(
      `SELECT SUM(total_tokens) as total_tokens, SUM(cost_usd) as total_cost_usd,
              SUM(review_count) as total_reviews,
              ROUND(SUM(cost_usd)/MAX(SUM(review_count),1), 6) as cost_per_review
       FROM cost_records WHERE agent_id=?
       AND recorded_date >= date('now', ? || ' days')`,
    ).bind(agentId, `-${days}`).first(),
  ]);
  return json({ summary, daily: daily.results });
};

const upsertCost: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    recorded_date: str(true), total_tokens: { type: "int", default: 0 }, input_tokens: { type: "int", default: 0 },
    output_tokens: { type: "int", default: 0 }, cost_usd: { type: "float", default: 0 },
    review_count: { type: "int", default: 0 },
  });
  await ensureAgent(env, agentId);
  await env.DB.prepare(
    `INSERT INTO cost_records(agent_id, recorded_date, total_tokens, input_tokens, output_tokens, cost_usd, review_count)
     VALUES (?,?,?,?,?,?,?)
     ON CONFLICT(agent_id, recorded_date) DO UPDATE SET
       total_tokens=excluded.total_tokens,
       input_tokens=excluded.input_tokens,
       output_tokens=excluded.output_tokens,
       cost_usd=excluded.cost_usd,
       review_count=excluded.review_count`,
  ).bind(agentId, b.recorded_date, b.total_tokens, b.input_tokens, b.output_tokens, b.cost_usd, b.review_count).run();
  return json({ status: "upserted", date: b.recorded_date }, 201);
};

// ── Retirement workflow ──

const proposeRetirement: Handler = async ({ env, params, body }) => {
  // Creates an approval request for Deprecated → Retired (or In Production → Deprecated).
  // The caller still needs to go through maker-checker before the stage changes.
  const agentId = params.agent_id;
  const b = validate(await body(), { proposed_by: str(true), reason: str(true), retirement_date: str() });
  const agent = await ensureAgent(env, agentId);
  const current = agent.current_stage;

  let toStage: string;
  if (current === "In Production" || current === "Under Monitoring") toStage = "Deprecated";
  else if (current === "Deprecated") toStage = "Retired";
  else throw new HttpError(422, `Cannot propose retirement from stage '${current}'`);

  const dup = await env.DB.prepare(
    "SELECT id FROM approval_requests WHERE agent_id=? AND to_stage=? AND decision IS NULL",
  ).bind(agentId, toStage).first();
  if (dup) throw new HttpError(409, "A pending retirement request already exists");

  const reqId = await insertApproval(env, agentId, {
    agent_id: agentId, request_type: "retirement", from_stage: current, to_stage: toStage, proposed_by: b.proposed_by,
  }, b.proposed_by, "RETIREMENT_PROPOSED", {
    from: current, to: toStage, reason: b.reason, retirement_date: b.retirement_date,
  });
  return json({
    request_id: reqId,
    status: "pending_approval",
    proposed_transition: `${current} → ${toStage}`,
    message: "Retirement request created. Governance lead must approve before stage changes.",
  });
};

// ── Audit log ──

const withPayload = (rows: Row[]) =>
  rows.map((r) => ({ ...r, payload: parseJson(r.payload, { _raw: String(r.payload) }) }));

const agentAudit: Handler = async ({ env, params, url }) => {
  const limit = qInt(url, "limit", 50, 1, 500);
  await ensureAgent(env, params.agent_id);
  const { results } = await env.DB.prepare(
    "SELECT * FROM audit_log WHERE agent_id=? ORDER BY event_time DESC LIMIT ?",
  ).bind(params.agent_id, limit).all();
  return json(withPayload(results));
};

const globalAudit: Handler = async ({ env, url }) => {
  const limit = qInt(url, "limit", 100, 1, 1000);
  const { results } = await env.DB.prepare("SELECT * FROM audit_log ORDER BY event_time DESC LIMIT ?").bind(limit).all();
  return json(withPayload(results));
};

// ── Execution traces ──

const ingestTrace: Handler = async ({ env, params, body }) => {
  // Receive a single execution trace from an agent app. INSERT OR IGNORE on trace_id — safe to repeat.
  const agentId = params.agent_id;
  const b = validate(await body(), {
    trace_id: str(true), timestamp: str(true), user_input: str(), severity: str(),
    qa_escalation: { type: "bool", default: false }, classification: str(),
    input_tokens: { type: "int", default: 0 }, output_tokens: { type: "int", default: 0 },
    cost_usd: { type: "float", default: 0 }, latency_ms: { type: "int", default: 0 },
    is_fallback: { type: "bool", default: false }, model_output: str(), source_app: str(),
  });
  await ensureAgent(env, agentId);
  // Trim user_input to 500 chars to avoid bloating the DB with full deviation text.
  const inputExcerpt = (b.user_input ?? "").slice(0, 500) || null;
  await env.DB.prepare(
    `INSERT OR IGNORE INTO agent_traces
     (agent_id, trace_id, timestamp, user_input, severity, qa_escalation,
      classification, input_tokens, output_tokens, cost_usd, latency_ms,
      is_fallback, model_output, source_app)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  ).bind(
    agentId, b.trace_id, b.timestamp, inputExcerpt, b.severity, b.qa_escalation ? 1 : 0, b.classification,
    b.input_tokens, b.output_tokens, Math.round(b.cost_usd * 1e6) / 1e6, b.latency_ms,
    b.is_fallback ? 1 : 0, b.model_output, b.source_app,
  ).run();
  return json({ trace_id: b.trace_id, status: "accepted" }, 201);
};

const listTraces: Handler = async ({ env, params, url }) => {
  const limit = qInt(url, "limit", 50, 1, 500);
  const offset = qInt(url, "offset", 0, 0);
  await ensureAgent(env, params.agent_id);
  const [rows, total] = await Promise.all([
    env.DB.prepare(
      `SELECT * FROM agent_traces WHERE agent_id=?
       ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?`,
    ).bind(params.agent_id, limit, offset).all(),
    env.DB.prepare("SELECT COUNT(*) AS n FROM agent_traces WHERE agent_id=?").bind(params.agent_id).first(),
  ]);
  // model_output is returned as parsed JSON when valid, else as the raw string.
  const traces = rows.results.map((r) =>
    r.model_output ? { ...r, model_output: parseJson(r.model_output, r.model_output) } : r);
  return json({ total: total?.n ?? 0, traces });
};

// ── Alerts ──

const withMetadata = (rows: Row[]) => rows.map((r) => ({ ...r, metadata: parseJson(r.metadata, {}) }));

const SEVERITY_ORDER = "CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END";

const listAlerts: Handler = async ({ env, params, url }) => {
  const activeOnly = qBool(url, "active_only", true);
  const limit = qInt(url, "limit", 50, 1, 200);
  await ensureAgent(env, params.agent_id);
  const sql = activeOnly
    ? `SELECT * FROM agent_alerts WHERE agent_id=? AND resolved_at IS NULL
       ORDER BY ${SEVERITY_ORDER}, triggered_at DESC LIMIT ?`
    : "SELECT * FROM agent_alerts WHERE agent_id=? ORDER BY triggered_at DESC LIMIT ?";
  return json(withMetadata((await env.DB.prepare(sql).bind(params.agent_id, limit).all()).results));
};

const createAlert: Handler = async ({ env, params, body }) => {
  const agentId = params.agent_id;
  const b = validate(await body(), {
    alert_type: str(true), severity: str(true), title: str(true), message: str(true),
    triggered_at: str(), metadata: dict(),
  });
  await ensureAgent(env, agentId);
  const [ins] = await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO agent_alerts (agent_id, alert_type, severity, title, message, triggered_at, metadata)
       VALUES (?,?,?,?,?,?,?)`,
    ).bind(agentId, b.alert_type, b.severity, b.title, b.message, b.triggered_at ?? now(), dumps(b.metadata)),
    env.DB.prepare(
      `INSERT INTO audit_log(event_time, agent_id, actor, action, payload)
       VALUES (?,?,?,?, json_set(?, '$.alert_id', last_insert_rowid()))`,
    ).bind(now(), agentId, "system", "ALERT_TRIGGERED",
      dumps({ type: b.alert_type, severity: b.severity, title: b.title })),
  ]);
  return json({ alert_id: ins.meta.last_row_id, status: "active" }, 201);
};

const resolveAlert: Handler = async ({ env, params, url }) => {
  const agentId = params.agent_id;
  const alertId = Number(params.alert_id);
  if (!Number.isInteger(alertId)) throw new HttpError(422, "alert_id must be an integer");
  const resolvedBy = url.searchParams.get("resolved_by") ?? "Governance User";
  await ensureAgent(env, agentId);
  const alert = await env.DB.prepare("SELECT * FROM agent_alerts WHERE id=? AND agent_id=?").bind(alertId, agentId).first();
  if (!alert) throw new HttpError(404, "Alert not found");
  if (alert.resolved_at) throw new HttpError(409, "Alert already resolved");
  await env.DB.batch([
    env.DB.prepare("UPDATE agent_alerts SET resolved_at=?, resolved_by=? WHERE id=?").bind(now(), resolvedBy, alertId),
    audit(env, agentId, resolvedBy, "ALERT_RESOLVED", { alert_id: alertId }),
  ]);
  return json({ alert_id: alertId, status: "resolved" });
};

// Alerts across ALL agents, joined with agent name. Used by Governance Queue.
const listAllAlerts: Handler = async ({ env, url }) => {
  const activeOnly = qBool(url, "active_only", true);
  const limit = qInt(url, "limit", 100, 1, 500);
  const sql = activeOnly
    ? `SELECT al.*, a.name AS agent_name FROM agent_alerts al
       JOIN agents a ON a.id = al.agent_id
       WHERE al.resolved_at IS NULL
       ORDER BY ${SEVERITY_ORDER.replace("severity", "al.severity")}, al.triggered_at DESC LIMIT ?`
    : `SELECT al.*, a.name AS agent_name FROM agent_alerts al
       JOIN agents a ON a.id = al.agent_id
       ORDER BY al.triggered_at DESC LIMIT ?`;
  return json(withMetadata((await env.DB.prepare(sql).bind(limit).all()).results));
};

// ─────────────────────────────────────────────────────────────────────────────
//  Router
// ─────────────────────────────────────────────────────────────────────────────

const ROUTES: [string, string, Handler][] = [
  ["GET", "/health", async () => json({ status: "ok", service: "agentops", version: "1.0.0" })],
  ["GET", "/agents", listAgents],
  ["POST", "/agents", createAgent],
  ["GET", "/agents/:agent_id", getAgent],
  ["PATCH", "/agents/:agent_id", updateAgent],
  ["DELETE", "/agents/:agent_id", deleteAgent],
  ["GET", "/agents/:agent_id/versions", listVersions],
  ["POST", "/agents/:agent_id/versions", createVersion],
  ["POST", "/agents/:agent_id/versions/:version/activate", activateVersion],
  ["GET", "/agents/:agent_id/transitions", getAllowedTransitions],
  ["POST", "/agents/:agent_id/transitions", executeTransition],
  ["GET", "/agents/:agent_id/approvals", listApprovals],
  ["POST", "/agents/:agent_id/approvals", proposeApproval],
  ["POST", "/agents/:agent_id/approvals/:req_id/decision", decideApproval],
  ["GET", "/approvals", listAllApprovals],
  ["GET", "/agents/:agent_id/evals", listEvals],
  ["POST", "/agents/:agent_id/evals", submitEval],
  ["GET", "/agents/:agent_id/costs", getCosts],
  ["POST", "/agents/:agent_id/costs", upsertCost],
  ["POST", "/agents/:agent_id/retire", proposeRetirement],
  ["GET", "/agents/:agent_id/audit", agentAudit],
  ["GET", "/audit", globalAudit],
  ["GET", "/agents/:agent_id/traces", listTraces],
  ["POST", "/agents/:agent_id/traces", ingestTrace],
  ["GET", "/agents/:agent_id/alerts", listAlerts],
  ["POST", "/agents/:agent_id/alerts", createAlert],
  ["POST", "/agents/:agent_id/alerts/:alert_id/resolve", resolveAlert],
  ["GET", "/alerts", listAllAlerts],
];

function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split("/"), s = path.split("/");
  if (p.length !== s.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(s[i]);
    else if (p[i] !== s[i]) return null;
  }
  return params;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    const url = new URL(request.url);
    let path = url.pathname.replace(/\/+$/, "") || "/";
    if (path === "/api" || path.startsWith("/api/")) path = path.slice(4) || "/";

    let pathMatched = false;
    for (const [method, pattern, handler] of ROUTES) {
      const params = match(pattern, path);
      if (!params) continue;
      pathMatched = true;
      if (method !== request.method) continue;
      const body = async () => {
        const text = await request.text();
        if (!text) return null;
        try { return JSON.parse(text); } catch { throw new HttpError(422, "Request body is not valid JSON"); }
      };
      try {
        return await handler({ env, url, params, body });
      } catch (e) {
        if (e instanceof HttpError) return json({ detail: e.detail }, e.status);
        console.error(e);
        return json({ detail: "Internal Server Error" }, 500);
      }
    }
    return pathMatched
      ? json({ detail: "Method Not Allowed" }, 405)
      : json({ detail: "Not Found" }, 404);
  },
};
