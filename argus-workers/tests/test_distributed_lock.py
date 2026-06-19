"""Tests for distributed_lock.py

Covers:
  - DistributedLock init and worker_id generation
  - acquire / release / extend
  - is_locked / get_lock_holder
  - release_all
  - LockContext context manager
  - Heartbeat loop error handling
  - Stale lock re-acquisition
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from distributed_lock import (
    DistributedLock,
    LockAcquisitionError,
    LockContext,
)


class TestDistributedLock:
    """Tests for DistributedLock."""

    @pytest.fixture
    def mock_redis(self):
        return MagicMock()

    @pytest.fixture
    def lock(self, mock_redis):
        with patch("distributed_lock.redis.Redis.from_url", return_value=mock_redis):
            dl = DistributedLock(
                redis_url="redis://localhost:6379", worker_id="worker-1"
            )
            yield dl

    @pytest.mark.requires_redis
    def test_init_generates_worker_id(self):
        with patch("distributed_lock.redis.Redis.from_url"):
            dl = DistributedLock(redis_url="redis://localhost:6379")
            assert dl.worker_id is not None
            assert dl.held_locks == {}

    @pytest.mark.requires_redis
    def test_init_with_worker_id(self):
        with patch("distributed_lock.redis.Redis.from_url"):
            dl = DistributedLock(redis_url="redis://localhost:6379", worker_id="custom")
            assert dl.worker_id == "custom"

    @pytest.mark.requires_redis
    def test_acquire_success(self, lock, mock_redis):
        mock_redis.set.return_value = True
        result = lock.acquire("eng-001")
        assert result is True
        assert "eng-001" in lock.held_locks
        mock_redis.set.assert_called_once()

    @pytest.mark.requires_redis
    def test_acquire_already_held(self, lock, mock_redis):
        mock_redis.set.return_value = False  # NX fails
        mock_redis.get.return_value = b"other-worker"
        result = lock.acquire("eng-001")
        assert result is False

    @pytest.mark.requires_redis
    def test_acquire_already_held_by_us(self, lock, mock_redis):
        mock_redis.set.return_value = False
        mock_redis.get.return_value = b"worker-1"
        result = lock.acquire("eng-001")
        assert result is True
        mock_redis.set.assert_called()

    @pytest.mark.requires_redis
    def test_acquire_stale_lock(self, lock, mock_redis):
        """Lock key expired between check and get — retry."""
        mock_redis.set.side_effect = [False, True]  # First fails, second succeeds
        mock_redis.get.return_value = None  # Key disappeared (expired)
        result = lock.acquire("eng-001")
        assert result is True
        assert mock_redis.set.call_count == 2

    @pytest.mark.requires_redis
    def test_release_success(self, lock, mock_redis):
        mock_redis.eval.return_value = 1
        lock.held_locks["eng-001"] = {"key": "engagement_lock:eng-001"}
        result = lock.release("eng-001")
        assert result is True
        assert "eng-001" not in lock.held_locks

    @pytest.mark.requires_redis
    def test_release_not_held_by_us(self, lock, mock_redis):
        mock_redis.eval.return_value = 0
        result = lock.release("eng-001")
        assert result is False

    @pytest.mark.requires_redis
    def test_extend_success(self, lock, mock_redis):
        mock_redis.set.return_value = True
        lock.held_locks["eng-001"] = {"key": "engagement_lock:eng-001"}
        result = lock.extend("eng-001")
        assert result is True

    @pytest.mark.requires_redis
    def test_extend_failure(self, lock, mock_redis):
        mock_redis.set.return_value = None
        result = lock.extend("eng-001")
        assert result is False

    @pytest.mark.requires_redis
    def test_is_locked(self, lock, mock_redis):
        mock_redis.exists.return_value = 1
        assert lock.is_locked("eng-001") is True
        mock_redis.exists.assert_called_once()

    @pytest.mark.requires_redis
    def test_is_not_locked(self, lock, mock_redis):
        mock_redis.exists.return_value = 0
        assert lock.is_locked("eng-001") is False

    @pytest.mark.requires_redis
    def test_get_lock_holder(self, lock, mock_redis):
        mock_redis.get.return_value = b"worker-1"
        assert lock.get_lock_holder("eng-001") == "worker-1"

    @pytest.mark.requires_redis
    def test_get_lock_holder_none(self, lock, mock_redis):
        mock_redis.get.return_value = None
        assert lock.get_lock_holder("eng-001") is None

    @pytest.mark.requires_redis
    def test_release_all(self, lock, mock_redis):
        mock_redis.eval.return_value = 1
        lock.held_locks["eng-001"] = {"key": "key1"}
        lock.held_locks["eng-002"] = {"key": "key2"}
        lock.release_all()
        assert lock.held_locks == {}

    @pytest.mark.requires_redis
    def test_heartbeat_loop_stops_on_callback(self, lock, mock_redis):
        mock_redis.set.return_value = True
        stop = iter([False, False, True])  # After 2 heartbeats, stop

        def stop_callback():
            return next(stop)

        lock.heartbeat_loop("eng-001", stop_callback, interval_seconds=0.01)
        assert mock_redis.set.called


class TestLockContext:
    """Tests for LockContext context manager."""

    def test_enter_acquires_lock(self):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        ctx = LockContext(mock_lock, "eng-001")
        with ctx as c:
            assert c.acquired is True
        mock_lock.release.assert_called_once()

    def test_enter_raises_on_failure(self):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False
        mock_lock.get_lock_holder.return_value = "other-worker"
        ctx = LockContext(mock_lock, "eng-001")
        with pytest.raises(LockAcquisitionError):
            with ctx:
                pass

    def test_release_on_exception(self):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        ctx = LockContext(mock_lock, "eng-001")
        with pytest.raises(ValueError):
            with ctx:
                raise ValueError("test")
        mock_lock.release.assert_called_once()
