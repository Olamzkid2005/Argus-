"""Tests for runtime/concurrency.py.

Validates semaphore types, counts, and HIGH_COST_TOOLS contents.
"""

import threading

import pytest

from config.constants import MAX_CONCURRENT_REQUESTS
from runtime.concurrency import (
    HIGH_COST_SEMAPHORE,
    HIGH_COST_TOOLS,
    SUBPROCESS_SEMAPHORE,
)


class TestSubprocessSemaphore:
    def test_is_bounded_semaphore(self):
        assert isinstance(SUBPROCESS_SEMAPHORE, threading.BoundedSemaphore)

    def test_initial_count_matches_max_concurrent(self):
        acquire_count = 0
        while SUBPROCESS_SEMAPHORE.acquire(blocking=False):
            acquire_count += 1
        assert acquire_count == MAX_CONCURRENT_REQUESTS
        # Release what we acquired so subsequent tests are unaffected
        for _ in range(acquire_count):
            SUBPROCESS_SEMAPHORE.release()

    def test_cannot_release_beyond_initial_count(self):
        with pytest.raises(ValueError, match="Semaphore released too many times"):
            SUBPROCESS_SEMAPHORE.release()


class TestHighCostSemaphore:
    def test_is_bounded_semaphore(self):
        assert isinstance(HIGH_COST_SEMAPHORE, threading.BoundedSemaphore)

    def test_initial_count_is_max_concurrent_divided_by_three(self):
        expected = max(1, MAX_CONCURRENT_REQUESTS // 3)
        acquire_count = 0
        while HIGH_COST_SEMAPHORE.acquire(blocking=False):
            acquire_count += 1
        assert acquire_count == expected
        for _ in range(acquire_count):
            HIGH_COST_SEMAPHORE.release()


class TestHighCostTools:
    def test_contains_expected_tools(self):
        expected = {"sqlmap", "dalfox", "commix", "nuclei", "masscan", "sn1per"}
        assert HIGH_COST_TOOLS == expected

    def test_is_case_sensitive_set(self):
        assert "SQLMAP" not in HIGH_COST_TOOLS
        assert "Sqlmap" not in HIGH_COST_TOOLS

    def test_is_set_type(self):
        assert isinstance(HIGH_COST_TOOLS, set)
