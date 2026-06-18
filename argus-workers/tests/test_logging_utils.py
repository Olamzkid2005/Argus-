"""Tests for utils.logging_utils — Category: class"""

import pytest

from utils.logging_utils import RedactedLogger, ScanLogger, SecretsRedactionFilter


class TestSecretsRedactionFilter:
    """Tests for the SecretsRedactionFilter class."""

    def test_instantiation(self):
        """Default instantiation succeeds."""
        instance = SecretsRedactionFilter()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = SecretsRedactionFilter()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestRedactedLogger:
    """Tests for the RedactedLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            RedactedLogger()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            RedactedLogger()


class TestScanLogger:
    """Tests for the ScanLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        with pytest.raises(TypeError):
            ScanLogger()

    def test_str_repr(self):
        """String representation not available (requires constructor args)."""
        with pytest.raises(TypeError):
            ScanLogger()
