"""Tests for tools.bugbounty_report_generator — Bug Bounty Report Generator."""

from __future__ import annotations

import pytest

from tools.bugbounty_report_generator import (
    VULN_META,
    ArgusFindingAdapter,
    BugBountyReportGenerator,
    format_steps,
    generate_bugcrowd,
    generate_hackerone,
    generate_intigriti,
    generate_yeswehack,
    get_field,
)


class TestFormatSteps:
    """Tests for format_steps()."""

    def test_list_input_formats_correctly(self):
        steps = ["Step one", "Step two", "Step three"]
        result = format_steps(steps)
        assert result == "1. Step one\n2. Step two\n3. Step three"

    def test_string_input_formats_correctly(self):
        steps = "Do this\nThen do that\nFinally do this"
        result = format_steps(steps)
        assert result == "1. Do this\n2. Then do that\n3. Finally do this"

    def test_string_with_already_numbered_lines(self):
        steps = "1. Do this\nThen do that\n3. Already numbered"
        result = format_steps(steps)
        assert result == "1. Do this\n2. Then do that\n3. Already numbered"

    def test_empty_string_returns_empty(self):
        result = format_steps("")
        assert result == ""

    def test_non_list_non_string_returns_default(self):
        result = format_steps(42)
        assert result == "1. [Steps to reproduce not provided]"

    def test_none_returns_default(self):
        result = format_steps(None)
        assert result == "1. [Steps to reproduce not provided]"


class TestGetField:
    """Tests for get_field()."""

    def test_returns_value_when_present(self):
        data = {"key": "value"}
        assert get_field(data, "key") == "value"

    def test_returns_default_when_missing(self):
        data = {}
        assert get_field(data, "missing") == "[Not provided]"

    def test_returns_custom_default(self):
        data = {}
        assert get_field(data, "missing", "custom") == "custom"

    def test_returns_default_for_none_value(self):
        data = {"key": None}
        assert get_field(data, "key") == "[Not provided]"


class TestGenerateHackerOne:
    """Tests for generate_hackerone()."""

    def test_formats_template_with_vuln_meta(self):
        data = {
            "title": "SQL Injection on /api",
            "summary": "A SQL injection vulnerability",
            "attacker_achieves": "Extract database contents",
            "worst_case": "Full database compromise",
            "steps": "Test",
            "poc": "1=1",
            "root_cause": "No parameterization",
            "remediation": "Use prepared statements",
        }
        result = generate_hackerone(data, "sqli")
        assert "Cross-Site Scripting (XSS)" not in result
        assert "SQL Injection" in result
        assert "SQL Injection on /api" in result
        assert "Extract database contents" in result
        assert "SQL Injection" in result
        assert "Full database compromise" in result
        assert "Argus Bug Bounty Report" in result

    def test_uses_meta_default_cia_when_not_provided(self):
        data = {"title": "XSS", "summary": "XSS found", "steps": "Test", "poc": "<script>", "root_cause": "No encoding", "remediation": "Encode output"}
        result = generate_hackerone(data, "xss")
        assert "Confidentiality (session tokens)" in result

    def test_handles_unknown_vuln_type(self):
        data = {"title": "Unknown bug", "summary": "Something", "steps": "x", "poc": "x", "root_cause": "x", "remediation": "x"}
        result = generate_hackerone(data, "unknown_type")
        assert "UNKNOWN_TYPE" in result


class TestGenerateBugcrowd:
    """Tests for generate_bugcrowd()."""

    def test_formats_bugcrowd_template(self):
        data = {
            "summary": "XSS on login",
            "endpoint": "https://example.com/login",
            "attacker_achieves": "Session theft",
            "steps": "Navigate to URL",
            "poc": "<script>alert(1)</script>",
            "root_cause": "No output encoding on username field",
            "remediation": "Encode all user-controlled output",
            "worst_case": "Account takeover",
        }
        result = generate_bugcrowd(data, "xss")
        assert "Vulnerable Endpoint" in result
        assert "https://example.com/login" in result
        assert "Session theft" in result
        assert "CWE-79" in result

    def test_uses_cwe_reason_with_endpoint(self):
        data = {
            "summary": "Test",
            "endpoint": "https://example.com/api",
            "steps": "Step 1",
            "poc": "test",
            "remediation": "Fix it",
        }
        result = generate_bugcrowd(data, "sqli")
        assert "CWE-89" in result
        assert "example.com/api" in result or "affected resource" in result


class TestGenerateIntigriti:
    """Tests for generate_intigriti()."""

    def test_formats_intigriti_template(self):
        data = {
            "summary": "IDOR in user profile",
            "endpoint": "https://example.com/api/user/123",
            "attacker_achieves": "Access other users' data",
            "steps": "Change user ID",
            "poc": "GET /api/user/456",
            "root_cause": "No authorization check on user ID parameter",
            "remediation": "Verify user owns the requested resource",
        }
        result = generate_intigriti(data, "idor")
        assert "IDOR in user profile" in result
        assert "example.com/api/user/123" in result
        assert "Access other users' data" in result
        assert "Standard user account" in result


class TestGenerateYesWeHack:
    """Tests for generate_yeswehack()."""

    def test_assesses_cia_from_impact_text(self):
        data = {
            "summary": "SSRF",
            "endpoint": "https://example.com/fetch",
            "attacker_achieves": "Access internal services and data",
            "steps": "Step",
            "poc": "test",
            "root_cause": "No URL validation",
            "remediation": "Validate URLs",
            "worst_case": "Cloud credential theft",
            "cia_impact": "Confidentiality (data access), Integrity (data modification)",
        }
        result = generate_yeswehack(data, "ssrf")
        assert "Impacted" in result
        assert "Not impacted" in result

    def test_cia_defaults_to_not_impacted_when_no_impact_text(self):
        data = {
            "summary": "Test",
            "endpoint": "https://example.com",
            "attacker_achieves": "Something",
            "steps": "Step",
            "poc": "test",
            "root_cause": "x",
            "remediation": "x",
        }
        result = generate_yeswehack(data, "xss")
        assert "Not impacted" in result


class TestArgusFindingAdapter:
    """Tests for ArgusFindingAdapter.adapt()."""

    def test_adapt_converts_finding_to_report_schema(self):
        finding = {
            "type": "XSS",
            "severity": "HIGH",
            "confidence": 0.9,
            "endpoint": "https://example.com/search",
            "description": "Reflected XSS in search parameter",
            "source_tool": "nuclei",
            "evidence": {"payload": "<script>alert(1)</script>"},
            "remediation": "Encode output",
        }
        result = ArgusFindingAdapter.adapt(finding, "xss")
        assert result["title"] == "Xss on https://example.com/search"
        assert result["endpoint"] == "https://example.com/search"
        assert "Reflected XSS" in result["summary"]
        assert result["poc"] == "<script>alert(1)</script>"
        assert "Encode output" in result["remediation"]
        assert result["cia_impact"] == VULN_META["xss"]["default_cia"]

    def test_adapt_extracts_poc_from_evidence(self):
        finding = {
            "type": "SQL_INJECTION",
            "severity": "CRITICAL",
            "endpoint": "https://example.com/api",
            "evidence": {"request": "POST /api with payload: 1=1"},
        }
        result = ArgusFindingAdapter.adapt(finding, "sqli")
        assert result["poc"] == "POST /api with payload: 1=1"

    def test_adapt_uses_default_steps_when_none_provided(self):
        finding = {
            "type": "XSS",
            "severity": "MEDIUM",
            "endpoint": "https://example.com",
            "evidence": {},
        }
        result = ArgusFindingAdapter.adapt(finding, "xss")
        assert len(result["steps"]) == 3
        assert "Navigate to" in result["steps"][0]

    def test_adapt_uses_engagement_target_url(self):
        finding = {
            "type": "XSS",
            "severity": "HIGH",
            "endpoint": "https://example.com",
            "evidence": {},
        }
        engagement = {"target_url": "https://example.com"}
        result = ArgusFindingAdapter.adapt(finding, "xss", engagement)
        assert "example.com" in result["affected_scope"]

    def test_adapt_without_engagement_uses_application_users(self):
        finding = {
            "type": "XSS",
            "severity": "HIGH",
            "endpoint": "https://example.com",
            "evidence": {},
        }
        result = ArgusFindingAdapter.adapt(finding, "xss")
        assert result["affected_scope"] == "Application users"

    def test_adapt_extracts_poc_from_raw_request(self):
        finding = {
            "type": "SSRF",
            "severity": "HIGH",
            "endpoint": "https://example.com/fetch",
            "evidence": {"raw_request": "GET /fetch?url=internal"},
        }
        result = ArgusFindingAdapter.adapt(finding, "ssrf")
        assert result["poc"] == "GET /fetch?url=internal"

    def test_adapt_uses_evidence_response_as_fallback_poc(self):
        finding = {
            "type": "XSS",
            "severity": "MEDIUM",
            "endpoint": "https://example.com",
            "evidence": {"response": "HTTP/1.1 200 OK\n<script>alert(1)</script>"},
        }
        result = ArgusFindingAdapter.adapt(finding, "xss")
        assert "HTTP/1.1 200 OK" in result["poc"]


class TestBugBountyReportGenerator:
    """Tests for BugBountyReportGenerator."""

    def test_list_supported_platforms(self):
        generator = BugBountyReportGenerator()
        platforms = generator.list_supported_platforms()
        assert "hackerone" in platforms
        assert "bugcrowd" in platforms
        assert "intigriti" in platforms
        assert "yeswehack" in platforms

    def test_list_supported_types(self):
        generator = BugBountyReportGenerator()
        types = generator.list_supported_types()
        assert "xss" in types
        assert "sqli" in types
        assert "ssrf" in types

    def test_generate_raises_value_error_for_unsupported_platform(self):
        generator = BugBountyReportGenerator()
        with pytest.raises(ValueError, match="Unsupported platform"):
            generator.generate([], platform="unsupported")

    def test_generate_returns_empty_report_for_no_findings(self):
        generator = BugBountyReportGenerator()
        result = generator.generate([], platform="hackerone")
        assert "No findings found" in result

    def test_generate_returns_empty_report_when_all_filtered_out(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "LOW", "confidence": 0.9, "endpoint": "https://example.com"},
            {"type": "XSS", "severity": "MEDIUM", "confidence": 0.3, "endpoint": "https://example.com"},
        ]
        result = generator.generate(findings, platform="hackerone")
        assert "No reportable vulnerabilities" in result

    def test_generate_generates_report_for_valid_findings(self):
        generator = BugBountyReportGenerator()
        findings = [
            {
                "type": "XSS",
                "severity": "HIGH",
                "confidence": 0.9,
                "endpoint": "https://example.com/search",
                "description": "Reflected XSS",
                "evidence": {"payload": "<script>alert(1)</script>"},
                "source_tool": "nuclei",
                "remediation": "Encode output",
            }
        ]
        result = generator.generate(findings, platform="hackerone")
        assert "Argus Bug Bounty Report" in result
        assert "HACKERONE" in result
        assert "Reflected XSS" in result

    def test_generate_includes_engagement_target_in_header(self):
        generator = BugBountyReportGenerator()
        findings = [
            {
                "type": "XSS",
                "severity": "HIGH",
                "confidence": 0.9,
                "endpoint": "https://example.com",
                "evidence": {"payload": "x"},
            }
        ]
        result = generator.generate(findings, platform="bugcrowd", engagement={"target_url": "https://example.com"})
        assert "https://example.com" in result

    def test_generate_with_empty_findings_list_and_engagement(self):
        generator = BugBountyReportGenerator()
        result = generator.generate([], platform="intigriti", engagement={"target_url": "https://test.com"})
        assert "No findings found" in result


class TestFilterFindings:
    """Tests for BugBountyReportGenerator._filter_findings()."""

    def test_filters_by_false_positive(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9, "false_positive": True},
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9},
        ]
        result = generator._filter_findings(findings, min_confidence=0.5)
        assert len(result) == 1

    def test_filters_by_false_positive_assessment_verdict(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9, "fp_assessment": {"verdict": "false_positive"}},
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9},
        ]
        result = generator._filter_findings(findings, min_confidence=0.5)
        assert len(result) == 1

    def test_filters_by_severity(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "LOW", "confidence": 0.9},
            {"type": "XSS", "severity": "INFO", "confidence": 0.9},
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9},
        ]
        result = generator._filter_findings(findings, min_confidence=0.5)
        assert len(result) == 1

    def test_filters_by_confidence_threshold(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "HIGH", "confidence": 0.5},
            {"type": "XSS", "severity": "HIGH", "confidence": 0.8},
        ]
        result = generator._filter_findings(findings, min_confidence=0.65)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.8

    def test_handles_missing_severity(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "confidence": 0.9},
        ]
        result = generator._filter_findings(findings, min_confidence=0.5)
        assert len(result) == 0

    def test_handles_non_dict_fp_assessment(self):
        generator = BugBountyReportGenerator()
        findings = [
            {"type": "XSS", "severity": "HIGH", "confidence": 0.9, "fp_assessment": "string_value"},
        ]
        result = generator._filter_findings(findings, min_confidence=0.5)
        assert len(result) == 1


class TestMapType:
    """Tests for BugBountyReportGenerator._map_type()."""

    def test_maps_known_types(self):
        generator = BugBountyReportGenerator()
        assert generator._map_type({"type": "XSS"}) == "xss"
        assert generator._map_type({"type": "REFLECTED_XSS"}) == "xss"
        assert generator._map_type({"type": "SQL_INJECTION"}) == "sqli"
        assert generator._map_type({"type": "SSRF"}) == "ssrf"
        assert generator._map_type({"type": "RCE"}) == "rce"

    def test_falls_back_to_api_graphql(self):
        generator = BugBountyReportGenerator()
        result = generator._map_type({"type": "UNKNOWN_TYPE"})
        assert result == "api-graphql"

    def test_falls_back_to_tag_based_mapping(self):
        generator = BugBountyReportGenerator()
        result = generator._map_type({"type": "UNKNOWN_TYPE", "tags": ["XSS"]})
        assert result == "xss"

    def test_ignores_tags_when_direct_match_exists(self):
        generator = BugBountyReportGenerator()
        result = generator._map_type({"type": "XSS", "tags": ["sqli"]})
        assert result == "xss"

    def test_handles_missing_type(self):
        generator = BugBountyReportGenerator()
        result = generator._map_type({})
        assert result == "api-graphql"

    def test_handles_non_list_tags(self):
        generator = BugBountyReportGenerator()
        result = generator._map_type({"type": "UNKNOWN_TYPE", "tags": "not_a_list"})
        assert result == "api-graphql"
