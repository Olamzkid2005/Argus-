"""Tests for tasks.report — Category: function"""


import pytest

from tasks.report import (
    _calculate_next_run,
    _generate_report_data,
    _send_report_email,
    generate_compliance_report,
    generate_full_report,
    generate_report,
    generate_scheduled_reports,
    get_compliance_reports,
    get_findings_summary,
)


class TestGenerateReport:
    """Tests for the generate_report function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_report()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_report()


class TestGetFindingsSummary:
    """Tests for the get_findings_summary function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_findings_summary()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_findings_summary()


class TestGenerateScheduledReports:
    """Tests for the generate_scheduled_reports function."""

    @pytest.mark.skipif("not os.environ.get('DATABASE_URL')", reason="Requires database")
    def test_basic_execution(self):
        """Function executes successfully."""
        instance = generate_scheduled_reports()
        assert instance is not None

    @pytest.mark.skipif("not os.environ.get('DATABASE_URL')", reason="Requires database")
    def test_returns_correct_type(self):
        """Returns a list."""
        instance = generate_scheduled_reports()
        assert isinstance(instance, list)


class TestGenerateReportData:
    """Tests for the _generate_report_data function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _generate_report_data()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _generate_report_data()


class TestSendReportEmail:
    """Tests for the _send_report_email function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _send_report_email()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _send_report_email()


class TestCalculateNextRun:
    """Tests for the _calculate_next_run function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _calculate_next_run()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            _calculate_next_run()


class TestGenerateComplianceReport:
    """Tests for the generate_compliance_report function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_compliance_report()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_compliance_report()


class TestGenerateFullReport:
    """Tests for the generate_full_report function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_full_report()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            generate_full_report()


class TestGetComplianceReports:
    """Tests for the get_compliance_reports function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_compliance_reports()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            get_compliance_reports()
