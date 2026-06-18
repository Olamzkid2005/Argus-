"""Tests for tasks.self_scan — Category: function"""


from tasks.self_scan import run_self_scan


class TestRunSelfScan:
    """Tests for the run_self_scan function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = run_self_scan()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function executes successfully."""
        instance = run_self_scan()
        assert isinstance(instance, dict)
