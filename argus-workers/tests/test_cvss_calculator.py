"""Tests for cvss_calculator.py

Covers:
  - estimate_cvss for all finding types
  - Severity multipliers
  - Evidence adjustments
  - Edge cases: empty strings, None, unknown types
  - Score capping at 10.0
  - get_cvss_label with and without CVE
  - Rounding precision
"""

from __future__ import annotations

import pytest

from cvss_calculator import (
    EVIDENCE_ADJUSTMENTS,
    SEVERITY_MULTIPLIERS,
    TYPE_BASE_SCORES,
    estimate_cvss,
    get_cvss_label,
)


class TestTypeBaseScores:
    """Verify the base score lookup table."""

    def test_critical_types_have_high_scores(self):
        assert TYPE_BASE_SCORES["SQL_INJECTION"] == 9.8
        assert TYPE_BASE_SCORES["COMMAND_INJECTION"] == 9.8
        assert TYPE_BASE_SCORES["SSTI"] == 9.8
        assert TYPE_BASE_SCORES["SSRF"] == 9.3

    def test_xss_variants(self):
        assert TYPE_BASE_SCORES["XSS"] == 6.1
        assert TYPE_BASE_SCORES["STORED_XSS"] == 8.8
        assert TYPE_BASE_SCORES["DOM_XSS"] == 6.1
        assert TYPE_BASE_SCORES["REFLECTED_XSS"] == 6.1

    def test_info_types_have_low_scores(self):
        assert TYPE_BASE_SCORES["TECHNOLOGY_DETECTION"] == 2.5
        assert TYPE_BASE_SCORES["ENDPOINT_DISCOVERY"] == 2.5
        assert TYPE_BASE_SCORES["MISSING_SECURITY_HEADERS"] == 3.7

    def test_all_expected_keys_present(self):
        required_keys = [
            "SQL_INJECTION", "XSS", "SSRF", "SSTI", "XXE",
            "CSRF", "IDOR", "OPEN_REDIRECT", "PATH_TRAVERSAL",
            "EXPOSED_SECRET", "DEPENDENCY_VULNERABILITY",
        ]
        for key in required_keys:
            assert key in TYPE_BASE_SCORES, f"Missing base score for {key}"


class TestEstimateCVSS:
    """Tests for estimate_cvss function."""

    def test_sql_injection_critical_verified(self):
        score = estimate_cvss("SQL_INJECTION", "CRITICAL", "verified")
        assert score == 9.8  # 9.8 * 1.0 * 1.0 = 9.8

    def test_xss_high_moderate(self):
        score = estimate_cvss("XSS", "HIGH", "moderate")
        expected = round(min(6.1 * 0.9 * 0.85, 10.0), 1)
        assert score == expected
        assert score < 6.1  # Reduced by severity and evidence

    def test_info_low_weak(self):
        score = estimate_cvss("TECHNOLOGY_DETECTION", "INFO", "weak")
        expected = round(min(2.5 * 0.3 * 0.7, 10.0), 1)
        assert score == expected
        assert score < 1.0

    def test_score_capped_at_10(self):
        score = estimate_cvss("SQL_INJECTION", "CRITICAL", "verified")
        assert score <= 10.0

    def test_unknown_type_defaults_to_5(self):
        score = estimate_cvss("UNKNOWN_TYPE", "MEDIUM", "moderate")
        expected = round(min(5.0 * 0.7 * 0.85, 10.0), 1)
        assert score == expected

    def test_empty_type(self):
        score = estimate_cvss("", "MEDIUM", "moderate")
        assert score > 0

    def test_none_type(self):
        score = estimate_cvss(None, "MEDIUM", "moderate")
        assert score > 0

    def test_empty_severity_defaults_to_info(self):
        score1 = estimate_cvss("XSS", "", "moderate")
        score2 = estimate_cvss("XSS", "INFO", "moderate")
        assert score1 == score2

    def test_none_severity_defaults_to_info(self):
        score1 = estimate_cvss("XSS", None, "moderate")
        score2 = estimate_cvss("XSS", "INFO", "moderate")
        assert score1 == score2

    def test_empty_evidence_defaults_to_moderate(self):
        score1 = estimate_cvss("XSS", "MEDIUM", "")
        score2 = estimate_cvss("XSS", "MEDIUM", "moderate")
        assert score1 == score2

    def test_none_evidence_defaults_to_moderate(self):
        score1 = estimate_cvss("XSS", "MEDIUM", None)
        score2 = estimate_cvss("XSS", "MEDIUM", "moderate")
        assert score1 == score2

    def test_case_insensitive_type(self):
        score_upper = estimate_cvss("SQL_INJECTION", "CRITICAL", "verified")
        score_lower = estimate_cvss("sql_injection", "critical", "verified")
        assert score_upper == score_lower

    def test_rounding_to_one_decimal(self):
        score = estimate_cvss("SQL_INJECTION", "HIGH", "weak")
        # 9.8 * 0.9 * 0.7 = 6.174 → round to 6.2
        assert score == 6.2

    @pytest.mark.parametrize("severity,multiplier", [
        ("CRITICAL", 1.0),
        ("HIGH", 0.9),
        ("MEDIUM", 0.7),
        ("LOW", 0.5),
        ("INFO", 0.3),
    ])
    def test_severity_multipliers(self, severity, multiplier):
        assert SEVERITY_MULTIPLIERS[severity] == multiplier

    @pytest.mark.parametrize("evidence,adjustment", [
        ("verified", 1.0),
        ("strong", 0.95),
        ("moderate", 0.85),
        ("weak", 0.7),
        ("none", 0.6),
    ])
    def test_evidence_adjustments(self, evidence, adjustment):
        assert EVIDENCE_ADJUSTMENTS[evidence] == adjustment

    def test_unknown_severity_defaults_to_medium(self):
        score = estimate_cvss("XSS", "UNKNOWN_SEVERITY", "moderate")
        score_medium = estimate_cvss("XSS", "MEDIUM", "moderate")
        assert score == score_medium

    def test_unknown_evidence_defaults_to_medium(self):
        score = estimate_cvss("XSS", "MEDIUM", "unknown_evidence")
        score_medium = estimate_cvss("XSS", "MEDIUM", "moderate")
        assert score == score_medium

    @pytest.mark.parametrize("finding_type,expected_approx", [
        ("SQL_INJECTION", 9.8),
        ("COMMAND_INJECTION", 9.8),
        ("SSTI", 9.8),
        ("SSRF", 9.3),
        ("XXE", 8.2),
        ("STORED_XSS", 8.8),
        ("XSS", 6.1),
        ("CSRF", 6.5),
        ("IDOR", 6.5),
        ("OPEN_REDIRECT", 6.1),
        ("PATH_TRAVERSAL", 7.5),
        ("EXPOSED_SECRET", 8.8),
        ("TECHNOLOGY_DETECTION", 2.5),
    ])
    def test_known_types_with_critical_severity(self, finding_type, expected_approx):
        score = estimate_cvss(finding_type, "CRITICAL", "verified")
        assert score == expected_approx


class TestGetCVSSLabel:
    """Tests for get_cvss_label function."""

    def test_with_cve(self):
        assert get_cvss_label(has_cve=True) == "CVSS (NVD)"

    def test_without_cve(self):
        assert get_cvss_label(has_cve=False) == "Estimated CVSS"

    def test_default_no_cve(self):
        assert get_cvss_label() == "Estimated CVSS"
