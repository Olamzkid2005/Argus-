"""Tests for tools.port_scanner — Category: dataclass"""

import pytest

from tools.port_scanner import OpenPort, PortScanner


class TestOpenPort:
    """Tests for the OpenPort class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            OpenPort()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            OpenPort()


class TestPortScanner:
    """Tests for the PortScanner class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = PortScanner()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = PortScanner()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
