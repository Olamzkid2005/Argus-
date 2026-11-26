"""Stage 5 rollout gate evaluator tests (plan §Stage 5).

Pure unit tests — no database, no workers. The evaluator must fail closed:
anything unmeasurable is INSUFFICIENT DATA, a measured breach is NO-GO, and
only a fully passing cohort is GO.
"""

from __future__ import annotations

from control_plane.rollout_metrics import evaluate_rollout_snapshot


def _healthy() -> dict:
    return {
        "engagements_observed": 4,
        "stalled_engagements": 0,
        "duplicate_intents": 0,
        "intents_proposed": 38,
        "refinements_total": 9,
        "tasks_finished": 4,
        "claim_losses": 0,
        "verified_findings": 11,
        "total_findings": 17,
        "anchors_covered": 41,
        "anchors_in_scope": 48,
        "cost_usd": 12.40,
        "cost_budget_usd": 50.0,
        "partial_runs": 0,
        "recovery_attempts": 2,
        "recoveries_intact": 2,
    }


def test_healthy_cohort_is_go():
    result = evaluate_rollout_snapshot(_healthy())
    assert result["verdict"] == "GO"
    assert result["breaches"] == []


def test_stall_breach_is_no_go_with_named_row():
    snap = _healthy()
    snap["stalled_engagements"] = 1  # 0.75 < 0.95
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "NO-GO"
    assert any("no_stall_rate" in b for b in result["breaches"])


def test_any_duplicate_intent_is_no_go():
    snap = _healthy()
    snap["duplicate_intents"] = 1
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "NO-GO"
    assert any("duplicate_intent_rate" in b for b in result["breaches"])


def test_raw_finding_count_cannot_rescue_a_breach():
    # Huge raw count but a poor verified ratio must still fail.
    snap = _healthy()
    snap["verified_findings"] = 10
    snap["total_findings"] = 1000
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "NO-GO"
    assert any("verified_finding_ratio" in b for b in result["breaches"])


def test_too_few_engagements_is_insufficient_not_go():
    snap = _healthy()
    snap["engagements_observed"] = 2
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "INSUFFICIENT DATA"


def test_missing_field_is_insufficient():
    snap = _healthy()
    del snap["cost_budget_usd"]
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "INSUFFICIENT DATA"


def test_negative_input_is_insufficient():
    snap = _healthy()
    snap["partial_runs"] = -1
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "INSUFFICIENT DATA"


def test_zero_recovery_attempts_is_insufficient():
    snap = _healthy()
    snap["recovery_attempts"] = 0
    snap["recoveries_intact"] = 0
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "INSUFFICIENT DATA"


def test_impossible_counts_are_insufficient():
    snap = _healthy()
    snap["verified_findings"] = 18  # exceeds total_findings=17
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "INSUFFICIENT DATA"


def test_cost_over_budget_is_no_go():
    snap = _healthy()
    snap["cost_usd"] = 61.0
    result = evaluate_rollout_snapshot(snap)
    assert result["verdict"] == "NO-GO"
    assert any("cost_usd" in b for b in result["breaches"])


def test_custom_thresholds_apply():
    snap = _healthy()
    snap["anchors_covered"] = 40  # 0.833 passes default 0.80
    result = evaluate_rollout_snapshot(snap, {"coverage": 0.90})
    assert result["verdict"] == "NO-GO"
    assert any("coverage" in b for b in result["breaches"])
