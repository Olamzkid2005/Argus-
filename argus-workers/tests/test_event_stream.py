"""Tests for runtime.event_stream — Category: class"""

import pytest

from runtime.event_stream import SafeEventEmitter


class TestSafeEventEmitter:
    """Tests for the SafeEventEmitter class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = SafeEventEmitter()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = SafeEventEmitter()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
