"""
AgentOps — Lifecycle State Machine

Pattern: explicit allowed-transitions table.
Each entry is (from_stage, to_stage, requires_approval, requires_eval).

Why an explicit table instead of code conditionals?
- Every valid transition is visible in one place — no hunting through if-chains.
- Adding a new transition means adding one row, not finding the right if-block.
- requires_eval is a first-class constraint, not a buried business rule.

Lifecycle:
  Proposed → Under Review → Approved → In Production → Under Monitoring
  → Deprecated → Retired
  Plus rejection/rollback paths.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Transition:
    from_stage: str
    to_stage: str
    requires_approval: bool   # must go through maker-checker
    requires_eval: bool       # eval results must be attached & threshold_met=1


# ── Valid transitions ─────────────────────────────────────────────────────────
TRANSITIONS: list[Transition] = [
    # Normal forward path
    Transition("Proposed",          "Under Review",     requires_approval=False, requires_eval=False),
    Transition("Under Review",      "Approved",         requires_approval=True,  requires_eval=True),
    Transition("Approved",          "In Production",    requires_approval=True,  requires_eval=False),
    Transition("In Production",     "Under Monitoring", requires_approval=False, requires_eval=False),
    Transition("Under Monitoring",  "Deprecated",       requires_approval=True,  requires_eval=False),
    Transition("Deprecated",        "Retired",          requires_approval=True,  requires_eval=False),

    # Rejection / rollback paths
    Transition("Under Review",      "Proposed",         requires_approval=False, requires_eval=False),  # rejected: back to start
    Transition("In Production",     "Under Review",     requires_approval=True,  requires_eval=False),  # re-review if issues found
    Transition("Under Monitoring",  "In Production",    requires_approval=True,  requires_eval=False),  # monitoring resolved, back to prod
    Transition("Under Monitoring",  "Deprecated",       requires_approval=True,  requires_eval=False),  # fast-track deprecation

    # Emergency retirement
    Transition("In Production",     "Deprecated",       requires_approval=True,  requires_eval=False),
]

# Build lookup: (from, to) → Transition
_TRANSITION_MAP: dict[tuple[str, str], Transition] = {
    (t.from_stage, t.to_stage): t for t in TRANSITIONS
}

# All valid stages (ordered for display)
STAGES = [
    "Proposed",
    "Under Review",
    "Approved",
    "In Production",
    "Under Monitoring",
    "Deprecated",
    "Retired",
]


class TransitionError(Exception):
    """Raised when a lifecycle transition is invalid or blocked."""
    pass


def get_transition(from_stage: str, to_stage: str) -> Optional[Transition]:
    """Return the Transition rule if valid, else None."""
    return _TRANSITION_MAP.get((from_stage, to_stage))


def allowed_next_stages(from_stage: str) -> list[str]:
    """Return all stages reachable from from_stage."""
    return [t.to_stage for t in TRANSITIONS if t.from_stage == from_stage]


def validate_transition(
    from_stage: str,
    to_stage: str,
    has_approved_request: bool = False,
    has_passing_eval: bool = False,
) -> Transition:
    """
    Validate a requested transition.
    Raises TransitionError with a human-readable reason if blocked.
    Returns the Transition rule if all gates pass.
    """
    rule = get_transition(from_stage, to_stage)
    if rule is None:
        valid = allowed_next_stages(from_stage)
        raise TransitionError(
            f"'{from_stage}' → '{to_stage}' is not a valid transition. "
            f"Valid next stages: {valid or ['none (terminal state)']}"
        )
    if rule.requires_approval and not has_approved_request:
        raise TransitionError(
            f"Transition '{from_stage}' → '{to_stage}' requires an approved "
            f"maker-checker request. Submit an approval request first."
        )
    if rule.requires_eval and not has_passing_eval:
        raise TransitionError(
            f"Transition '{from_stage}' → '{to_stage}' requires attached eval "
            f"results with threshold_met=true. Run evals and attach results first."
        )
    return rule
