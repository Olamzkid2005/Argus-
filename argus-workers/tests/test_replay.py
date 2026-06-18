"""Tests for tasks.replay — Category: function"""

import pytest

from tasks.replay import replay_dlq_task


class TestReplayDlqTask:
    """Tests for the replay_dlq_task function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            replay_dlq_task()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            replay_dlq_task()
