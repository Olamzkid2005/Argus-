"""
Compliance Reporting Framework for Argus Platform

Generates structured compliance reports (OWASP Top 10, PCI DSS, SOC 2)
using Jinja2 templates.

Requirements: 17.1, 17.2, 17.3, 17.4
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)


class ComplianceStandard(StrEnum):
    """Supported compliance standards"""
    OWASP_TOP10 = "owasp_top10"
    PCI_DSS = "pci_dss"
    SOC2 = "soc2"


@dataclass
class ComplianceFinding:
    """Finding mapped to compliance requirement"""
    finding_id: str
    type: str
    severity: str
    endpoint: str
    description: str
    remediation: str
    compliance_ref: str
    status: str = "open"


@dataclass
class ComplianceReport:
    """Generated compliance report"""
    id: str
    engagement_id: str
    standard: ComplianceStandard
    title: str
    generated_at: datetime
    findings: list[ComplianceFinding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    template_used: str = ""


class ComplianceMapper:
    """Maps vulnerability findings to compliance requirements"""

    # OWASP Top 10 2021 mapping
    OWASP_MAPPING = {
        "SQL_INJECTION": "A03:2021 - Injection",
        "COMMAND_INJECTION": "A03:2021 - Injection",
        "XSS": "A03:2021 - Injection",
        "XXE": "A03:2021 - Injection",
        "BROKEN_ACCESS_CONTROL": "A01:2021 - Broken Access Control",
        "IDOR": "A01:2021 - Broken Access Control",
        "PATH_TRAVERSAL": "A01:2021 - Broken Access Control",
        "CRYPTOGRAPHIC_FAILURE": "A02:2021 - Cryptographic Failures",
        "WEAK_TLS": "A02:2021 - Cryptographic Failures",
        "INSECURE_DESIGN": "A04:2021 - Insecure Design",
        "SECURITY_MISCONFIGURATION": "A05:2021 - Security Misconfiguration",
        "VULNERABLE_COMPONENT": "A06:2021 - Vulnerable and Outdated Components",
        "AUTH_FAILURE": "A07:2021 - Identification and Authentication Failures",
        "SESSION_MANAGEMENT": "A07:2021 - Identification and Authentication Failures",
        "SOFTWARE_INTEGRITY": "A08:2021 - Software and Data Integrity Failures",
        "SSRF": "A10:2021 - Server-Side Request Forgery",
        "LOGGING_FAILURE": "A09:2021 - Security Logging and Monitoring Failures",
    }

    # PCI DSS 4.0 requirement mapping
    PCI_MAPPING = {
        "SQL_INJECTION": "6.5.1 - Injection flaws",
        "COMMAND_INJECTION": "6.5.1 - Injection flaws",
        "XSS": "6.5.7 - Cross-site scripting",
        "BROKEN_ACCESS_CONTROL": "6.5.8 - Improper access control",
        "IDOR": "6.5.8 - Improper access control",
        "CRYPTOGRAPHIC_FAILURE": "3.6 - Cryptographic keys protection",
        "WEAK_TLS": "4.1 - Strong cryptography",
        "AUTH_FAILURE": "8.2 - Strong authentication",
        "SESSION_MANAGEMENT": "8.2 - Strong authentication",
        "SECURITY_MISCONFIGURATION": "2.2 - Configuration standards",
        "VULNERABLE_COMPONENT": "6.3 - Software security patches",
        "LOGGING_FAILURE": "10.2 - Audit trail coverage",
    }

    # SOC 2 Trust Services Criteria mapping
    SOC2_MAPPING = {
        "AUTH_FAILURE": "CC6.1 - Logical access security",
        "SESSION_MANAGEMENT": "CC6.1 - Logical access security",
        "BROKEN_ACCESS_CONTROL": "CC6.1 - Logical access security",
        "IDOR": "CC6.1 - Logical access security",
        "CRYPTOGRAPHIC_FAILURE": "CC6.7 - Encryption",
        "WEAK_TLS": "CC6.7 - Encryption",
        "SQL_INJECTION": "CC7.1 - Vulnerability detection",
        "COMMAND_INJECTION": "CC7.1 - Vulnerability detection",
        "XSS": "CC7.1 - Vulnerability detection",
        "SECURITY_MISCONFIGURATION": "CC7.1 - Vulnerability detection",
        "VULNERABLE_COMPONENT": "CC7.1 - Vulnerability detection",
        "LOGGING_FAILURE": "CC7.2 - System monitoring",
    }

    @classmethod
    def map_to_owasp(cls, finding_type: str) -> str:
        """Map finding type to OWASP Top 10 category"""
        return cls.OWASP_MAPPING.get(finding_type.upper(), "A05:2021 - Security Misconfiguration")

    @classmethod
    def map_to_pci(cls, finding_type: str) -> str:
        """Map finding type to PCI DSS requirement"""
        return cls.PCI_MAPPING.get(finding_type.upper(), "6.5.10 - Unvalidated redirects and forwards")

    @classmethod
    def map_to_soc2(cls, finding_type: str) -> str:
        """Map finding type to SOC 2 criteria"""
        return cls.SOC2_MAPPING.get(finding_type.upper(), "CC7.1 - Vulnerability detection")


class ComplianceReportGenerator:
    """Generates compliance reports from vulnerability findings"""

    def __init__(self, templates_dir: str = None):
        """
        Initialize report generator

        Args:
            templates_dir: Directory containing Jinja2 templates
        """
        if templates_dir is None:
            templates_dir = os.path.join(
                os.path.dirname(__file__), "templates", "compliance"
            )

        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.mapper = ComplianceMapper()

    def generate_owasp_report(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate OWASP Top 10 compliance report

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        report_id = report_id or f"owasp-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"

        compliance_findings = []
        category_counts = {}

        for finding in findings:
            owasp_ref = self.mapper.map_to_owasp(finding.get("type", "UNKNOWN"))
            category_counts[owasp_ref] = category_counts.get(owasp_ref, 0) + 1

            compliance_findings.append(ComplianceFinding(
                finding_id=finding.get("id", ""),
                type=finding.get("type", "UNKNOWN"),
                severity=finding.get("severity", "INFO"),
                endpoint=finding.get("endpoint", ""),
                description=finding.get("description", ""),
                remediation=finding.get("remediation", ""),
                compliance_ref=owasp_ref,
                status=finding.get("status", "open"),
            ))

        summary = {
            "total_findings": len(findings),
            "categories": category_counts,
            "critical_count": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
            "high_count": sum(1 for f in findings if f.get("severity") == "HIGH"),
            "medium_count": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
            "low_count": sum(1 for f in findings if f.get("severity") == "LOW"),
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.OWASP_TOP10,
            title=f"OWASP Top 10 Compliance Report - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="owasp_top10_report.html",
        )

    def generate_pci_dss_checklist(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate PCI DSS checklist report

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        report_id = report_id or f"pci-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"

        # PCI DSS 4.0 requirements checklist
        pci_requirements = {
            "1.1": "Processes and mechanisms for network security controls",
            "2.1": "Processes and mechanisms for system components",
            "2.2": "Configuration standards",
            "3.1": "Processes and mechanisms for protecting stored data",
            "3.6": "Cryptographic keys protection",
            "4.1": "Strong cryptography and security protocols",
            "6.3": "Software security patches",
            "6.5.1": "Injection flaws",
            "6.5.7": "Cross-site scripting",
            "6.5.8": "Improper access control",
            "6.5.10": "Unvalidated redirects and forwards",
            "8.2": "Strong authentication",
            "10.2": "Audit trail coverage",
            "11.3.2": "Vulnerability scanning",
        }

        compliance_findings = []
        requirement_status = {
            req: {"status": "compliant", "findings": [], "name": name}
            for req, name in pci_requirements.items()
        }

        for finding in findings:
            pci_ref = self.mapper.map_to_pci(finding.get("type", "UNKNOWN"))
            req_key = pci_ref.split(" - ")[0]

            compliance_findings.append(ComplianceFinding(
                finding_id=finding.get("id", ""),
                type=finding.get("type", "UNKNOWN"),
                severity=finding.get("severity", "INFO"),
                endpoint=finding.get("endpoint", ""),
                description=finding.get("description", ""),
                remediation=finding.get("remediation", ""),
                compliance_ref=pci_ref,
                status=finding.get("status", "open"),
            ))

            if req_key in requirement_status:
                requirement_status[req_key]["status"] = "non_compliant"
                requirement_status[req_key]["findings"].append(finding.get("id", ""))

        summary = {
            "total_findings": len(findings),
            "compliant_requirements": sum(1 for r in requirement_status.values() if r["status"] == "compliant"),
            "non_compliant_requirements": sum(1 for r in requirement_status.values() if r["status"] == "non_compliant"),
            "total_requirements": len(pci_requirements),
            "requirement_status": requirement_status,
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.PCI_DSS,
            title=f"PCI DSS 4.0 Compliance Checklist - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="pci_dss_checklist.html",
        )

    def generate_soc2_template(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate SOC 2 compliance template

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        report_id = report_id or f"soc2-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"

        # SOC 2 Trust Services Criteria
        soc2_criteria = {
            "CC6.1": "Logical and physical access controls",
            "CC6.2": "Prior to access",
            "CC6.3": "Access removal",
            "CC6.6": "Encryption for data transmission",
            "CC6.7": "Encryption for data at rest",
            "CC7.1": "Vulnerability detection",
            "CC7.2": "System monitoring",
            "CC8.1": "Change management",
        }

        compliance_findings = []
        criteria_status = {
            c: {"status": "pass", "findings": [], "name": name}
            for c, name in soc2_criteria.items()
        }

        for finding in findings:
            soc2_ref = self.mapper.map_to_soc2(finding.get("type", "UNKNOWN"))
            criteria_key = soc2_ref.split(" - ")[0]

            compliance_findings.append(ComplianceFinding(
                finding_id=finding.get("id", ""),
                type=finding.get("type", "UNKNOWN"),
                severity=finding.get("severity", "INFO"),
                endpoint=finding.get("endpoint", ""),
                description=finding.get("description", ""),
                remediation=finding.get("remediation", ""),
                compliance_ref=soc2_ref,
                status=finding.get("status", "open"),
            ))

            if criteria_key in criteria_status:
                criteria_status[criteria_key]["status"] = "fail"
                criteria_status[criteria_key]["findings"].append(finding.get("id", ""))

        summary = {
            "total_findings": len(findings),
            "passing_criteria": sum(1 for c in criteria_status.values() if c["status"] == "pass"),
            "failing_criteria": sum(1 for c in criteria_status.values() if c["status"] == "fail"),
            "total_criteria": len(soc2_criteria),
            "criteria_status": criteria_status,
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.SOC2,
            title=f"SOC 2 Type II Compliance Report - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="soc2_template.html",
        )

    def render_report(self, report: ComplianceReport) -> str:
        """
        Render compliance report using Jinja2 template

        Args:
            report: ComplianceReport instance

        Returns:
            Rendered HTML string
        """
        try:
            template = self.env.get_template(report.template_used)
        except Exception:
            logger.warning(f"Template {report.template_used} not found, using default")
            template = self.env.get_template("default_report.html")

        return template.render(
            report=report,
            generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        )

    def render_to_json(self, report: ComplianceReport) -> dict:
        """
        Export compliance report to JSON format

        Args:
            report: ComplianceReport instance

        Returns:
            JSON-compatible dictionary
        """
        return {
            "id": report.id,
            "engagement_id": report.engagement_id,
            "standard": report.standard.value,
            "title": report.title,
            "generated_at": report.generated_at.isoformat(),
            "summary": report.summary,
            "findings": [
                {
                    "finding_id": f.finding_id,
                    "type": f.type,
                    "severity": f.severity,
                    "endpoint": f.endpoint,
                    "description": f.description,
                    "remediation": f.remediation,
                    "compliance_ref": f.compliance_ref,
                    "status": f.status,
                }
                for f in report.findings
            ],
        }


def generate_compliance_report(
    standard: str,
    engagement_id: str,
    findings: list[dict],
    report_id: str = None,
) -> dict:
    """
    Convenience function to generate a compliance report

    Args:
        standard: Compliance standard (owasp_top10, pci_dss, soc2)
        engagement_id: Engagement ID
        findings: List of findings
        report_id: Optional report ID

    Returns:
        Dictionary with report data and rendered HTML
    """
    generator = ComplianceReportGenerator()

    if standard == "owasp_top10":
        report = generator.generate_owasp_report(engagement_id, findings, report_id)
    elif standard == "pci_dss":
        report = generator.generate_pci_dss_checklist(engagement_id, findings, report_id)
    elif standard == "soc2":
        report = generator.generate_soc2_template(engagement_id, findings, report_id)
    else:
        raise ValueError(f"Unknown compliance standard: {standard}")

    html = generator.render_report(report)
    json_data = generator.render_to_json(report)

    return {
        "report": json_data,
        "html": html,
    }
