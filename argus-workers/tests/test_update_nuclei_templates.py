"""Tests for tools.update_nuclei_templates — Category: function"""


from tools.update_nuclei_templates import get_template_count, update_nuclei_templates


class TestUpdateNucleiTemplates:
    """Tests for the update_nuclei_templates function."""

    def test_basic_execution(self):
        """Function executes successfully."""
        instance = update_nuclei_templates()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a boolean."""
        instance = update_nuclei_templates()
        assert isinstance(instance, bool)


class TestGetTemplateCount:
    """Tests for the get_template_count function."""

    def test_basic_execution(self):
        """Function executes successfully."""
        instance = get_template_count()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns an integer."""
        instance = get_template_count()
        assert isinstance(instance, int)
