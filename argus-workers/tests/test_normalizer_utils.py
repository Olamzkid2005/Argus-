"""Tests for orchestrator_pkg.normalizer_utils — Category: function

Focuses on title handling. The Finding model has no title field, so
normalize_finding is the single point where a parser's title must be carried
through (or a readable one derived), otherwise findings reach the database and
reports with an empty title.
"""

from types import SimpleNamespace

import pytest

from orchestrator_pkg.normalizer_utils import normalize_finding


def _normalizer(finding_type="OPEN_PORT", severity="MEDIUM"):
    """Build a stand-in FindingNormalizer returning a Finding-like object."""

    class _Stub:
        def normalize(self, raw_finding, tool):
            return SimpleNamespace(
                type=finding_type,
                severity=SimpleNamespace(value=severity),
                endpoint="127.0.0.1:8080",
                evidence={"raw": True},
                confidence=0.7,
            )

    return _Stub()


class TestNormalizeFinding:
    """Tests for the normalize_finding function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            normalize_finding()

    def test_keeps_the_standard_keys(self):
        result = normalize_finding(_normalizer(), {"title": "Ignored"}, "naabu")
        assert result is not None
        assert result["type"] == "OPEN_PORT"
        assert result["severity"] == "MEDIUM"
        assert result["endpoint"] == "127.0.0.1:8080"
        assert result["confidence"] == 0.7
        assert result["source_tool"] == "naabu"

    def test_preserves_a_parser_supplied_title(self):
        result = normalize_finding(
            _normalizer(finding_type="SQL_INJECTION"),
            {"title": "Boolean-based blind SQL injection"},
            "sqlmap",
        )
        assert result["title"] == "Boolean-based blind SQL injection"

    def test_derives_a_title_when_the_parser_supplies_none(self):
        """Regression: low-level parsers (naabu, katana) report no title."""
        result = normalize_finding(_normalizer(finding_type="OPEN_PORT"), {}, "naabu")
        assert result["title"] == "Open port detected"

    def test_humanizes_an_unknown_type(self):
        result = normalize_finding(
            _normalizer(finding_type="SOME_NEW_FINDING"), {}, "custom"
        )
        assert result["title"] == "Some new finding"

    @pytest.mark.parametrize("blank", ["", "   ", None])
    def test_blank_titles_fall_back_rather_than_persisting_empty(self, blank):
        result = normalize_finding(
            _normalizer(finding_type="CRAWLED_ENDPOINT"),
            {"title": blank},
            "katana",
        )
        assert result["title"] == "Endpoint discovered"

    def test_empty_type_still_yields_a_non_empty_title(self):
        result = normalize_finding(_normalizer(finding_type=""), {}, "unknown")
        assert result["title"].strip() != ""

    def test_returns_none_when_the_normalizer_raises(self):
        class _Broken:
            def normalize(self, raw_finding, tool):
                raise ValueError("boom")

        assert normalize_finding(_Broken(), {"title": "x"}, "naabu") is None
