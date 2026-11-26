"""Stage 5 rollout gate evaluator (plan §Stage 5, ``stage5-rollout-plan.md``).

Pure stdlib: counts in, verdict out. The operator collects a snapshot dict from
the source tables named in the rollout plan and this module decides GO /
NO-GO / INSUFFICIENT DATA against pre-rollout thresholds. It never touches the
database and never dispatches work, so running it cannot mutate a rollout.

Fail-closed rules: anything unmeasurable (missing fields, non-numeric or
negative inputs, too few engagements, zero recovery attempts) yields
INSUFFICIENT DATA, never GO. A measured breach yields NO-GO with the breaching
rows listed. Raw finding count is recorded for context only and cannot flip a
verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Snapshot fields the evaluator reads. All counts must be integers >= 0,
#: except cost_usd / cost_budget_usd which are floats >= 0.
REQUIRED_FIELDS = (
    "engagements_observed",
    "stalled_engagements",
    "duplicate_intents",
    "intents_proposed",
    "refinements_total",
    "tasks_finished",
    "claim_losses",
    "verified_findings",
    "total_findings",
    "anchors_covered",
    "anchors_in_scope",
    "cost_usd",
    "cost_budget_usd",
    "partial_runs",
    "recovery_attempts",
    "recoveries_intact",
)

DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_engagements": 3,
    "no_stall_rate": 0.95,
    "duplicate_intent_rate": 0.0,
    "max_refinements_per_task": 3.0,
    "max_claim_losses": 0,
    "verified_finding_ratio": 0.50,
    "coverage": 0.80,
    "max_partial_run_rate": 0.10,
    "recovery_rate": 0.90,
}

VERDICT_GO = "GO"
VERDICT_NO_GO = "NO-GO"
VERDICT_INSUFFICIENT = "INSUFFICIENT DATA"


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "verdict": VERDICT_INSUFFICIENT,
        "metrics": {},
        "breaches": [],
        "notes": [reason],
    }


def evaluate_rollout_snapshot(
    snapshot: Mapping[str, Any],
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate one cohort snapshot against Stage 5 thresholds."""
    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)

    values: dict[str, float] = {}
    for field in REQUIRED_FIELDS:
        if field not in snapshot:
            return _invalid(f"missing snapshot field: {field}")
        value = snapshot[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _invalid(f"snapshot field {field!r} is not numeric")
        if value < 0:
            return _invalid(f"snapshot field {field!r} is negative")
        values[field] = float(value)

    notes: list[str] = []
    for int_field in (
        "engagements_observed",
        "stalled_engagements",
        "duplicate_intents",
        "intents_proposed",
        "refinements_total",
        "tasks_finished",
        "claim_losses",
        "verified_findings",
        "total_findings",
        "anchors_covered",
        "anchors_in_scope",
        "partial_runs",
        "recovery_attempts",
        "recoveries_intact",
    ):
        if not float(snapshot[int_field]).is_integer():
            return _invalid(f"snapshot field {int_field!r} must be a whole count")

    observed = int(values["engagements_observed"])
    if observed < int(limits["min_engagements"]):
        return _invalid(
            f"only {observed} engagement(s) observed; "
            f"need >= {int(limits['min_engagements'])}"
        )

    # Guard every denominator before any rate is computed.
    if values["tasks_finished"] == 0:
        return _invalid("no finished tasks; refinement mean is undefined")
    if values["total_findings"] == 0:
        return _invalid("no findings; verified-finding ratio is undefined")
    if values["anchors_in_scope"] == 0:
        return _invalid("no in-scope anchors; coverage is undefined")
    if values["recovery_attempts"] == 0:
        return _invalid("zero recovery attempts; recovery rate is vacuous")
    if values["recoveries_intact"] > values["recovery_attempts"]:
        return _invalid("recoveries_intact exceeds recovery_attempts")
    if values["verified_findings"] > values["total_findings"]:
        return _invalid("verified_findings exceeds total_findings")
    if values["anchors_covered"] > values["anchors_in_scope"]:
        return _invalid("anchors_covered exceeds anchors_in_scope")
    if values["stalled_engagements"] > observed:
        return _invalid("stalled_engagements exceeds engagements_observed")
    if values["partial_runs"] > observed:
        return _invalid("partial_runs exceeds engagements_observed")
    if values["cost_budget_usd"] == 0:
        notes.append("no per-engagement budget set; cost check skipped")
    if values["intents_proposed"] == 0 and values["duplicate_intents"] > 0:
        pass  # handled below as a breach, not a divide-by-zero

    proposed = values["intents_proposed"]
    metrics = {
        "no_stall_rate": (observed - values["stalled_engagements"]) / observed,
        "duplicate_intent_rate": (values["duplicate_intents"] / proposed)
        if proposed
        else 0.0,
        "refinements_per_task": values["refinements_total"]
        / values["tasks_finished"],
        "claim_losses": values["claim_losses"],
        "verified_finding_ratio": values["verified_findings"]
        / values["total_findings"],
        "coverage": values["anchors_covered"] / values["anchors_in_scope"],
        "cost_usd": values["cost_usd"],
        "cost_budget_usd": values["cost_budget_usd"],
        "partial_run_rate": values["partial_runs"] / observed,
        "recovery_rate": values["recoveries_intact"]
        / values["recovery_attempts"],
        # Context only: deliberately excluded from the gate decision.
        "total_findings": values["total_findings"],
    }

    breaches: list[str] = []
    if metrics["no_stall_rate"] < limits["no_stall_rate"]:
        breaches.append(
            f"no_stall_rate {metrics['no_stall_rate']:.3f} "
            f"< {limits['no_stall_rate']}"
        )
    if metrics["duplicate_intent_rate"] > limits["duplicate_intent_rate"]:
        breaches.append(
            f"duplicate_intent_rate {metrics['duplicate_intent_rate']:.3f} "
            f"> {limits['duplicate_intent_rate']}"
        )
    if metrics["refinements_per_task"] > limits["max_refinements_per_task"]:
        breaches.append(
            f"refinements_per_task {metrics['refinements_per_task']:.3f} "
            f"> {limits['max_refinements_per_task']}"
        )
    if metrics["claim_losses"] > limits["max_claim_losses"]:
        breaches.append(f"claim_losses {metrics['claim_losses']:.0f} > 0")
    if metrics["verified_finding_ratio"] < limits["verified_finding_ratio"]:
        breaches.append(
            f"verified_finding_ratio {metrics['verified_finding_ratio']:.3f} "
            f"< {limits['verified_finding_ratio']}"
        )
    if metrics["coverage"] < limits["coverage"]:
        breaches.append(
            f"coverage {metrics['coverage']:.3f} < {limits['coverage']}"
        )
    if values["cost_budget_usd"] > 0 and (
        metrics["cost_usd"] > values["cost_budget_usd"]
    ):
        breaches.append(
            f"cost_usd {metrics['cost_usd']:.2f} "
            f"> budget {values['cost_budget_usd']:.2f}"
        )
    if metrics["partial_run_rate"] > limits["max_partial_run_rate"]:
        breaches.append(
            f"partial_run_rate {metrics['partial_run_rate']:.3f} "
            f"> {limits['max_partial_run_rate']}"
        )
    if metrics["recovery_rate"] < limits["recovery_rate"]:
        breaches.append(
            f"recovery_rate {metrics['recovery_rate']:.3f} "
            f"< {limits['recovery_rate']}"
        )

    if breaches:
        return {
            "verdict": VERDICT_NO_GO,
            "metrics": metrics,
            "breaches": breaches,
            "notes": notes,
        }
    return {
        "verdict": VERDICT_GO,
        "metrics": metrics,
        "breaches": [],
        "notes": notes,
    }
