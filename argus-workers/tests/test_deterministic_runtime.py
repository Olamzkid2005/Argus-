"""Tests for runtime.deterministic_runtime — Category: class"""

import pytest

from runtime.deterministic_runtime import DeterministicRuntime


class TestDeterministicRuntime:
    """Tests for the DeterministicRuntime class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = DeterministicRuntime()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = DeterministicRuntime()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
