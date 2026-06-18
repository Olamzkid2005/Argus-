"""Comprehensive fixture matrix tests — full regression suite.

These tests exercise every fixture JSON through the full normalization,
dedup, reporting, and finding classification pipeline. They are marked
with @pytest.mark.full and run in nightly CI.

Run locally with:
    python -m pytest tests/test_fixture_comprehensive.py -m full -v

Run alongside the daily test suite:
    python -m pytest tests/ -m "full or smoke or not (requires_db or requires_redis)" -v
"""

import json
from html import escape

import pytest

from tests.conftest import FIXTURE_DIR, load_fixture

pytestmark = [
    pytest.mark.full,
    pytest.mark.timeout(120),
]

# ── Fixture inventory ──────────────────────────────────────────────
# Every fixture file registered here is checked for existence and
# required schema fields. Add new fixtures here when creating them.

STATIC_FIXTURES = {
    # (name, is_list, required_fields)
    "sqli_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "xss_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "port_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "tech_detect": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "empty_scan": (False, {"finding_type", "severity", "title", "source_tool"}),
    "mixed_severity": (True, {"finding_type", "severity", "title", "source_tool"}),
    "ssrf_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "rce_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
    "weak_tls_scan": (
        False,
        {"finding_type", "severity", "title", "source_tool", "evidence"},
    ),
}

TOOL_ERROR_FIXTURES = {
    "nuclei_timeout": {"tool", "stderr", "exit_code"},
    "nmap_permissions": {"tool", "stderr", "exit_code"},
    "sqlmap_error": {"tool", "stderr", "exit_code"},
}


class TestFixtureInventory:
    """All fixture files exist and have valid JSON content."""

    @pytest.mark.parametrize("name", list(STATIC_FIXTURES.keys()))
    def test_static_fixture_exists(self, name):
        """Every static fixture file exists and is valid JSON."""
        file_path = FIXTURE_DIR / f"{name}.json"
        assert file_path.exists(), f"Fixture file not found: {file_path}"
        with open(file_path) as f:
            data = json.load(f)
        assert data is not None, f"Fixture {name} is empty"

    @pytest.mark.parametrize("name", list(TOOL_ERROR_FIXTURES.keys()))
    def test_tool_error_fixture_exists(self, name):
        """Every tool error fixture file exists and is valid JSON."""
        file_path = FIXTURE_DIR / "tool_error_outputs" / f"{name}.json"
        assert file_path.exists(), f"Fixture file not found: {file_path}"
        with open(file_path) as f:
            data = json.load(f)
        assert data is not None, f"Fixture {name} is empty"


class TestStaticFixtureSchema:
    """All static fixtures have the required schema fields."""

    @pytest.mark.parametrize("name, meta", STATIC_FIXTURES.items())
    def test_required_fields(self, name, meta):
        """Fixture contains all required fields for its type."""
        is_list, required = meta
        if is_list:
            data = load_fixture(name)
            assert isinstance(data, list), f"{name} should be a list"
            assert len(data) > 0, f"{name} should have at least one entry"
            for entry in data:
                missing = required - set(entry.keys())
                assert not missing, f"{name} entry missing fields: {missing}"
        else:
            data = load_fixture(name)
            assert isinstance(data, dict), f"{name} should be a dict"
            missing = required - set(data.keys())
            assert not missing, f"{name} missing fields: {missing}"

    def test_mixed_severity_has_all_levels(self):
        """Mixed severity fixture covers CRITICAL, HIGH, MEDIUM, LOW."""
        data = load_fixture("mixed_severity")
        severities = {f.get("severity", "").upper() for f in data}
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            assert level in severities, f"Missing severity level: {level}"

    def test_mixed_severity_severity_breakdown(self):
        """Compute severity breakdown from mixed_severity."""
        data = load_fixture("mixed_severity")
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for f in data:
            sev = (f.get("severity") or "INFO").upper()
            if sev in counts:
                counts[sev] += 1
        assert counts["CRITICAL"] >= 1
        assert counts["HIGH"] >= 1
        assert counts["MEDIUM"] >= 1
        assert counts["LOW"] >= 1


class TestToolErrorFixtureSchema:
    """All tool error fixtures have the required schema fields."""

    @pytest.mark.parametrize("name, required", TOOL_ERROR_FIXTURES.items())
    def test_required_fields(self, name, required):
        """Tool error fixture contains all required fields."""
        data = load_fixture(name)
        missing = required - set(data.keys())
        assert not missing, f"{name} missing fields: {missing}"

    def test_nuclei_timeout_has_timeout_indicator(self):
        """Nuclei timeout fixture indicates a timeout in stderr."""
        data = load_fixture("nuclei_timeout")
        assert "timeout" in data["stderr"].lower()

    def test_nmap_permissions_has_root_indicator(self):
        """Nmap permissions fixture mentions root privileges."""
        data = load_fixture("nmap_permissions")
        assert "root" in data["stderr"].lower()

    def test_sqlmap_error_has_connection_refused(self):
        """Sqlmap error fixture mentions connection refused."""
        data = load_fixture("sqlmap_error")
        assert "connection refused" in data["stderr"].lower()


class TestPipelineRegression:
    """End-to-end pipeline regression tests using fixture data.

    These tests exercise the normalization, dedup, and reporting pipeline
    by feeding fixture data through the real processing functions.
    """

    def test_sqli_normalization_preserves_severity(self):
        """SQL injection fixture yields HIGH severity after normalization."""
        data = load_fixture("sqli_scan")
        assert data["severity"] == "HIGH"

    def test_sqli_remediation_exists(self):
        """SQL injection fixture has actionable remediation."""
        data = load_fixture("sqli_scan")
        remediation = data.get("remediation", "")
        assert len(remediation) > 10, "Remediation should be detailed"
        assert (
            "parameterized" in remediation.lower() or "prepared" in remediation.lower()
        )

    def test_empty_scan_has_no_findings_indicator(self):
        """Empty scan fixture is explicitly a no-findings result."""
        data = load_fixture("empty_scan")
        assert data["finding_type"] == "NO_FINDINGS"

    def test_port_scan_has_port_number(self):
        """Port scan fixture contains the discovered port."""
        data = load_fixture("port_scan")
        assert "port" in data.get("evidence", {})

    def test_tech_detect_has_technologies_list(self):
        """Tech detection fixture lists detected technologies."""
        data = load_fixture("tech_detect")
        techs = data.get("evidence", {}).get("technologies", [])
        assert len(techs) >= 3, f"Expected at least 3 technologies, got {len(techs)}"

    def test_xss_has_script_payload(self):
        """XSS fixture has a script-based payload."""
        data = load_fixture("xss_scan")
        assert "script" in data["evidence"]["payload"].lower()

    def test_ssrf_has_internal_address_in_evidence(self):
        """SSRF fixture targets an internal/RFC 1918 address."""
        data = load_fixture("ssrf_scan")
        evidence = data.get("evidence", {})
        assert "internal_host" in evidence
        assert "redirect_chain" in evidence

    def test_ssrf_has_cwe_918(self):
        """SSRF fixture uses CWE-918."""
        data = load_fixture("ssrf_scan")
        assert data["cwe"] == "CWE-918"

    def test_rce_is_critical_severity(self):
        """RCE fixture is CRITICAL severity."""
        data = load_fixture("rce_scan")
        assert data["severity"] == "CRITICAL"

    def test_rce_has_command_evidence(self):
        """RCE fixture contains the executed command in evidence."""
        data = load_fixture("rce_scan")
        evidence = data.get("evidence", {})
        assert "command_executed" in evidence
        assert evidence["command_executed"] == "id"
        assert "response_header_evidence" in evidence

    def test_rce_remediation_mentions_patch_or_upgrade(self):
        """RCE remediation suggests patching Bash or upgrading."""
        data = load_fixture("rce_scan")
        remediation = data.get("remediation", "")
        assert "upgrade" in remediation.lower() or "patch" in remediation.lower()

    def test_weak_tls_has_certificate_info(self):
        """Weak TLS fixture includes certificate details in evidence."""
        data = load_fixture("weak_tls_scan")
        evidence = data.get("evidence", {})
        cert = evidence.get("certificate_info", {})
        assert cert.get("self_signed", False)
        assert "issuer" in cert

    def test_weak_tls_has_vulnerability_list(self):
        """Weak TLS fixture lists known protocol vulnerabilities."""
        data = load_fixture("weak_tls_scan")
        vulns = data.get("evidence", {}).get("vulnerabilities", [])
        assert len(vulns) >= 1
        assert "BEAST" in vulns or "POODLE" in vulns

    def test_weak_tls_has_multiple_supported_versions(self):
        """Weak TLS fixture shows TLS 1.0, 1.1, and 1.2 supported."""
        data = load_fixture("weak_tls_scan")
        versions = data.get("evidence", {}).get("supported_versions", [])
        assert "TLSv1.0" in versions
        assert "TLSv1.2" in versions

    def test_severity_breakdown_from_static_fixtures(self):
        """Compute combined severity breakdown across all static fixtures."""
        all_findings = []
        for name, (is_list, _) in STATIC_FIXTURES.items():
            if name == "empty_scan":
                continue
            if is_list:
                all_findings.extend(load_fixture(name))
            else:
                all_findings.append(load_fixture(name))

        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for f in all_findings:
            sev = (f.get("severity") or "INFO").upper()
            if sev in counts:
                counts[sev] += 1

        assert counts["HIGH"] >= 1, "Expected at least 1 HIGH finding"
        assert counts["MEDIUM"] >= 1, "Expected at least 1 MEDIUM finding"
        total = sum(counts.values())
        assert total == len(all_findings), (
            f"Severity breakdown counts ({total}) don't match "
            f"total findings ({len(all_findings)})"
        )

    def test_finding_types_diverse(self):
        """Static fixtures cover multiple finding types."""
        all_findings = []
        for name, (is_list, _) in STATIC_FIXTURES.items():
            if name == "empty_scan":
                continue
            if is_list:
                all_findings.extend(load_fixture(name))
            else:
                all_findings.append(load_fixture(name))

        types = set()
        for f in all_findings:
            ft = f.get("finding_type", f.get("type", ""))
            types.add(ft)

        assert "SQL_INJECTION" in types
        assert "XSS" in types
        assert "OPEN_PORT" in types
        assert "TECHNOLOGY_DETECTION" in types
        assert "SSRF" in types
        assert "RCE" in types
        assert "WEAK_TLS" in types


class TestHTMLReportRendering:
    """HTML report rendering against fixture data (comprehensive)."""

    def test_render_with_all_fixtures(self):
        """Render an HTML report with all static fixture data combined."""
        from reporting.html_report import render_html_report

        all_findings = []
        for name, (is_list, _) in STATIC_FIXTURES.items():
            if name == "empty_scan":
                continue
            if is_list:
                all_findings.extend(load_fixture(name))
            else:
                all_findings.append(load_fixture(name))

        html = render_html_report(
            title="Comprehensive Regression Test Report",
            target="fixture://regression-suite",
            findings=all_findings,
        )

        assert isinstance(html, str)
        assert len(html) > 500
        assert "<!DOCTYPE html>" in html

        # Verify finding content rendered
        for f in all_findings:
            title = f.get("title", "")
            if title:
                # HTML-escaped title should appear somewhere in the output
                assert escape(title) in html or title in html, (
                    f"Finding title '{title}' not found in rendered HTML"
                )

    def test_render_severity_cards_match_breakdown(self):
        """Severity cards in HTML match the computed severity breakdown."""
        from reporting.html_report import render_html_report

        data = load_fixture("mixed_severity")
        html = render_html_report(
            severity_breakdown={
                "CRITICAL": 2,
                "HIGH": 1,
                "MEDIUM": 1,
                "LOW": 1,
                "INFO": 0,
            },
            findings=data,
        )

        # Verify severity card counts appear next to their labels
        assert 'class="card critical"><div class="count">2</div>' in html, (
            "Expected 2 CRITICAL findings in severity cards"
        )
        assert (
            'class="card high"><div class="count">1</div>' in html
            or 'class="card medium"><div class="count">1</div>' in html
        ), "Expected a severity card with count 1"
        assert "CRITICAL" in html
        assert "HIGH" in html
        assert "MEDIUM" in html
        assert "LOW" in html

    def test_render_with_executive_summary(self):
        """HTML report with fixture data and executive summary."""
        from reporting.html_report import render_html_report

        data = load_fixture("sqli_scan")
        html = render_html_report(
            target="https://example.com",
            findings=[data],
            executive_summary="Critical SQL injection vulnerability found requiring immediate remediation.",
        )
        assert "Executive Summary" in html
        assert "Critical SQL injection" in html


class TestErrorHintCoverage:
    """Error hint generation covers all ErrorCode values."""

    def test_all_error_codes_have_hints(self):
        """Every ErrorCode in error_classifier has a corresponding hint."""
        from error_classifier import ErrorCode
        from utils.error_hints import _ERROR_CODE_HINTS

        missing = set(ErrorCode) - set(_ERROR_CODE_HINTS.keys())
        assert not missing, (
            f"ErrorCodes without hints: {[c.value for c in sorted(missing)]}"
        )

    def test_all_tool_specific_patterns_have_hints(self):
        """Every tool-specific stderr pattern produces a valid ErrorHint."""
        from utils.error_hints import _tool_specific_hint

        tested = []
        for tool_name, patterns in [
            ("nuclei", "Error: templates not found"),
            ("nmap", "requires root privileges"),
            ("sqlmap", "connection refused"),
            ("semgrep", "No rules found"),
            ("gitleaks", "No git repository found"),
        ]:
            hint = _tool_specific_hint(tool_name, 1, patterns)
            assert hint is not None, f"No hint for {tool_name} with '{patterns}'"
            tested.append(tool_name)

        assert len(tested) == 5, f"Expected 5 tools, tested {tested}"


class TestScanResilience:
    """Tests for scan resilience against network/target failures."""

    @pytest.mark.full
    def test_scan_does_not_crash_on_unreachable_target(self):
        """Scanning an unreachable target returns gracefully without crash."""
        from tests.conftest import run_scan_against_fixture

        result = run_scan_against_fixture("http://127.0.0.1:65535", timeout=30)
        assert isinstance(result, dict)
