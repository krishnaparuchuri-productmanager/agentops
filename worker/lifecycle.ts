/**
 * AgentOps — Lifecycle State Machine (port of backend/lifecycle.py)
 *
 * Pattern: explicit allowed-transitions table.
 * Each entry is (from_stage, to_stage, requires_approval, requires_eval).
 *
 * Lifecycle:
 *   Proposed → Under Review → Approved → Under Monitoring → In Production
 *   → Deprecated → Retired
 *
 *   Under Monitoring is a canary/gradual-rollout stage BEFORE full production.
 */

export interface Transition {
  from_stage: string;
  to_stage: string;
  requires_approval: boolean; // must go through maker-checker
  requires_eval: boolean;     // eval results must be attached & threshold_met=1
}

const t = (from_stage: string, to_stage: string, requires_approval: boolean, requires_eval: boolean): Transition =>
  ({ from_stage, to_stage, requires_approval, requires_eval });

// ── Valid transitions ─────────────────────────────────────────────────────────
export const TRANSITIONS: Transition[] = [
  // Normal forward path
  t("Proposed",         "Under Review",     false, false),
  t("Under Review",     "Approved",         true,  true),
  t("Approved",         "Under Monitoring", true,  false), // start canary
  t("Under Monitoring", "In Production",    true,  false), // canary passed → full prod
  t("In Production",    "Deprecated",       true,  false), // end of life
  t("Deprecated",       "Retired",          true,  false),

  // Rejection / rollback paths
  t("Under Review",     "Proposed",         false, false), // rejected: back to start
  t("Under Monitoring", "Approved",         true,  false), // canary failed: back to approved
  t("Under Monitoring", "Deprecated",       true,  false), // canary critical failure: fast-track deprecation
  t("In Production",    "Under Review",     true,  false), // major issue: full re-review
];

export class TransitionError extends Error {}

export function getTransition(from: string, to: string): Transition | undefined {
  return TRANSITIONS.find((r) => r.from_stage === from && r.to_stage === to);
}

export function allowedNextStages(from: string): string[] {
  return TRANSITIONS.filter((r) => r.from_stage === from).map((r) => r.to_stage);
}

// Mirrors Python's repr of a list of strings, e.g. ['Approved', 'Proposed']
export const pyList = (xs: string[]) => `[${xs.map((x) => `'${x}'`).join(", ")}]`;

export function validateTransition(
  from: string,
  to: string,
  hasApprovedRequest = false,
  hasPassingEval = false,
): Transition {
  const rule = getTransition(from, to);
  if (!rule) {
    const valid = allowedNextStages(from);
    throw new TransitionError(
      `'${from}' → '${to}' is not a valid transition. ` +
      `Valid next stages: ${pyList(valid.length ? valid : ["none (terminal state)"])}`,
    );
  }
  if (rule.requires_approval && !hasApprovedRequest) {
    throw new TransitionError(
      `Transition '${from}' → '${to}' requires an approved ` +
      `maker-checker request. Submit an approval request first.`,
    );
  }
  if (rule.requires_eval && !hasPassingEval) {
    throw new TransitionError(
      `Transition '${from}' → '${to}' requires attached eval ` +
      `results with threshold_met=true. Run evals and attach results first.`,
    );
  }
  return rule;
}
