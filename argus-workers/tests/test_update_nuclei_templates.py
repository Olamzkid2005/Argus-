"""Tests for tools.update_nuclei_templates — Category: function"""

import pytest

from tools.update_nuclei_templates import get_template_count, update_nuclei_templates


class TestUpdateNucleiTemplates:
    """Tests for the update_nuclei_templates function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = update_nuclei_templates()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            update_nuclei_templates()


class TestGetTemplateCount:
    """Tests for the get_template_count function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = update_nuclei_templates()
        assert instance is not None

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_template_count()
