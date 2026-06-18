"""Tests for runtime.deterministic_runtime — Category: class"""

import pytest

from runtime.deterministic_runtime import DeterministicRuntime


class TestDeterministicRuntime:
    """Tests for the DeterministicRuntime class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            DeterministicRuntime()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            DeterministicRuntime()
