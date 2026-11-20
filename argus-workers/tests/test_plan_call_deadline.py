"""Tests for the bounded planning call in mcp_server.

An unreachable LLM provider used to make one planning call retry for ten
minutes (three 180s attempts plus backoff), which the driver saw as an
`agent_init` RPC timeout and killed the whole phase with it.
"""

import time

import pytest

import mcp_server
from mcp_server import _call_with_deadline, _PlannerCallTimeout


class TestCallWithDeadline:
    def test_returns_the_value_when_fast_enough(self):
        assert _call_with_deadline(lambda: 42, timeout=5) == 42

    def test_no_timeout_runs_inline(self):
        assert _call_with_deadline(lambda: "inline", timeout=0) == "inline"
        assert _call_with_deadline(lambda: "inline", timeout=None) == "inline"

    def test_slow_call_is_abandoned_not_awaited(self):
        started = time.monotonic()
        with pytest.raises(_PlannerCallTimeout):
            _call_with_deadline(lambda: time.sleep(5), timeout=0.2, label="plan")
        # It must return control at the deadline, not when the call finishes.
        assert time.monotonic() - started < 2.0

    def test_call_timeout_is_configurable(self):
        assert mcp_server._PLAN_CALL_TIMEOUT_SECONDS > 0
        # It has to be far below the 600s RPC budget the driver allows.
        assert mcp_server._PLAN_CALL_TIMEOUT_SECONDS < 600
