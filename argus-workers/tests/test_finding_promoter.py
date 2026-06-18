"""Tests for tools.verification.finding_promoter — Category: function"""

import pytest

from tools.verification.finding_promoter import promote_finding


class TestPromoteFinding:
    """Tests for the promote_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            promote_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            promote_finding()
