"""
Tests for tasks/self_scan.py — Argus platform security self-scan.
"""

from unittest.mock import MagicMock, patch

from tasks.self_scan import run_self_scan


class TestRunSelfScan:
    """Test suite for run_self_scan"""

    @patch("security_audit.SecurityAudit")
    def test_runs_security_audit_and_returns_completed_with_summary(self, mock_security_audit):
        mock_audit = MagicMock()
        mock_audit.generate_report.return_value = {
            "summary": {
                "total_findings": 5,
                "critical": 0,
                "high": 2,
            }
        }
        mock_security_audit.return_value = mock_audit

        result = run_self_scan.run()

        assert result == {
            "status": "completed",
            "summary": {"total_findings": 5, "critical": 0, "high": 2},
            "findings_count": 5,
        }
        mock_security_audit.assert_called_once()
        mock_audit.generate_report.assert_called_once()

    @patch("security_audit.SecurityAudit")
    def test_logs_critical_message_when_critical_findings_exist(self, mock_security_audit):
        mock_audit = MagicMock()
        mock_audit.generate_report.return_value = {
            "summary": {
                "total_findings": 3,
                "critical": 2,
                "high": 1,
            }
        }
        mock_security_audit.return_value = mock_audit

        with patch("tasks.self_scan.logger") as mock_logger:
            result = run_self_scan.run()

        assert result["status"] == "completed"
        assert result["summary"]["critical"] == 2
        mock_logger.critical.assert_called_once_with(
            "CRITICAL: Self-scan found 2 critical security issues!"
        )

    @patch("security_audit.SecurityAudit")
    def test_handles_exceptions_gracefully(self, mock_security_audit):
        mock_security_audit.side_effect = RuntimeError("Audit crashed")

        result = run_self_scan.run()

        assert result == {
            "status": "error",
            "error": "Audit crashed",
        }

    @patch("security_audit.SecurityAudit")
    def test_no_critical_log_when_zero_critical_findings(self, mock_security_audit):
        mock_audit = MagicMock()
        mock_audit.generate_report.return_value = {
            "summary": {
                "total_findings": 10,
                "critical": 0,
                "high": 5,
            }
        }
        mock_security_audit.return_value = mock_audit

        with patch("tasks.self_scan.logger") as mock_logger:
            result = run_self_scan.run()

        assert result["status"] == "completed"
        mock_logger.critical.assert_not_called()
