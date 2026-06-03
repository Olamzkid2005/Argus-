"""Tests for shutdown_handler.py

Covers:
  - GracefulShutdownHandler init
  - setup (signal handler registration)
  - should_shutdown logic
  - should_force_exit
  - register_task / unregister_task
  - handle_task_failure_on_shutdown
  - restore
  - Convenience functions
"""

from __future__ import annotations

import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from shutdown_handler import (
    GracefulShutdownHandler,
    setup_graceful_shutdown,
    should_force_exit,
    should_graceful_shutdown,
    shutdown_handler,
)


class TestGracefulShutdownHandler:
    """Tests for GracefulShutdownHandler."""

    @pytest.fixture
    def handler(self):
        h = GracefulShutdownHandler()
        h.force_exit_after = 1
        yield h

    def test_init(self, handler):
        assert handler.shutdown_requested is False
        assert handler.active_tasks == set()
        assert handler.force_exit_after == 1

    def test_setup_registers_signal_handlers(self, handler):
        with patch.object(handler, "original_sigterm_handler", None), \
             patch.object(handler, "original_sigint_handler", None):
            handler.setup()
            assert handler.original_sigterm_handler is not None
            assert handler.original_sigint_handler is not None

    def test_handle_shutdown(self, handler):
        handler._handle_shutdown(signal.SIGTERM, None)
        assert handler.shutdown_requested is True
        assert handler.shutdown_deadline is not None

    def test_should_shutdown_not_requested(self, handler):
        assert handler.should_shutdown() is False

    def test_should_shutdown_requested(self, handler):
        handler.shutdown_requested = True
        handler.shutdown_deadline = time.time() + 60
        assert handler.should_shutdown() is True

    def test_should_shutdown_deadline_exceeded(self, handler):
        handler.shutdown_requested = True
        handler.shutdown_deadline = time.time() - 1  # Past deadline
        assert handler.should_shutdown() is True

    def test_shutdown_waits_for_active_tasks(self, handler):
        handler.shutdown_requested = True
        handler.shutdown_deadline = time.time() + 60
        handler.active_tasks.add("task-1")
        # should_shutdown returns True even with active tasks
        # (tasks should check and finish quickly)
        assert handler.should_shutdown() is True

    def test_should_force_exit_no_deadline(self, handler):
        assert handler.should_force_exit() is False

    def test_should_force_exit_past_deadline(self, handler):
        handler.shutdown_deadline = time.time() - 1
        assert handler.should_force_exit() is True

    def test_register_task(self, handler):
        handler.register_task("task-1")
        assert "task-1" in handler.active_tasks

    def test_unregister_task(self, handler):
        handler.register_task("task-1")
        handler.unregister_task("task-1")
        assert "task-1" not in handler.active_tasks

    def test_unregister_nonexistent_task(self, handler):
        handler.unregister_task("nonexistent")  # Should not raise

    def test_restore_signal_handlers(self, handler):
        # Just verify it doesn't crash
        handler.restore()

    def test_handle_task_failure_on_shutdown(self, handler):
        error = ValueError("test error")
        with patch("dead_letter_queue.get_dlq") as mock_get_dlq, \
             patch("error_classifier.classify_error") as mock_classify:
            mock_dlq = MagicMock()
            mock_get_dlq.return_value = mock_dlq
            mock_classify.return_value.category.value = "retryable"

            handler.handle_task_failure_on_shutdown(
                task_id="task-1",
                task_name="test_task",
                args=(),
                kwargs={},
                error=error,
            )
            mock_dlq.enqueue.assert_called_once()

    def test_handle_task_failure_dlq_error(self, handler):
        error = ValueError("test")
        with patch("dead_letter_queue.get_dlq", side_effect=Exception("DLQ down")):
            # Should not raise — gracefully handles DLQ failure
            handler.handle_task_failure_on_shutdown(
                task_id="task-1", task_name="test", args=(), kwargs={}, error=error,
            )


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_setup_graceful_shutdown(self):
        with patch.object(shutdown_handler, "setup") as mock_setup:
            setup_graceful_shutdown()
            mock_setup.assert_called_once()

    def test_should_graceful_shutdown(self):
        shutdown_handler.shutdown_requested = False
        assert should_graceful_shutdown() is False

    def test_should_force_exit_default(self):
        shutdown_handler.shutdown_deadline = None
        assert should_force_exit() is False
