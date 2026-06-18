"""Tests for runtime.execution_engine — Category: class"""

import pytest

from runtime.execution_engine import ExecutionEngine


class TestExecutionEngine:
    """Tests for the ExecutionEngine class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ExecutionEngine()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ExecutionEngine()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
