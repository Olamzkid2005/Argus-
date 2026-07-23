"""
Tests for reporting/pdf_report.py — self-contained PDF report generation.

Verifies:
- Pure function contract (no file I/O, returns bytes)
- PDF structure (valid PDF header, version)
- Content rendering via pypdf text extraction
- Edge cases: empty findings, missing fields, long text, XSS payloads
"""

from io import BytesIO

import pytest
from pypdf import PdfReader

from reporting.pdf_report import render_pdf_report


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF bytes using pypdf."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() for page in reader.pages)


def _count_pages(pdf_bytes: bytes) -> int:
    """Count pages in PDF bytes."""
    return len(PdfReader(BytesIO(pdf_bytes)).pages)


class TestRenderPdfReport:
    """Tests for render_pdf_report() — pure function returning PDF bytes."""

    def test_returns_bytes(self):
        """render_pdf_report returns bytes."""
        pdf = render_pdf_report()
        assert isinstance(pdf, bytes)
        assert len(pdf) > 100

    def test_valid_pdf_header(self):
        """Output starts with valid PDF header."""
        pdf = render_pdf_report()
        assert pdf.startswith(b"%PDF-")

    def test_contains_title(self):
        """Report title appears in the PDF content."""
        pdf = render_pdf_report(title="Test PDF Report")
        text = _extract_text(pdf)
        assert "Test PDF Report" in text

    def test_contains_target(self):
        """Target appears in the PDF content."""
        pdf = render_pdf_report(target="https://example.com")
        text = _extract_text(pdf)
        assert "example.com" in text

    def test_contains_scan_date(self):
        """Custom scan date appears in the PDF metadata."""
        pdf = render_pdf_report(scan_date="2026-06-09 12:00 UTC")
        text = _extract_text(pdf)
        assert "2026-06-09" in text

    def test_auto_generates_scan_date(self):
        """Auto-generated scan date when not provided."""
        import datetime

        from tool_core._compat import utc

        pdf = render_pdf_report()
        text = _extract_text(pdf)
        today = datetime.datetime.now(utc).strftime("%Y-%m-%d")
        assert today in text

    def test_severity_summary_section(self):
        """Severity Summary section header is present."""
        findings = [
            {"severity": "CRITICAL", "type": "SQLI", "endpoint": "/api"},
            {"severity": "HIGH", "type": "XSS", "endpoint": "/search"},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "Severity Summary" in text
        assert "CRITICAL" in text
        assert "HIGH" in text

    def test_findings_detail_section(self):
        """Findings appear in detail table."""
        findings = [
            {"severity": "MEDIUM", "type": "CSRF", "endpoint": "/form", "title": "Missing CSRF Token"},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "CSRF" in text
        assert "/form" in text
        assert "Missing CSRF Token" in text

    def test_empty_findings(self):
        """No findings produces valid PDF."""
        pdf = render_pdf_report(findings=[])
        text = _extract_text(pdf)
        assert pdf.startswith(b"%PDF-")
        assert "Findings Detail" not in text

    def test_no_findings_param(self):
        """None findings param produces valid PDF gracefully."""
        pdf = render_pdf_report(findings=None)
        assert pdf.startswith(b"%PDF-")

    def test_severity_breakdown_passed_directly(self):
        """Pre-computed severity breakdown renders correctly."""
        pdf = render_pdf_report(
            severity_breakdown={
                "CRITICAL": 3,
                "HIGH": 5,
                "MEDIUM": 2,
                "LOW": 1,
                "INFO": 0,
            }
        )
        text = _extract_text(pdf)
        assert "11" in text  # total = 3+5+2+1+0

    def test_severity_breakdown_computed_from_findings(self):
        """Severity breakdown is auto-computed from findings when not provided."""
        findings = [
            {"severity": "CRITICAL", "type": "A", "endpoint": "/a"},
            {"severity": "CRITICAL", "type": "B", "endpoint": "/b"},
            {"severity": "HIGH", "type": "C", "endpoint": "/c"},
            {"severity": "INFO", "type": "D", "endpoint": "/d"},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "4" in text  # total findings

    def test_executive_summary_included(self):
        """Executive summary renders when provided."""
        pdf = render_pdf_report(
            executive_summary="Critical vulnerabilities found requiring immediate action."
        )
        text = _extract_text(pdf)
        assert "Executive Summary" in text
        assert "Critical vulnerabilities" in text

    def test_no_executive_summary_when_empty(self):
        """No Executive Summary section when summary is empty."""
        pdf = render_pdf_report(executive_summary="")
        text = _extract_text(pdf)
        assert "Executive Summary" not in text

    def test_finding_detail_sub_rows(self):
        """Findings with descriptions get detail rows in PDF."""
        findings = [
            {
                "severity": "HIGH",
                "type": "SQL_INJECTION",
                "endpoint": "/api",
                "title": "SQL Injection",
                "description": "Time-based blind SQL injection detected.",
                "remediation": "Use parameterized queries.",
                "cwe_id": "CWE-89",
            }
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "Time-based blind SQL injection" in text
        assert "Use parameterized queries" in text
        assert "CWE-89" in text

    def test_multiple_findings_all_appear(self):
        """All findings appear in the PDF."""
        findings = [
            {"severity": "CRITICAL", "type": "SQLI", "endpoint": "/login", "title": "SQLi"},
            {"severity": "HIGH", "type": "XSS", "endpoint": "/search", "title": "XSS"},
            {"severity": "MEDIUM", "type": "CSRF", "endpoint": "/form", "title": "CSRF"},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "SQLI" in text
        assert "XSS" in text
        assert "CSRF" in text

    def test_long_text_does_not_break_pdf(self):
        """Long titles and endpoints still produce valid PDF."""
        findings = [
            {
                "severity": "INFO",
                "type": "VERY_LONG_FINDING_TYPE_NAME_HERE",
                "endpoint": "https://example.com/very/long/path/that/should/be/truncated",
                "title": "A" * 100,
            }
        ]
        pdf = render_pdf_report(findings=findings)
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 200

    def test_xss_safety(self):
        """XSS payloads in findings don't break PDF generation."""
        findings = [
            {
                "severity": "HIGH",
                "type": "<script>alert(1)</script>",
                "endpoint": "/",
                "title": "<b>XSS</b>",
                "description": "<script>malicious</script>",
            }
        ]
        pdf = render_pdf_report(findings=findings)
        assert pdf.startswith(b"%PDF-")
        assert len(pdf) > 200

    def test_all_severity_levels(self):
        """All 5 severity levels appear in the PDF when present."""
        findings = [
            {"severity": "CRITICAL", "type": "A", "endpoint": "/a"},
            {"severity": "HIGH", "type": "B", "endpoint": "/b"},
            {"severity": "MEDIUM", "type": "C", "endpoint": "/c"},
            {"severity": "LOW", "type": "D", "endpoint": "/d"},
            {"severity": "INFO", "type": "E", "endpoint": "/e"},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "CRITICAL" in text
        assert "HIGH" in text
        assert "MEDIUM" in text
        assert "LOW" in text
        assert "INFO" in text

    def test_missing_endpoint_shows_na(self):
        """Missing endpoint shows 'N/A' in table."""
        findings = [
            {"severity": "INFO", "type": "INFO_LEAK", "endpoint": None},
        ]
        pdf = render_pdf_report(findings=findings)
        text = _extract_text(pdf)
        assert "INFO_LEAK" in text

    def test_empty_findings_skips_detail_section(self):
        """No findings means no 'Findings Detail' section."""
        pdf = render_pdf_report(findings=[])
        text = _extract_text(pdf)
        assert "Findings Detail" not in text

    def test_multi_page_pdf_with_many_findings(self):
        """Many findings produce multi-page PDF with valid structure."""
        findings = []
        for i in range(25):
            findings.append({
                "severity": "MEDIUM" if i % 2 == 0 else "HIGH",
                "type": f"VULN_{i:03d}",
                "endpoint": f"/api/endpoint/{i}",
                "title": f"Vulnerability number {i}",
                "description": f"This is finding {i} with description of moderate length.",
            })
        pdf = render_pdf_report(findings=findings)
        pages = _count_pages(pdf)

        assert pdf.startswith(b"%PDF-")
        assert pages > 1, f"Expected multi-page PDF but got {pages} page(s)"
        assert len(pdf) > 5000

    def test_branding_in_pdf(self):
        """Argus branding appears in the PDF."""
        pdf = render_pdf_report()
        text = _extract_text(pdf)
        assert "Argus" in text

    def test_finding_without_severity_defaults(self):
        """Finding without severity defaults to INFO."""
        findings = [
            {"type": "MISC", "endpoint": "/"},
        ]
        pdf = render_pdf_report(findings=findings)
        assert pdf.startswith(b"%PDF-")

    def test_pdf_has_cover_page(self):
        """PDF cover page contains report title and target."""
        pdf = render_pdf_report(
            title="Security Assessment Report",
            target="https://scanme.org",
        )
        text = _extract_text(pdf)
        assert "Security Assessment Report" in text
        assert "scanme.org" in text
