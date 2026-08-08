"""Tests for tools.port_scanner — Category: dataclass"""

from tools.port_scanner import OpenPort, PortScanner


class TestOpenPort:
    """Tests for the OpenPort factory function."""

    def test_instantiation(self):
        """OpenPort() is a dict factory with safe defaults (legacy alias)."""
        p = OpenPort()
        assert isinstance(p, dict)
        assert p["port"] == 0
        assert p["protocol"] == "tcp"
        assert p["state"] == "open"

    def test_str_repr(self):
        """OpenPort result is str-able and repr-able."""
        p = OpenPort(80, "tcp", "http", "1.1", "open")
        assert isinstance(str(p), str)
        assert isinstance(repr(p), str)
        assert p["port"] == 80


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
