"""Tests for runtime.execution_engine — Category: class"""

import pytest

from runtime.execution_engine import ExecutionEngine


class TestExecutionEngine:
    """Tests for the ExecutionEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ExecutionEngine()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            ExecutionEngine()
