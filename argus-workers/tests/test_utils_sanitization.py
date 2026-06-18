"""Tests for utils/sanitization.py — input sanitization utilities."""

from utils.sanitization import (
    check_for_dangerous_content,
    sanitize_evidence,
    sanitize_string,
    strip_dangerous_tags,
)


class TestSanitizeString:
    def test_escapes_html(self):
        assert (
            sanitize_string("<script>alert(1)</script>")
            == "&lt;script&gt;alert(1)&lt;/script&gt;"
        )

    def test_escapes_quotes(self):
        result = sanitize_string('say "hello"')
        assert "&quot;" in result or "&#x27;" in result

    def test_none_returns_empty(self):
        assert sanitize_string("") == ""

    def test_safe_string_passes_through(self):
        assert sanitize_string("hello world") == "hello world"


class TestSanitizeEvidence:
    def test_sanitizes_string_values(self):
        evidence = {"payload": "<script>alert(1)</script>"}
        result = sanitize_evidence(evidence)
        assert result["payload"] != evidence["payload"]
        assert "&lt;" in result["payload"]

    def test_none_returns_empty_dict(self):
        assert sanitize_evidence({}) == {}
        assert sanitize_evidence(None) == {}

    def test_recursive_dicts(self):
        evidence = {"nested": {"payload": "<script>"}}
        result = sanitize_evidence(evidence)
        assert "&lt;" in result["nested"]["payload"]

    def test_lists_are_sanitized(self):
        evidence = {"items": ["<script>", "safe"]}
        result = sanitize_evidence(evidence)
        assert "&lt;" in result["items"][0]
        assert result["items"][1] == "safe"

    def test_non_string_values_preserved(self):
        evidence = {"number": 42, "flag": True, "none": None}
        result = sanitize_evidence(evidence)
        assert result["number"] == 42
        assert result["flag"] is True
        assert result["none"] is None


class TestCheckForDangerousContent:
    def test_detects_script_tag(self):
        results = check_for_dangerous_content("<script>alert(1)</script>")
        assert len(results) > 0
        assert any("script" in r.lower() for r in results)

    def test_detects_javascript_protocol(self):
        results = check_for_dangerous_content("javascript:alert(1)")
        assert any("javascript" in r.lower() for r in results)

    def test_detects_event_handler(self):
        results = check_for_dangerous_content('<div onload="alert(1)">')
        assert any("event" in r.lower() for r in results)

    def test_safe_string_returns_empty(self):
        results = check_for_dangerous_content("hello world")
        assert results == []


class TestStripDangerousTags:
    def test_removes_script_tags(self):
        result = strip_dangerous_tags("<script>alert(1)</script>")
        assert "alert" not in result

    def test_removes_iframe(self):
        result = strip_dangerous_tags('<iframe src="http://evil.com"></iframe>')
        assert result != '<iframe src="http://evil.com"></iframe>'

    def test_safe_string_preserved(self):
        result = strip_dangerous_tags("hello world")
        assert result == "hello world"
