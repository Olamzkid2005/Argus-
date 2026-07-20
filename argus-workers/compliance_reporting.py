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
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tool_core._compat import StrEnum

logger = logging.getLogger(__name__)


class ComplianceStandard(StrEnum):
    """Supported compliance standards"""

    OWASP_TOP10 = "owasp_top10"
    PCI_DSS = "pci_dss"
    SOC2 = "soc2"
    NIST_CSF = "nist_csf"
    HIPAA = "hipaa"
    ISO_27001 = "iso_27001"


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

    # NIST CSF (Cybersecurity Framework) v1.1 mapping
    NIST_CSF_MAPPING = {
        "SQL_INJECTION": "PR.PT-3 - System and data protection (least functionality)",
        "COMMAND_INJECTION": "PR.PT-3 - System and data protection",
        "XSS": "PR.AC-4 - Access permissions management",
        "BROKEN_ACCESS_CONTROL": "PR.AC-4 - Access permissions management",
        "IDOR": "PR.AC-4 - Access permissions management",
        "PATH_TRAVERSAL": "PR.AC-4 - Access permissions management",
        "CRYPTOGRAPHIC_FAILURE": "PR.DS-1 - Data-at-rest protection",
        "WEAK_TLS": "PR.DS-2 - Data-in-transit protection",
        "AUTH_FAILURE": "PR.AC-7 - Authentication",
        "SESSION_MANAGEMENT": "PR.AC-7 - Authentication",
        "SECURITY_MISCONFIGURATION": "PR.IP-1 - Configuration management",
        "VULNERABLE_COMPONENT": "DE.CM-8 - Vulnerability scans",
        "SSRF": "PR.AC-5 - Network integrity",
        "LOGGING_FAILURE": "DE.AE-3 - Event data analysis",
        "SOFTWARE_INTEGRITY": "PR.DS-6 - Integrity checks",
        "INSECURE_DESIGN": "PR.IP-1 - Baseline configuration",
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

    # HIPAA Security Rule mapping (45 CFR Parts 164.308, 164.310, 164.312)
    HIPAA_MAPPING = {
        "SQL_INJECTION": "164.312(c) - Integrity Controls",
        "COMMAND_INJECTION": "164.312(c) - Integrity Controls",
        "XSS": "164.312(a) - Access Control",
        "BROKEN_ACCESS_CONTROL": "164.312(a) - Access Control",
        "IDOR": "164.312(a) - Access Control",
        "CRYPTOGRAPHIC_FAILURE": "164.312(e) - Transmission Security",
        "WEAK_TLS": "164.312(e) - Transmission Security",
        "AUTH_FAILURE": "164.312(d) - Person or Entity Authentication",
        "SESSION_MANAGEMENT": "164.312(a) - Access Control",
        "SECURITY_MISCONFIGURATION": "164.308(a)(1) - Security Management Process",
        "VULNERABLE_COMPONENT": "164.308(a)(8) - Evaluation",
        "LOGGING_FAILURE": "164.312(b) - Audit Controls",
        "SSRF": "164.308(a)(4) - Information Access Management",
        "PATH_TRAVERSAL": "164.312(a) - Access Control",
        "SOFTWARE_INTEGRITY": "164.312(c) - Integrity Controls",
        "INSECURE_DESIGN": "164.308(a)(1) - Security Management Process",
    }

    # ISO 27001:2022 Annex A mapping
    ISO_27001_MAPPING = {
        "SQL_INJECTION": "A.8.9 - Configuration management",
        "COMMAND_INJECTION": "A.8.9 - Configuration management",
        "XSS": "A.8.20 - Input validation",
        "BROKEN_ACCESS_CONTROL": "A.8.2 - Access control",
        "IDOR": "A.8.2 - Access control",
        "CRYPTOGRAPHIC_FAILURE": "A.8.24 - Use of cryptography",
        "WEAK_TLS": "A.8.24 - Use of cryptography",
        "AUTH_FAILURE": "A.8.5 - Authentication",
        "SESSION_MANAGEMENT": "A.8.5 - Authentication",
        "SECURITY_MISCONFIGURATION": "A.8.8 - Configuration management",
        "VULNERABLE_COMPONENT": "A.8.29 - Security testing",
        "LOGGING_FAILURE": "A.8.16 - Monitoring activities",
        "SSRF": "A.8.20 - Input validation",
        "PATH_TRAVERSAL": "A.8.20 - Input validation",
        "SOFTWARE_INTEGRITY": "A.8.25 - Secure development lifecycle",
        "INSECURE_DESIGN": "A.8.25 - Secure development lifecycle",
    }

    @classmethod
    def map_to_owasp(cls, finding_type: str) -> str:
        """Map finding type to OWASP Top 10 category"""
        return cls.OWASP_MAPPING.get(
            finding_type.upper(), "A05:2021 - Security Misconfiguration"
        )

    @classmethod
    def map_to_pci(cls, finding_type: str) -> str:
        """Map finding type to PCI DSS requirement"""
        return cls.PCI_MAPPING.get(
            finding_type.upper(), "6.5.10 - Unvalidated redirects and forwards"
        )

    @classmethod
    def map_to_soc2(cls, finding_type: str) -> str:
        """Map finding type to SOC 2 criteria"""
        return cls.SOC2_MAPPING.get(
            finding_type.upper(), "CC7.1 - Vulnerability detection"
        )

    @classmethod
    def map_to_nist_csf(cls, finding_type: str) -> str:
        """Map finding type to NIST CSF v1.1 category"""
        return cls.NIST_CSF_MAPPING.get(
            finding_type.upper(), "DE.CM-8 - Vulnerability scans"
        )

    @classmethod
    def map_to_hipaa(cls, finding_type: str) -> str:
        """Map finding type to HIPAA Security Rule reference"""
        return cls.HIPAA_MAPPING.get(
            finding_type.upper(), "164.308(a)(1) - Security Management Process"
        )

    @classmethod
    def map_to_iso_27001(cls, finding_type: str) -> str:
        """Map finding type to ISO 27001:2022 Annex A control"""
        return cls.ISO_27001_MAPPING.get(
            finding_type.upper(), "A.8.8 - Configuration management"
        )


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
            autoescape=select_autoescape(["html", "xml", "j2"]),
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
        findings = findings or []
        report_id = (
            report_id or f"owasp-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

        compliance_findings = []
        category_counts: dict[str, int] = {}

        for finding in findings:
            owasp_ref = self.mapper.map_to_owasp(finding.get("type", "UNKNOWN"))
            category_counts[owasp_ref] = category_counts.get(owasp_ref, 0) + 1

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=owasp_ref,
                    status=finding.get("status", "open"),
                )
            )

        summary = {
            "total_findings": len(findings),
            "categories": category_counts,
            "critical_count": sum(
                1 for f in findings if f.get("severity") == "CRITICAL"
            ),
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
        findings = findings or []
        report_id = (
            report_id or f"pci-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

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
        requirement_status: dict[str, dict[str, Any]] = {
            req: {"status": "compliant", "findings": [], "name": name}
            for req, name in pci_requirements.items()
        }

        for finding in findings:
            pci_ref = self.mapper.map_to_pci(finding.get("type", "UNKNOWN"))
            req_key = pci_ref.split(" - ")[0]

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=pci_ref,
                    status=finding.get("status", "open"),
                )
            )

            if req_key in requirement_status:
                requirement_status[req_key]["status"] = "non_compliant"
                requirement_status[req_key]["findings"].append(finding.get("id", ""))

        summary = {
            "total_findings": len(findings),
            "compliant_requirements": sum(
                1 for r in requirement_status.values() if r["status"] == "compliant"
            ),
            "non_compliant_requirements": sum(
                1 for r in requirement_status.values() if r["status"] == "non_compliant"
            ),
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
        findings = findings or []
        report_id = (
            report_id or f"soc2-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

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
        criteria_status: dict[str, dict[str, Any]] = {
            c: {"status": "pass", "findings": [], "name": name}
            for c, name in soc2_criteria.items()
        }

        for finding in findings:
            soc2_ref = self.mapper.map_to_soc2(finding.get("type", "UNKNOWN"))
            criteria_key = soc2_ref.split(" - ")[0]

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=soc2_ref,
                    status=finding.get("status", "open"),
                )
            )

            if criteria_key in criteria_status:
                criteria_status[criteria_key]["status"] = "fail"
                criteria_status[criteria_key]["findings"].append(finding.get("id", ""))

        summary = {
            "total_findings": len(findings),
            "passing_criteria": sum(
                1 for c in criteria_status.values() if c["status"] == "pass"
            ),
            "failing_criteria": sum(
                1 for c in criteria_status.values() if c["status"] == "fail"
            ),
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

    def generate_nist_csf_report(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate NIST CSF v1.1 compliance report

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        findings = findings or []
        report_id = (
            report_id or f"nist-csf-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

        # NIST CSF Core Functions: Identify, Protect, Detect, Respond, Recover
        nist_functions = {
            "PR.AC": "Access Control",
            "PR.DS": "Data Security",
            "PR.PT": "Protective Technology",
            "PR.IP": "Information Protection",
            "DE.AE": "Anomalies and Events",
            "DE.CM": "Continuous Monitoring",
            "DE.DP": "Detection Processes",
        }

        compliance_findings = []
        function_findings: dict[str, list[str]] = {func: [] for func in nist_functions}

        for finding in findings:
            nist_ref = self.mapper.map_to_nist_csf(finding.get("type", "UNKNOWN"))
            # sub_prefix is the first word before space, e.g. "PR.PT-3"
            sub_prefix = nist_ref.split(" ")[0]  # e.g. "PR.PT-3"

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=nist_ref,
                    status=finding.get("status", "open"),
                )
            )

            # Track findings by function
            for func_key in nist_functions:
                if sub_prefix.startswith(func_key):
                    function_findings[func_key].append(finding.get("id", ""))
                    break

        # Build summary with function-level stats
        functions_summary: dict[str, Any] = {}
        for func_key, func_name in nist_functions.items():
            finding_ids = function_findings[func_key]
            functions_summary[func_key] = {
                "name": func_name,
                "finding_count": len(finding_ids),
                "findings": finding_ids,
            }

        summary = {
            "total_findings": len(findings),
            "functions": functions_summary,
            "passing_functions": sum(
                1 for f in function_findings.values() if len(f) == 0
            ),
            "failing_functions": sum(
                1 for f in function_findings.values() if len(f) > 0
            ),
            "total_functions": len(nist_functions),
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.NIST_CSF,
            title=f"NIST Cybersecurity Framework v1.1 Report - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="nist_csf_report.html",
        )

    def generate_hipaa_report(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate HIPAA Security Rule compliance report

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        findings = findings or []
        report_id = (
            report_id or f"hipaa-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

        # HIPAA Security Rule sections and criteria
        hipaa_sections: dict[str, dict[str, Any]] = {
            "Administrative Safeguards": {
                "css_class": "admin",
                "criteria": {
                    "164.308(a)(1)": "Security Management Process",
                    "164.308(a)(2)": "Assigned Security Responsibility",
                    "164.308(a)(3)": "Workforce Security",
                    "164.308(a)(4)": "Information Access Management",
                    "164.308(a)(5)": "Security Awareness and Training",
                    "164.308(a)(6)": "Security Incident Procedures",
                    "164.308(a)(7)": "Contingency Plan",
                    "164.308(a)(8)": "Evaluation",
                },
            },
            "Physical Safeguards": {
                "css_class": "physical",
                "criteria": {
                    "164.310(a)": "Facility Access Controls",
                    "164.310(b)": "Workstation Use",
                    "164.310(c)": "Workstation Security",
                    "164.310(d)": "Device and Media Controls",
                },
            },
            "Technical Safeguards": {
                "css_class": "technical",
                "criteria": {
                    "164.312(a)": "Access Control",
                    "164.312(b)": "Audit Controls",
                    "164.312(c)": "Integrity Controls",
                    "164.312(d)": "Person or Entity Authentication",
                    "164.312(e)": "Transmission Security",
                },
            },
        }

        compliance_findings = []
        section_status: dict[str, dict[str, Any]] = {}

        for section_name, section_config in hipaa_sections.items():
            section_criteria: dict[str, dict[str, Any]] = {}
            for criteria_id, criteria_name in section_config["criteria"].items():
                section_criteria[criteria_id] = {
                    "name": criteria_name,
                    "status": "pass",
                    "findings": [],
                }
            section_status[section_name] = {
                "name": section_name,
                "css_class": section_config["css_class"],
                "criteria": section_criteria,
                "passing": len(section_criteria),
                "total": len(section_criteria),
            }

        for finding in findings:
            hipaa_ref = self.mapper.map_to_hipaa(finding.get("type", "UNKNOWN"))
            ref_key = hipaa_ref.split(" - ")[0]

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=hipaa_ref,
                    status=finding.get("status", "open"),
                )
            )

            # Map ref to section and mark as failing
            for section_name in list(section_status):
                section_data = section_status[section_name]
                if ref_key in section_data["criteria"]:
                    ctrl = section_data["criteria"][ref_key]
                    if ctrl["status"] == "pass":
                        ctrl["status"] = "fail"
                        section_data["passing"] -= 1
                    ctrl["findings"].append(finding.get("id", ""))
                    break

        passing = sum(1 for s in section_status.values() if s["passing"] == s["total"])
        failing = sum(1 for s in section_status.values() if s["passing"] < s["total"])

        summary = {
            "total_findings": len(findings),
            "critical_count": sum(
                1 for f in findings if f.get("severity") == "CRITICAL"
            ),
            "high_count": sum(1 for f in findings if f.get("severity") == "HIGH"),
            "medium_count": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
            "passing_controls": passing,
            "failing_controls": failing,
            "total_controls": len(section_status),
            "sections": section_status,
            "composite_score": round((passing / max(len(section_status), 1)) * 100),
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.HIPAA,
            title=f"HIPAA Security Rule Compliance Report - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="hipaa_template.html",
        )

    def generate_iso_27001_report(
        self,
        engagement_id: str,
        findings: list[dict],
        report_id: str = None,
    ) -> ComplianceReport:
        """
        Generate ISO 27001:2022 compliance report

        Args:
            engagement_id: Engagement ID
            findings: List of vulnerability findings
            report_id: Optional report ID

        Returns:
            ComplianceReport instance
        """
        findings = findings or []
        report_id = (
            report_id or f"iso27001-{engagement_id}-{datetime.now().strftime('%Y%m%d')}"
        )

        # ISO 27001:2022 Annex A control themes
        iso_themes: dict[str, dict[str, Any]] = {
            "A.5 Organizational": {
                "css_class": "organizational",
                "controls": {
                    "A.5.1": "Information security policies",
                    "A.5.2": "Information security roles",
                    "A.5.15": "Access control",
                    "A.5.23": "Information security for cloud services",
                },
            },
            "A.6 People": {
                "css_class": "people",
                "controls": {
                    "A.6.1": "Screening",
                    "A.6.2": "Terms and conditions of employment",
                    "A.6.3": "Information security awareness and training",
                },
            },
            "A.7 Physical": {
                "css_class": "physical",
                "controls": {
                    "A.7.1": "Physical security perimeters",
                    "A.7.2": "Physical entry controls",
                    "A.7.6": "Working in secure areas",
                    "A.7.10": "Clear desk and clear screen",
                },
            },
            "A.8 Technological": {
                "css_class": "technological",
                "controls": {
                    "A.8.2": "Access control",
                    "A.8.5": "Authentication",
                    "A.8.8": "Configuration management",
                    "A.8.9": "Configuration management",
                    "A.8.16": "Monitoring activities",
                    "A.8.20": "Input validation",
                    "A.8.24": "Use of cryptography",
                    "A.8.25": "Secure development lifecycle",
                    "A.8.29": "Security testing",
                },
            },
        }

        compliance_findings = []
        theme_status: dict[str, dict[str, Any]] = {}

        for theme_name, theme_config in iso_themes.items():
            theme_controls: dict[str, dict[str, Any]] = {}
            for control_id, control_name in theme_config["controls"].items():
                theme_controls[control_id] = {
                    "name": control_name,
                    "status": "pass",
                    "findings": [],
                }
            theme_status[theme_name] = {
                "name": theme_name,
                "css_class": theme_config["css_class"],
                "controls": theme_controls,
                "passing": len(theme_controls),
                "total": len(theme_controls),
            }

        for finding in findings:
            iso_ref = self.mapper.map_to_iso_27001(finding.get("type", "UNKNOWN"))
            ref_key = iso_ref.split(" - ")[0]

            compliance_findings.append(
                ComplianceFinding(
                    finding_id=finding.get("id", ""),
                    type=finding.get("type", "UNKNOWN"),
                    severity=finding.get("severity", "INFO"),
                    endpoint=finding.get("endpoint", ""),
                    description=finding.get("description", ""),
                    remediation=finding.get("remediation", ""),
                    compliance_ref=iso_ref,
                    status=finding.get("status", "open"),
                )
            )

            # Map ref to theme and mark as failing
            for theme_name in list(theme_status):
                theme_data = theme_status[theme_name]
                if ref_key in theme_data["controls"]:
                    ctrl = theme_data["controls"][ref_key]
                    if ctrl["status"] == "pass":
                        ctrl["status"] = "fail"
                        theme_data["passing"] -= 1
                    ctrl["findings"].append(finding.get("id", ""))
                    break

        passing = sum(1 for t in theme_status.values() if t["passing"] == t["total"])
        failing = sum(1 for t in theme_status.values() if t["passing"] < t["total"])

        summary = {
            "total_findings": len(findings),
            "critical_count": sum(
                1 for f in findings if f.get("severity") == "CRITICAL"
            ),
            "high_count": sum(1 for f in findings if f.get("severity") == "HIGH"),
            "medium_count": sum(1 for f in findings if f.get("severity") == "MEDIUM"),
            "passing_controls": passing,
            "failing_controls": failing,
            "total_controls": len(theme_status),
            "themes": theme_status,
            "composite_score": round((passing / max(len(theme_status), 1)) * 100),
        }

        return ComplianceReport(
            id=report_id,
            engagement_id=engagement_id,
            standard=ComplianceStandard.ISO_27001,
            title=f"ISO/IEC 27001:2022 Compliance Report - {engagement_id}",
            generated_at=datetime.now(),
            findings=compliance_findings,
            summary=summary,
            template_used="iso27001_template.html",
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
            logger.warning("Template %s not found, using default", report.template_used)
            try:
                template = self.env.get_template("default_report.html")
            except Exception:
                logger.error(
                    "Default template not found — using minimal inline template"
                )
                template = self.env.from_string(
                    "<html><body><h1>Compliance Report</h1><pre>{{ report | pprint }}</pre></body></html>"
                )

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
        report = generator.generate_pci_dss_checklist(
            engagement_id, findings, report_id
        )
    elif standard == "soc2":
        report = generator.generate_soc2_template(engagement_id, findings, report_id)
    elif standard == "nist_csf":
        report = generator.generate_nist_csf_report(engagement_id, findings, report_id)
    elif standard == "hipaa":
        report = generator.generate_hipaa_report(engagement_id, findings, report_id)
    elif standard == "iso_27001":
        report = generator.generate_iso_27001_report(engagement_id, findings, report_id)
    else:
        raise ValueError(f"Unknown compliance standard: {standard}")

    html = generator.render_report(report)
    json_data = generator.render_to_json(report)

    return {
        "report": json_data,
        "html": html,
    }
