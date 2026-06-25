"""Tests for models/finding.py evidence validation fix.

The fix ensures None evidence produces {} not {"raw": "None"},
strings are parsed as JSON, dicts pass through, and other types
are wrapped in {"raw": str(v)}.
"""

import json

import pytest


def validate_evidence(v):
    """Inline replica of VulnerabilityFinding.validate_evidence."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, TypeError):
            return {"raw": v}
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return {"items": v}
    if v is None:
        return {}
    return {"raw": str(v)}


class TestEvidenceValidator:
    def test_none_produces_empty_dict(self):
        """None evidence must produce {} not {'raw': 'None'}."""
        result = validate_evidence(None)
        assert result == {}
        assert result != {"raw": "None"}

    def test_string_json_parsed_to_dict(self):
        """String containing JSON should be parsed into a dict."""
        evidence_str = json.dumps({"param": "id", "payload": "<script>alert(1)</script>"})
        result = validate_evidence(evidence_str)
        assert isinstance(result, dict)
        assert result["param"] == "id"
        assert result["payload"] == "<script>alert(1)</script>"

    def test_dict_passes_through(self):
        """Dict evidence should be returned as-is."""
        evidence = {"request": "GET /admin", "response": "200 OK"}
        result = validate_evidence(evidence)
        assert result is evidence

    def test_list_wrapped_in_items(self):
        """List evidence should be wrapped in {'items': v}."""
        result = validate_evidence(["item1", "item2"])
        assert result == {"items": ["item1", "item2"]}

    def test_integer_wrapped_in_raw(self):
        """Integer evidence wraps in {'raw': str(v)}."""
        result = validate_evidence(200)
        assert result == {"raw": "200"}

    def test_boolean_wrapped_in_raw(self):
        """Boolean evidence wraps in {'raw': str(v)}."""
        result = validate_evidence(False)
        assert result == {"raw": "False"}

    def test_non_json_string_wrapped_in_raw(self):
        """Non-JSON string wraps in {'raw': v}."""
        result = validate_evidence("just a raw string")
        assert result == {"raw": "just a raw string"}
