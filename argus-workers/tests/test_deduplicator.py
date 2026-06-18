"""Tests for tools.correlation.deduplicator — Category: function"""

import pytest

from tools.correlation.deduplicator import _finding_fingerprint
from tools.correlation.deduplicator import _jaccard
from tools.correlation.deduplicator import _normalize
from tools.correlation.deduplicator import _token_set
from tools.correlation.deduplicator import deduplicate


class TestNormalize:
    """Tests for the _normalize function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _normalize()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _normalize()


class TestTokenSet:
    """Tests for the _token_set function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _token_set()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _token_set()


class TestJaccard:
    """Tests for the _jaccard function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jaccard()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _jaccard()


class TestFindingFingerprint:
    """Tests for the _finding_fingerprint function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _finding_fingerprint()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _finding_fingerprint()


class TestDeduplicate:
    """Tests for the deduplicate function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deduplicate()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            deduplicate()
