"""Tests for runtime.event_stream — Category: class"""

import pytest

from runtime.event_stream import SafeEventEmitter


class TestSafeEventEmitter:
    """Tests for the SafeEventEmitter class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            SafeEventEmitter()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            SafeEventEmitter()
            str(SafeEventEmitter())
