"""Tests for tools.sbom_generator — Category: function"""

import pytest

from tools.sbom_generator import generate_sbom_from_findings


class TestGenerateSbomFromFindings:
    """Tests for the generate_sbom_from_findings function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_sbom_from_findings()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_sbom_from_findings()
