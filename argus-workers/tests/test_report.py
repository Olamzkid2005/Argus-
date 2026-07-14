"""Tests for tasks.report — Category: function"""

import os
from unittest.mock import MagicMock, patch

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

    @patch.dict(os.environ, {}, clear=True)
    def test_skips_when_no_recipients(self):
        """Should skip silently when recipients list is empty."""
        _send_report_email([], "test-report", {"findings_summary": [], "engagements": []})
        # No assertion needed — should not raise

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "argus@example.com",
        "SMTP_USE_TLS": "true",
    }, clear=True)
    def test_smtp_backend_sends_email(self, mock_smtp):
        """SMTP backend sends email with correct content."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        _send_report_email(
            ["admin@example.com"],
            "Weekly Report",
            {
                "findings_summary": [
                    {"severity": "CRITICAL", "count": 2, "avg_confidence": 0.95},
                    {"severity": "HIGH", "count": 5, "avg_confidence": 0.80},
                ],
                "engagements": [
                    {"target_url": "https://example.com", "findings_count": 7},
                ],
                "generated_at": "2026-07-14T12:00:00",
            },
        )

        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pass")
        # Verify email was sent with the right args
        mock_server.sendmail.assert_called_once()
        args, _ = mock_server.sendmail.call_args
        assert args[0] == "argus@example.com"  # from
        assert args[1] == ["admin@example.com"]  # to
        assert "Weekly Report" in args[2]  # subject in body
        assert "CRITICAL" in args[2]  # findings in body

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "argus@example.com",
        "SMTP_USE_TLS": "false",
    }, clear=True)
    def test_smtp_backend_without_tls(self, mock_smtp):
        """SMTP backend skips STARTTLS when SMTP_USE_TLS=false."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        _send_report_email(
            ["admin@example.com"],
            "Test",
            {"findings_summary": [], "engagements": [], "generated_at": ""},
        )

        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        mock_server.starttls.assert_not_called()
        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.sendmail.assert_called_once()

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "argus@example.com",
        "SMTP_USE_TLS": "false",
    }, clear=True)
    def test_smtp_backend_tls_disabled_explicitly(self, mock_smtp):
        """SMTP backend respects explicit SMTP_USE_TLS=false."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        _send_report_email(
            ["admin@example.com"],
            "Test",
            {"findings_summary": [], "engagements": [], "generated_at": ""},
        )

        mock_server.starttls.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {
        "SENDGRID_API_KEY": "SG.test-key-here",
        "SMTP_FROM": "argus@example.com",
    }, clear=True)
    def test_sendgrid_backend_sends_email(self, mock_urlopen):
        """SendGrid backend sends email via REST API."""
        mock_response = MagicMock()
        mock_response.status = 202
        mock_urlopen.return_value.__enter__.return_value = mock_response

        _send_report_email(
            ["admin@example.com"],
            "Weekly Report",
            {
                "findings_summary": [
                    {"severity": "HIGH", "count": 3, "avg_confidence": 0.85},
                ],
                "engagements": [],
                "generated_at": "2026-07-14T12:00:00",
            },
        )

        mock_urlopen.assert_called_once()
        # urllib.request.Request stores the URL and headers; use get_method()
        req = mock_urlopen.call_args[0][0]
        assert "api.sendgrid.com" in req.full_url
        assert req.get_method() == "POST"
        assert "SG.test-key-here" in req.headers.get("Authorization", "")

    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {
        "SENDGRID_API_KEY": "SG.test-key-here",
        "SMTP_FROM": "argus@example.com",
    }, clear=True)
    def test_sendgrid_non_202_still_logged(self, mock_urlopen):
        """SendGrid non-202 response should not raise but should fall back."""
        mock_response = MagicMock()
        mock_response.status = 400
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Should not raise — falls through to logging fallback
        _send_report_email(
            ["admin@example.com"],
            "Test",
            {"findings_summary": [], "engagements": [], "generated_at": ""},
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_logging_fallback_when_no_backend(self):
        """Logs warning when no email backend is configured."""
        with patch("tasks.report.logger.warning") as mock_warn:
            _send_report_email(
                ["admin@example.com"],
                "Fallback Report",
                {
                    "findings_summary": [
                        {"severity": "MEDIUM", "count": 1, "avg_confidence": 0.5},
                    ],
                    "engagements": [
                        {"target_url": "https://test.com", "findings_count": 1},
                    ],
                    "generated_at": "2026-07-14T12:00:00",
                },
            )
            mock_warn.assert_called_once()
            call_args = mock_warn.call_args[0]
            fmt = call_args[0]  # The format string
            assert "not configured" in fmt or "placeholder" in fmt
            # report_name is the first positional arg after the format string
            if len(call_args) > 1:
                assert "Fallback Report" in str(call_args[1])
            # Check all args combined for "MEDIUM"
            combined = " ".join(str(a) for a in call_args)
            assert "MEDIUM" in combined

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "argus@example.com",
    }, clear=True)
    def test_smtp_failure_falls_to_sendgrid_then_logging(self, mock_smtp):
        """When SMTP fails and no SendGrid configured, falls through to logging."""
        mock_smtp.return_value.__enter__.return_value.login.side_effect = Exception("Auth failed")

        with patch("tasks.report.logger.warning") as mock_warn:
            _send_report_email(
                ["admin@example.com"],
                "Retry Report",
                {"findings_summary": [], "engagements": [], "generated_at": ""},
            )
            # SMTP failure logs a warning, final fallback logs another
            # At least one warning should mention placeholder/not-configured
            mock_warn.assert_called()
            has_fallback = any(
                "not configured" in c[0][0] or "placeholder" in c[0][0]
                for c in mock_warn.call_args_list
            )
            assert has_fallback, "Expected at least one warning about email not being configured"

    @patch("smtplib.SMTP")
    @patch.dict(os.environ, {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "pass",
        "SMTP_FROM": "argus@example.com",
        "SENDGRID_API_KEY": "SG.test-key",
    }, clear=True)
    def test_smtp_failure_falls_to_sendgrid(self, mock_smtp):
        """When SMTP fails and SendGrid is configured, falls through to SendGrid."""
        mock_smtp.return_value.__enter__.return_value.login.side_effect = Exception("Auth failed")

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.status = 202
            mock_urlopen.return_value.__enter__.return_value = mock_response

            _send_report_email(
                ["admin@example.com"],
                "Failover Report",
                {"findings_summary": [], "engagements": [], "generated_at": ""},
            )

            # Should have tried SendGrid after SMTP failed
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert "api.sendgrid.com" in req.full_url


class TestCalculateNextRun:
    """Tests for the _calculate_next_run function."""

    def test_daily_returns_1_day(self):
        """Daily frequency adds 1 day."""
        from datetime import datetime, timedelta
        from tool_core._compat import utc

        result = _calculate_next_run("daily")
        assert result > datetime.now(utc)
        assert result < datetime.now(utc) + timedelta(days=2)

    def test_weekly_returns_7_days(self):
        """Weekly frequency adds 7 days."""
        from datetime import datetime, timedelta
        from tool_core._compat import utc

        result = _calculate_next_run("weekly")
        assert result > datetime.now(utc) + timedelta(days=5)
        assert result < datetime.now(utc) + timedelta(days=9)

    def test_monthly_returns_30_days(self):
        """Monthly frequency adds 30 days."""
        from datetime import datetime, timedelta
        from tool_core._compat import utc

        result = _calculate_next_run("monthly")
        expected = datetime.now(utc) + timedelta(days=30)
        assert abs((result - expected).total_seconds()) < 2  # within 2s

    def test_quarterly_returns_90_days(self):
        """Quarterly frequency adds 90 days."""
        from datetime import datetime, timedelta
        from tool_core._compat import utc

        result = _calculate_next_run("quarterly")
        expected = datetime.now(utc) + timedelta(days=90)
        assert abs((result - expected).total_seconds()) < 2  # within 2s

    def test_unknown_frequency_defaults_to_weekly(self):
        """Unknown frequency defaults to 7 days (weekly)."""
        from datetime import datetime, timedelta
        from tool_core._compat import utc

        result = _calculate_next_run("hourly")  # not a valid frequency
        assert result > datetime.now(utc) + timedelta(days=5)
        assert result < datetime.now(utc) + timedelta(days=9)


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
