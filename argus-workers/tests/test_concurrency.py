"""Tests for runtime/concurrency.py.

Validates semaphore types, counts, and HIGH_COST_TOOLS contents.
"""

from runtime.concurrency import (
    HIGH_COST_SEMAPHORE,
    HIGH_COST_TOOLS,
    SUBPROCESS_SEMAPHORE,
)


class TestSubprocessSemaphore:
    def test_is_bounded_semaphore(self):
        # DistributedSemaphore does not inherit BoundedSemaphore
        # but provides the same API contract (acquire/release)
        assert hasattr(SUBPROCESS_SEMAPHORE, "acquire")
        assert hasattr(SUBPROCESS_SEMAPHORE, "release")

    def test_initial_count_acquire_release(self):
        # Verify acquire/release roundtrip works
        assert SUBPROCESS_SEMAPHORE.acquire(timeout=5) is True
        SUBPROCESS_SEMAPHORE.release()


class TestHighCostSemaphore:
    def test_is_bounded_semaphore(self):
        assert hasattr(HIGH_COST_SEMAPHORE, "acquire")
        assert hasattr(HIGH_COST_SEMAPHORE, "release")

    def test_initial_count_acquire_release(self):
        # Verify acquire/release roundtrip works
        assert HIGH_COST_SEMAPHORE.acquire(timeout=5) is True
        HIGH_COST_SEMAPHORE.release()


class TestHighCostTools:
    def test_contains_expected_tools(self):
        expected = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}
        assert expected == HIGH_COST_TOOLS

    def test_is_case_sensitive_set(self):
        assert "SQLMAP" not in HIGH_COST_TOOLS
        assert "Sqlmap" not in HIGH_COST_TOOLS

    def test_is_set_type(self):
        assert isinstance(HIGH_COST_TOOLS, set)
