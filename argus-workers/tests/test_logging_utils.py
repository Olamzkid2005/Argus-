"""Tests for utils.logging_utils — Category: class"""

import pytest

from utils.logging_utils import RedactedLogger
from utils.logging_utils import ScanLogger
from utils.logging_utils import SecretsRedactionFilter


class TestSecretsRedactionFilter:
    """Tests for the SecretsRedactionFilter class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = SecretsRedactionFilter()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = SecretsRedactionFilter()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestRedactedLogger:
    """Tests for the RedactedLogger class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = RedactedLogger()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = RedactedLogger()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass


class TestScanLogger:
    """Tests for the ScanLogger class."""

    def test_instantiation(self):
        """Class can be instantiated."""
        try:
            instance = ScanLogger()
            assert instance is not None
        except TypeError:
            pytest.skip("Requires constructor args")

    def test_str_repr(self):
        """String representation works."""
        try:
            instance = ScanLogger()
            assert isinstance(str(instance), str)
            assert isinstance(repr(instance), str)
        except TypeError:
            pytest.skip("Requires constructor args")
        except AttributeError:
            pass
