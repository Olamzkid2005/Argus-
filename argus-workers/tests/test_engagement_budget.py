"""Tests for the cumulative engagement budget ledger (Stage 6.1)."""

from datetime import UTC, datetime, timedelta

import pytest

from runtime.engagement_budget import (
    STOP_BUDGET,
    STOP_CANCELLED,
    STOP_DEADLINE,
    BudgetUsage,
    EngagementBudgetLedger,
    InMemoryBudgetLedgerStore,
    classify_llm_failure,
)


def iso_in(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


class TestUsageAccounting:
    def test_successful_call_records_tokens_and_cost(self):
        ledger = EngagementBudgetLedger("eng-1", store=InMemoryBudgetLedgerStore())
        ledger.record_llm_call(input_tokens=120, output_tokens=30, cost_usd=0.02)
        usage = ledger.usage
        assert usage.llm_calls == 1
        assert usage.input_tokens == 120
        assert usage.output_tokens == 30
        assert usage.cost_usd == pytest.approx(0.02)
        assert usage.cost_known is True
        assert usage.llm_failures == 0

    def test_failed_fallback_and_malformed_calls_are_counted(self):
        ledger = EngagementBudgetLedger("eng-1")
        ledger.record_llm_call(success=False, reason="provider timeout")
        ledger.record_llm_call(
            success=False, fallback=True, reason="JSON parse error: no object"
        )
        ledger.record_llm_call(
            success=False, fallback=True, reason="Cost cap exceeded"
        )
        usage = ledger.usage
        assert usage.llm_calls == 3
        assert usage.llm_failures == 3
        assert usage.llm_fallbacks == 2
        assert usage.llm_malformed == 1

    def test_unpriced_call_is_explicit_unknown_cost(self):
        ledger = EngagementBudgetLedger("eng-1", max_cost_usd=0.0)
        ledger.record_llm_call(cost_usd=None)
        assert ledger.usage.cost_known is False
        # An unknown cost must not be treated as zero and allow a hard stop to
        # be bypassed silently; the caller can see cost_known=False.
        assert ledger.status()["cost_known"] is False

    def test_tool_calls_and_llm_requests_are_counted(self):
        ledger = EngagementBudgetLedger("eng-1")
        ledger.record_tool_call()
        ledger.record_tool_call()
        assert ledger.usage.tool_calls == 2
        ledger.record_llm_call(cost_usd=0.01)
        assert ledger.usage.request_count == 1

    def test_classify_failure_distinguishes_malformed_from_failure(self):
        assert classify_llm_failure("JSON parse error: no object") == "malformed"
        assert classify_llm_failure("connection reset") == "failure"


class TestDeadline:
    def test_remaining_seconds_tracks_the_deadline(self):
        ledger = EngagementBudgetLedger("eng-1", deadline_at=iso_in(60))
        assert 55 <= ledger.remaining_seconds() <= 60
        assert ledger.stop_reason() is None

    def test_past_deadline_stops_the_run(self):
        ledger = EngagementBudgetLedger(
            "eng-1", deadline_at=iso_in(-1)
        )
        assert ledger.stop_reason() == STOP_DEADLINE

    def test_timeout_is_bounded_by_remaining_time(self):
        ledger = EngagementBudgetLedger("eng-1", deadline_at=iso_in(5))
        assert ledger.bounded_timeout(300) <= 5
        assert ledger.bounded_timeout(1) == pytest.approx(1, abs=0.01)

    def test_no_deadline_means_no_time_bound(self):
        ledger = EngagementBudgetLedger("eng-1")
        assert ledger.remaining_seconds() is None
        assert ledger.bounded_timeout(300) == 300

    def test_cancelled_preempts_every_other_reason(self):
        ledger = EngagementBudgetLedger("eng-1", deadline_at=iso_in(-1))
        assert ledger.stop_reason(cancelled=True) == STOP_CANCELLED


class TestBudgetLimits:
    def test_tool_call_limit_stops_the_run(self):
        ledger = EngagementBudgetLedger("eng-1", max_tool_calls=1)
        ledger.record_tool_call()
        assert ledger.stop_reason() == STOP_BUDGET

    def test_llm_call_limit_stops_the_run(self):
        ledger = EngagementBudgetLedger("eng-1", max_llm_calls=1)
        ledger.record_llm_call(cost_usd=0.0)
        assert ledger.stop_reason() == STOP_BUDGET

    def test_cost_limit_stops_the_run(self):
        ledger = EngagementBudgetLedger("eng-1", max_cost_usd=0.05)
        ledger.record_llm_call(cost_usd=0.06)
        assert ledger.stop_reason() == STOP_BUDGET


class TestPersistence:
    def test_usage_round_trips_through_the_store(self):
        store = InMemoryBudgetLedgerStore()
        ledger = EngagementBudgetLedger(
            "eng-1",
            deadline_at=iso_in(120),
            store=store,
            max_cost_usd=1.0,
        )
        ledger.record_llm_call(input_tokens=10, output_tokens=5, cost_usd=0.01)
        ledger.record_tool_call()

        resumed = EngagementBudgetLedger("eng-1", store=store, max_cost_usd=1.0)
        assert resumed.usage.llm_calls == 1
        assert resumed.usage.tool_calls == 1
        assert resumed.usage.input_tokens == 10
        assert resumed.usage.cost_usd == pytest.approx(0.01)
        # The original deadline is preserved, not reset by the resume.
        assert resumed.usage.deadline_at == ledger.usage.deadline_at

    def test_resumed_usage_keeps_accumulating(self):
        store = InMemoryBudgetLedgerStore()
        first = EngagementBudgetLedger("eng-1", store=store)
        first.record_llm_call(cost_usd=0.02)
        resumed = EngagementBudgetLedger("eng-1", store=store)
        resumed.record_llm_call(cost_usd=0.03)
        assert resumed.usage.llm_calls == 2
        assert resumed.usage.cost_usd == pytest.approx(0.05)

    def test_usage_from_dict_ignores_missing_engagement_id(self):
        assert BudgetUsage.from_dict({"llm_calls": 3}) is None
        assert BudgetUsage.from_dict(None) is None

    def test_status_includes_deadline_remaining_and_stop_reason(self):
        ledger = EngagementBudgetLedger("eng-1", deadline_at=iso_in(30))
        status = ledger.status()
        assert status["engagement_id"] == "eng-1"
        assert status["remaining_seconds"] is not None
        assert status["stop_reason"] is None
