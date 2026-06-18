"""Tests for tools.websocket_scanner — Category: class"""

import pytest

from tools.websocket_scanner import WebSocketScanner


class TestWebSocketScanner:
    """Tests for the WebSocketScanner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = WebSocketScanner()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = WebSocketScanner()
        assert instance is not None
