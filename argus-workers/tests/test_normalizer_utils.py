"""Tests for orchestrator_pkg.normalizer_utils — Category: function"""

import pytest

from orchestrator_pkg.normalizer_utils import normalize_finding


class TestNormalizeFinding:
    """Tests for the normalize_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            normalize_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        pytest.skip("Requires arguments")  # Skip if args needed
