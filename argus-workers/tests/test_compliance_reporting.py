"""
Tests for compliance_reporting.py
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from compliance_reporting import (
    ComplianceMapper,
    ComplianceReportGenerator,
    ComplianceStandard,
    ComplianceFinding,
    ComplianceReport,
    generate_compliance_report,
)


class TestComplianceMapper:
    """Test suite for ComplianceMapper"""

    def test_map_to_owasp_sql_injection(self):
        """Test OWASP mapping for SQL injection"""
        result = ComplianceMapper.map_to_owasp("SQL_INJECTION")
        assert result == "A03:2021 - Injection"

    def test_map_to_owasp_broken_access_control(self):
        """Test OWASP mapping for broken access control"""
        result = ComplianceMapper.map_to_owasp("BROKEN_ACCESS_CONTROL")
        assert result == "A01:2021 - Broken Access Control"

    def test_map_to_owasp_unknown(self):
        """Test OWASP mapping defaults for unknown type"""
        result = ComplianceMapper.map_to_owasp("UNKNOWN_TYPE")
        assert result == "A05:2021 - Security Misconfiguration"

    def test_map_to_pci_sql_injection(self):
        """Test PCI DSS mapping for SQL injection"""
        result = ComplianceMapper.map_to_pci("SQL_INJECTION")
        assert result == "6.5.1 - Injection flaws"

    def test_map_to_pci_weak_tls(self):
        """Test PCI DSS mapping for weak TLS"""
        result = ComplianceMapper.map_to_pci("WEAK_TLS")
        assert result == "4.1 - Strong cryptography"

    def test_map_to_pci_unknown(self):
        """Test PCI DSS mapping defaults for unknown type"""
        result = ComplianceMapper.map_to_pci("UNKNOWN_TYPE")
        assert result == "6.5.10 - Unvalidated redirects and forwards"

    def test_map_to_soc2_auth_failure(self):
        """Test SOC 2 mapping for auth failure"""
        result = ComplianceMapper.map_to_soc2("AUTH_FAILURE")
        assert result == "CC6.1 - Logical access security"

    def test_map_to_soc2_logging_failure(self):
        """Test SOC 2 mapping for logging failure"""
        result = ComplianceMapper.map_to_soc2("LOGGING_FAILURE")
        assert result == "CC7.2 - System monitoring"

    def test_map_to_soc2_unknown(self):
        """Test SOC 2 mapping defaults for unknown type"""
        result = ComplianceMapper.map_to_soc2("UNKNOWN_TYPE")
        assert result == "CC7.1 - Vulnerability detection"

    def test_case_insensitive_mapping(self):
        """Test mappings are case insensitive"""
        assert ComplianceMapper.map_to_owasp("xss") == "A03:2021 - Injection"
        assert ComplianceMapper.map_to_pci("xss") == "6.5.7 - Cross-site scripting"


class TestComplianceReportGenerator:
    """Test suite for ComplianceReportGenerator"""

    @pytest.fixture
    def generator(self):
        return ComplianceReportGenerator(templates_dir="/tmp/test_templates")

    @pytest.fixture
    def sample_findings(self):
        return [
            {
                "id": "F001",
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "https://example.com/api/login",
                "description": "SQL injection in login form",
                "remediation": "Use parameterized queries",
                "status": "open",
            },
            {
                "id": "F002",
                "type": "XSS",
                "severity": "HIGH",
                "endpoint": "https://example.com/search",
                "description": "Reflected XSS",
                "remediation": "Encode output",
                "status": "open",
            },
            {
                "id": "F003",
                "type": "WEAK_TLS",
                "severity": "MEDIUM",
                "endpoint": "https://example.com",
                "description": "TLS 1.0 enabled",
                "remediation": "Disable TLS 1.0",
                "status": "open",
            },
        ]

    def test_generate_owasp_report(self, generator, sample_findings):
        """Test OWASP report generation"""
        report = generator.generate_owasp_report("ENG-001", sample_findings, report_id="RPT-001")

        assert report.id == "RPT-001"
        assert report.engagement_id == "ENG-001"
        assert report.standard == ComplianceStandard.OWASP_TOP10
        assert len(report.findings) == 3
        assert report.summary["total_findings"] == 3
        assert report.summary["critical_count"] == 1
        assert report.summary["high_count"] == 1
        assert report.summary["medium_count"] == 1
        assert "A03:2021 - Injection" in report.summary["categories"]

    def test_generate_pci_dss_checklist(self, generator, sample_findings):
        """Test PCI DSS checklist generation"""
        report = generator.generate_pci_dss_checklist("ENG-001", sample_findings)

        assert report.engagement_id == "ENG-001"
        assert report.standard == ComplianceStandard.PCI_DSS
        assert len(report.findings) == 3
        assert report.summary["total_findings"] == 3
        assert "requirement_status" in report.summary
        assert report.summary["total_requirements"] == 14

    def test_generate_soc2_template(self, generator, sample_findings):
        """Test SOC 2 template generation"""
        report = generator.generate_soc2_template("ENG-001", sample_findings)

        assert report.engagement_id == "ENG-001"
        assert report.standard == ComplianceStandard.SOC2
        assert len(report.findings) == 3
        assert "criteria_status" in report.summary
        assert report.summary["total_criteria"] == 8

    def test_generate_owasp_report_empty_findings(self, generator):
        """Test OWASP report with no findings"""
        report = generator.generate_owasp_report("ENG-002", [])

        assert report.summary["total_findings"] == 0
        assert report.summary["critical_count"] == 0
        assert report.findings == []

    def test_render_report_with_template(self, generator):
        """Test HTML rendering with a found template"""
        report = generator.generate_owasp_report("ENG-001", [])
        report.template_used = "owasp_top10_report.html"

        with patch.object(generator.env, "get_template") as mock_get_template:
            mock_template = MagicMock()
            mock_template.render.return_value = "<html>report</html>"
            mock_get_template.return_value = mock_template

            html = generator.render_report(report)

            mock_get_template.assert_called_once_with("owasp_top10_report.html")
            assert html == "<html>report</html>"

    def test_render_report_fallback_template(self, generator):
        """Test HTML rendering falls back to default template"""
        report = generator.generate_owasp_report("ENG-001", [])
        report.template_used = "missing_template.html"

        with patch.object(generator.env, "get_template") as mock_get_template:
            mock_template = MagicMock()
            mock_template.render.return_value = "<html>default</html>"
            mock_get_template.side_effect = [
                Exception("Template not found"),
                mock_template,
            ]

            html = generator.render_report(report)

            assert mock_get_template.call_count == 2
            assert html == "<html>default</html>"

    def test_render_to_json(self, generator, sample_findings):
        """Test JSON export"""
        report = generator.generate_owasp_report("ENG-001", sample_findings)
        json_data = generator.render_to_json(report)

        assert json_data["engagement_id"] == "ENG-001"
        assert json_data["standard"] == "owasp_top10"
        assert len(json_data["findings"]) == 3
        assert json_data["findings"][0]["finding_id"] == "F001"


class TestGenerateComplianceReport:
    """Test suite for the convenience function"""

    @patch("compliance_reporting.ComplianceReportGenerator")
    def test_generate_owasp_report(self, mock_generator_class):
        """Test convenience function for OWASP"""
        mock_gen = MagicMock()
        mock_generator_class.return_value = mock_gen
        mock_report = MagicMock()
        mock_report.template_used = "test.html"
        mock_report.generated_at = datetime.now()
        mock_gen.generate_owasp_report.return_value = mock_report
        mock_gen.render_report.return_value = "html"
        mock_gen.render_to_json.return_value = {"data": "test"}

        result = generate_compliance_report("owasp_top10", "ENG-001", [])

        assert result["html"] == "html"
        assert result["report"] == {"data": "test"}
        mock_gen.generate_owasp_report.assert_called_once()

    @patch("compliance_reporting.ComplianceReportGenerator")
    def test_generate_pci_report(self, mock_generator_class):
        """Test convenience function for PCI DSS"""
        mock_gen = MagicMock()
        mock_generator_class.return_value = mock_gen
        mock_report = MagicMock()
        mock_report.template_used = "test.html"
        mock_report.generated_at = datetime.now()
        mock_gen.generate_pci_dss_checklist.return_value = mock_report
        mock_gen.render_report.return_value = "html"
        mock_gen.render_to_json.return_value = {"data": "test"}

        result = generate_compliance_report("pci_dss", "ENG-001", [])

        mock_gen.generate_pci_dss_checklist.assert_called_once()

    @patch("compliance_reporting.ComplianceReportGenerator")
    def test_generate_soc2_report(self, mock_generator_class):
        """Test convenience function for SOC 2"""
        mock_gen = MagicMock()
        mock_generator_class.return_value = mock_gen
        mock_report = MagicMock()
        mock_report.template_used = "test.html"
        mock_report.generated_at = datetime.now()
        mock_gen.generate_soc2_template.return_value = mock_report
        mock_gen.render_report.return_value = "html"
        mock_gen.render_to_json.return_value = {"data": "test"}

        result = generate_compliance_report("soc2", "ENG-001", [])

        mock_gen.generate_soc2_template.assert_called_once()

    def test_generate_unknown_standard(self):
        """Test convenience function raises for unknown standard"""
        with pytest.raises(ValueError, match="Unknown compliance standard"):
            generate_compliance_report("unknown", "ENG-001", [])
