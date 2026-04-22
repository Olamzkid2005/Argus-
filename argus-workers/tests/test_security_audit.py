"""
Tests for security_audit.py

Validates: Environment checks, dependency scanning, TLS config, full audit run
"""
import pytest
import os
from unittest.mock import Mock, patch, mock_open

from security_audit import SecurityAudit, SecurityFinding


class TestSecurityAudit:
    """Tests for SecurityAudit class"""

    @pytest.fixture
    def audit(self):
        """Fixture providing a fresh SecurityAudit instance"""
        return SecurityAudit()

    def test_init(self, audit):
        """Test audit initialization"""
        assert audit.findings == []

    def test_check_environment_variables_weak_secret(self, audit):
        """Test detecting weak secrets in environment variables"""
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:password@remote-host/db"}, clear=False):
            audit.check_environment_variables()

        env_findings = [f for f in audit.findings if f.check_id == "ENV-001"]
        assert len(env_findings) >= 1
        assert env_findings[0].severity == "medium"
        assert "DATABASE_URL" in env_findings[0].title

    def test_check_environment_variables_missing_required(self, audit):
        """Test detecting missing required variables"""
        with patch.dict(os.environ, {"NEXTAUTH_SECRET": ""}, clear=False):
            with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
                audit.check_environment_variables()

        required_findings = [f for f in audit.findings if f.check_id == "ENV-002"]
        assert len(required_findings) >= 1
        assert required_findings[0].severity == "critical"

    def test_check_environment_variables_localhost_not_flagged(self, audit):
        """Test localhost in value does not falsely trigger weak secret"""
        # Reset findings and use a localhost-only value
        audit.findings = []
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user@localhost/db"}, clear=False):
            audit.check_environment_variables()

        env_findings = [f for f in audit.findings if f.check_id == "ENV-001" and "DATABASE_URL" in f.title]
        assert len(env_findings) == 0

    def test_check_database_security_ssl_disabled(self, audit):
        """Test detecting disabled SSL in database URL"""
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host/db?sslmode=disable"}, clear=False):
            audit.check_database_security()

        finding = [f for f in audit.findings if f.check_id == "DB-001"]
        assert len(finding) == 1
        assert finding[0].severity == "high"

    def test_check_database_security_default_user(self, audit):
        """Test detecting default postgres user"""
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://postgres:pass@host/db"}, clear=False):
            audit.check_database_security()

        finding = [f for f in audit.findings if f.check_id == "DB-002"]
        assert len(finding) == 1
        assert finding[0].severity == "medium"

    def test_check_celery_security_unencrypted_redis(self, audit):
        """Test detecting unencrypted Redis connection"""
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost:6379"}, clear=False):
            audit.check_celery_security()

        finding = [f for f in audit.findings if f.check_id == "CELERY-001"]
        assert len(finding) == 1
        assert finding[0].severity == "medium"

    def test_check_celery_security_encrypted_redis_ok(self, audit):
        """Test encrypted Redis connection is not flagged"""
        with patch.dict(os.environ, {"REDIS_URL": "rediss://localhost:6379"}, clear=False):
            audit.check_celery_security()

        finding = [f for f in audit.findings if f.check_id == "CELERY-001"]
        assert len(finding) == 0

    def test_check_celery_security_shared_db(self, audit):
        """Test detecting shared broker/backend Redis DB"""
        with patch.dict(os.environ, {
            "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
        }, clear=False):
            audit.check_celery_security()

        finding = [f for f in audit.findings if f.check_id == "CELERY-002"]
        assert len(finding) == 1
        assert finding[0].severity == "low"

    def test_check_file_permissions_world_readable(self, audit):
        """Test detecting world-readable sensitive files"""
        mock_stat = Mock()
        mock_stat.st_mode = 0o644  # world-readable

        with patch("os.walk", return_value=[(".", [], [".env"])]):
            with patch("os.stat", return_value=mock_stat):
                audit.check_file_permissions()

        finding = [f for f in audit.findings if f.check_id == "FILE-001"]
        assert len(finding) >= 1
        assert ".env" in finding[0].title

    def test_check_file_permissions_restricted(self, audit):
        """Test restricted files are not flagged"""
        mock_stat = Mock()
        mock_stat.st_mode = 0o600  # owner only

        with patch("os.walk", return_value=[(".", [], [".env"])]):
            with patch("os.stat", return_value=mock_stat):
                audit.check_file_permissions()

        finding = [f for f in audit.findings if f.check_id == "FILE-001"]
        assert len(finding) == 0

    def test_check_dependencies_pinned(self, audit):
        """Test detecting pinned dependency versions"""
        req_content = "requests==2.28.1\nnumpy==1.23.0\n"
        with patch("os.path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=req_content)):
                audit.check_dependencies()

        finding = [f for f in audit.findings if f.check_id == "DEP-001"]
        assert len(finding) == 1
        assert finding[0].severity == "info"

    def test_check_dependencies_no_requirements(self, audit):
        """Test no findings when requirements.txt missing"""
        with patch("os.path.exists", return_value=False):
            audit.check_dependencies()

        finding = [f for f in audit.findings if f.check_id == "DEP-001"]
        assert len(finding) == 0

    def test_check_ssl_tls_missing_in_production(self, audit):
        """Test missing TLS config in production is flagged"""
        with patch.dict(os.environ, {"NODE_ENV": "production"}, clear=False):
            with patch.dict(os.environ, {"SSL_CERT_PATH": "", "TLS_ENABLED": ""}, clear=False):
                audit.check_ssl_tls()

        finding = [f for f in audit.findings if f.check_id == "TLS-001"]
        assert len(finding) == 1
        assert finding[0].severity == "high"

    def test_check_ssl_tls_enabled(self, audit):
        """Test TLS explicitly enabled is not flagged"""
        with patch.dict(os.environ, {"NODE_ENV": "production", "TLS_ENABLED": "1"}, clear=False):
            audit.check_ssl_tls()

        finding = [f for f in audit.findings if f.check_id == "TLS-001"]
        assert len(finding) == 0

    def test_check_ssl_tls_development(self, audit):
        """Test missing TLS in development is not flagged"""
        with patch.dict(os.environ, {"NODE_ENV": "development"}, clear=False):
            audit.check_ssl_tls()

        finding = [f for f in audit.findings if f.check_id == "TLS-001"]
        assert len(finding) == 0

    def test_check_rate_limiting_missing(self, audit):
        """Test missing rate limiting config is flagged"""
        with patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": ""}, clear=False):
            audit.check_rate_limiting()

        finding = [f for f in audit.findings if f.check_id == "RATE-001"]
        assert len(finding) == 1
        assert finding[0].severity == "medium"

    def test_run_all_checks(self, audit):
        """Test run_all_checks executes all checks and returns findings"""
        with patch.object(audit, "check_environment_variables") as mock_env:
            with patch.object(audit, "check_database_security") as mock_db:
                with patch.object(audit, "check_celery_security") as mock_celery:
                    with patch.object(audit, "check_file_permissions") as mock_file:
                        with patch.object(audit, "check_dependencies") as mock_dep:
                            with patch.object(audit, "check_ssl_tls") as mock_ssl:
                                with patch.object(audit, "check_rate_limiting") as mock_rate:
                                    audit.findings = [SecurityFinding("info", "test", "title", "desc", "fix", "TEST-001")]
                                    result = audit.run_all_checks()

        assert result is audit.findings
        mock_env.assert_called_once()
        mock_db.assert_called_once()
        mock_celery.assert_called_once()
        mock_file.assert_called_once()
        mock_dep.assert_called_once()
        mock_ssl.assert_called_once()
        mock_rate.assert_called_once()

    def test_generate_report(self, audit):
        """Test generate_report produces correct structure"""
        controlled_findings = [
            SecurityFinding("critical", "config", "Crit", "Desc", "Fix", "C-001"),
            SecurityFinding("high", "network", "High", "Desc", "Fix", "H-001"),
            SecurityFinding("medium", "config", "Med", "Desc", "Fix", "M-001"),
        ]
        with patch.object(audit, "run_all_checks", return_value=controlled_findings):
            report = audit.generate_report()

        assert "timestamp" in report
        assert report["summary"]["total_findings"] == 3
        assert report["summary"]["critical"] == 1
        assert report["summary"]["high"] == 1
        assert report["summary"]["medium"] == 1
        assert report["summary"]["low"] == 0
        assert report["summary"]["info"] == 0
        assert len(report["findings"]) == 3
        assert report["findings"][0]["check_id"] == "C-001"

    def test_generate_report_empty(self, audit):
        """Test generate_report with no findings"""
        with patch.object(audit, "run_all_checks", return_value=[]):
            report = audit.generate_report()

        assert report["summary"]["total_findings"] == 0
        assert report["findings"] == []

    @patch("builtins.print")
    def test_print_report(self, mock_print, audit):
        """Test print_report outputs report to console"""
        audit.findings = [
            SecurityFinding("high", "network", "TLS Issue", "Desc", "Fix", "TLS-001"),
        ]
        audit.print_report()

        assert mock_print.call_count > 0
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        assert "ARGUS SECURITY AUDIT REPORT" in printed
        assert "TLS Issue" in printed

    @patch("security_audit.sys.exit")
    @patch("builtins.print")
    def test_main_exits_error_on_critical(self, mock_print, mock_exit):
        """Test main exits with error code when critical findings exist"""
        mock_exit.side_effect = SystemExit
        with patch.object(SecurityAudit, "run_all_checks", return_value=[
            SecurityFinding("critical", "config", "Crit", "Desc", "Fix", "C-001")
        ]):
            from security_audit import main
            with pytest.raises(SystemExit):
                main()

        mock_exit.assert_called_once_with(1)

    @patch("security_audit.sys.exit")
    @patch("builtins.print")
    def test_main_exits_ok(self, mock_print, mock_exit):
        """Test main exits with 0 when no critical/high findings"""
        with patch.object(SecurityAudit, "run_all_checks", return_value=[
            SecurityFinding("medium", "config", "Med", "Desc", "Fix", "M-001")
        ]):
            from security_audit import main
            main()

        mock_exit.assert_called_once_with(0)
