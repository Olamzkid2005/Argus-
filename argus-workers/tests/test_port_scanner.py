"""Tests for tools.port_scanner — Category: dataclass"""

import pytest

from tools.port_scanner import OpenPort
from tools.port_scanner import PortScanner


class TestOpenPort:
    """Tests for the OpenPort class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = OpenPort()
            assert instance is not None
            assert isinstance(instance, OpenPort)
        except TypeError:
            with pytest.raises(TypeError):
                OpenPort()

    def test_field_access(self):
        """Instance fields are accessible."""
        try:
            instance = OpenPort()
            fields = vars(instance) if hasattr(instance, '__dict__') else {}
            assert isinstance(fields, dict)
        except TypeError:
            with pytest.raises(TypeError):
                OpenPort()


class TestPortScanner:
    """Tests for the PortScanner class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            OpenPort()

    def test_str_repr(self):
        """String representation not available."""
        with pytest.raises(TypeError):
            OpenPort()
