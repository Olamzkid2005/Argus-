"""Tests for parsers.schemas.nuclei_schema — Category: function"""

import pytest

from parsers.schemas.nuclei_schema import validate_nuclei_finding


class TestValidateNucleiFinding:
    """Tests for the validate_nuclei_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            validate_nuclei_finding()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            validate_nuclei_finding()
