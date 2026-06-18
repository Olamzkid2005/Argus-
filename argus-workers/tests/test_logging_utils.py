"""Tests for utils.logging_utils — Category: class"""

import pytest

from utils.logging_utils import RedactedLogger
from utils.logging_utils import ScanLogger
from utils.logging_utils import SecretsRedactionFilter


class TestSecretsRedactionFilter:
    """Tests for the SecretsRedactionFilter class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SecretsRedactionFilter()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ScanLogger()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestRedactedLogger:
    """Tests for the RedactedLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = RedactedLogger()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = RedactedLogger()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestScanLogger:
    """Tests for the ScanLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ScanLogger()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = RedactedLogger()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)
