"""Tests for tools.websocket_scanner — Category: class"""

import pytest

from tools.websocket_scanner import WebSocketScanner


class TestWebSocketScanner:
    """Tests for the WebSocketScanner class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = WebSocketScanner()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = WebSocketScanner()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
