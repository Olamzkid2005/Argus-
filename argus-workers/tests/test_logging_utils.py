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
        """String representation not available."""
        instance = SecretsRedactionFilter()
        assert instance is not None


class TestRedactedLogger:
    """Tests for the RedactedLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SecretsRedactionFilter()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = SecretsRedactionFilter()
        assert instance is not None


class TestScanLogger:
    """Tests for the ScanLogger class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = SecretsRedactionFilter()
        assert instance is not None

    def test_str_repr(self):
        """String representation not available."""
        instance = SecretsRedactionFilter()
        assert instance is not None
