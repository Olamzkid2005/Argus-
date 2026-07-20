"""
Tests for reporting/html_report.py — self-contained HTML reports.

Verifies:
- Pure function contract (no file I/O, no side effects)
- Severity cards render correctly
- Findings table renders with expandable details
- XSS safety via html.escape()
- Empty findings handled gracefully
"""

from reporting.html_report import render_html_report


class TestRenderHtmlReport:
    """Tests for render_html_report() — pure function."""

    def test_returns_string(self):
        """render_html_report returns a string."""
        html = render_html_report()
        assert isinstance(html, str)
        assert len(html) > 100

    def test_contains_doctype(self):
        """Output starts with proper HTML5 doctype."""
        html = render_html_report()
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_title(self):
        """Report title appears in the HTML."""
        html = render_html_report(title="Test Report")
        assert "Test Report" in html

    def test_contains_target(self):
        """Target appears in meta section."""
        html = render_html_report(target="https://example.com")
        assert "example.com" in html

    def test_severity_cards_rendered(self):
        """Severity cards appear for all severity levels."""
        findings = [
            {
                "severity": "CRITICAL",
                "type": "SQLI",
                "endpoint": "/api",
                "title": "SQL Injection",
            },
            {"severity": "HIGH", "type": "XSS", "endpoint": "/search", "title": "XSS"},
            {
                "severity": "MEDIUM",
                "type": "CSRF",
                "endpoint": "/form",
                "title": "CSRF",
            },
        ]
        html = render_html_report(findings=findings)
        assert "CRITICAL" in html
        assert "HIGH" in html
        assert "MEDIUM" in html
        assert "search" in html.lower()  # search bar present

    def test_severity_breakdown_passed_directly(self):
        """Pre-computed severity breakdown renders correctly."""
        html = render_html_report(
            severity_breakdown={
                "CRITICAL": 3,
                "HIGH": 5,
                "MEDIUM": 2,
                "LOW": 1,
                "INFO": 0,
            }
        )
        assert "3" in html
        assert "5" in html
        assert "2" in html
        assert "1" in html

    def test_findings_table_has_rows(self):
        """Findings appear as table rows."""
        findings = [
            {
                "severity": "HIGH",
                "type": "SQL_INJECTION",
                "endpoint": "/login",
                "title": "SQLi in login",
            },
            {
                "severity": "LOW",
                "type": "INFO_LEAK",
                "endpoint": "/robots.txt",
                "title": "Info leak",
            },
        ]
        html = render_html_report(findings=findings)
        assert "SQL_INJECTION" in html
        assert "INFO_LEAK" in html
        assert "/login" in html
        assert "/robots.txt" in html

    def test_empty_findings(self):
        """No findings produces empty results gracefully."""
        html = render_html_report(findings=[])
        assert "0" in html  # total findings shows 0

    def test_no_findings_param(self):
        """None findings param produces empty results gracefully."""
        html = render_html_report(findings=None)
        assert "0" in html

    def test_expandable_details(self):
        """Findings with descriptions get expandable detail sections."""
        findings = [
            {
                "severity": "HIGH",
                "type": "SQL_INJECTION",
                "endpoint": "/api",
                "title": "SQLi",
                "description": "Time-based SQL injection detected.",
                "remediation": "Use parameterized queries.",
                "cwe_id": "CWE-89",
            }
        ]
        html = render_html_report(findings=findings)
        assert "Time-based SQL injection" in html
        assert "Use parameterized queries" in html
        assert "CWE-89" in html
        assert "toggleDetail" in html  # expandable
        assert "Copy Fix" in html  # copy button

    def test_xss_safety(self):
        """User data is HTML-escaped to prevent XSS."""
        findings = [
            {
                "severity": "HIGH",
                "type": "<script>alert(1)</script>",
                "endpoint": "/<img onerror=alert(1)>",
                "title": "<b>XSS</b>",
                "description": "<script>malicious</script>",
            }
        ]
        html = render_html_report(findings=findings)
        # Script tags should be escaped, not executable
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
        assert "&lt;script&gt;malicious&lt;/script&gt;" in html
        assert "&lt;b&gt;XSS&lt;/b&gt;" in html
        # Raw script tags should NOT appear
        assert "<script>alert(1)</script>" not in html

    def test_executive_summary_included(self):
        """Executive summary renders when provided."""
        html = render_html_report(
            executive_summary="Critical vulnerabilities found requiring immediate action."
        )
        assert "Executive Summary" in html
        assert "Critical vulnerabilities" in html

    def test_no_executive_summary_when_empty(self):
        """No executive summary section when summary is empty."""
        html = render_html_report(executive_summary="")
        assert "Executive Summary" not in html

    def test_scan_date_included(self):
        """Custom scan date appears in report."""
        html = render_html_report(scan_date="2026-06-09 12:00 UTC")
        assert "2026-06-09" in html

    def test_auto_generates_scan_date(self):
        """Auto-generated scan date when not provided."""
        import datetime

        from tool_core._compat import utc

        html = render_html_report()
        today = datetime.datetime.now(utc).strftime("%Y-%m-%d")
        assert today in html

    def test_self_contained_no_external_refs(self):
        """Report has no external HTTP references."""
        html = render_html_report()
        assert "http://" not in html
        assert (
            "https://" not in html or "https://example.com" in html
        )  # only our target

    def test_no_javascript_error(self):
        """JavaScript functions defined correctly."""
        html = render_html_report(
            findings=[
                {"severity": "LOW", "type": "TEST", "endpoint": "/", "title": "Test"}
            ]
        )
        assert "filterFindings" in html
        assert "toggleDetail" in html
        assert "copyFix" in html
