"""Placeholder reproduction is explicitly unsupported (Stage 4.1 item 3).

Every strategy in `ReproductionEngine` returns canned evidence and a "requires
a live HTTP client" note: none of them replays the attack. They must say so
structurally (`supported: False`) rather than look like a completed, negative
verification, so downstream promotion records the finding as unsupported.
"""

import pytest

from tools.verification.reproduction_engine import ReproductionEngine


class TestReproductionEngine:
    """Tests for the ReproductionEngine class."""

    def test_instantiation(self):
        """Class requires constructor args."""
        instance = ReproductionEngine()
        assert instance is not None

    def test_str_repr(self):
        """String and repr work on instantiated object."""
        instance = ReproductionEngine()
        assert isinstance(str(instance), str)
        assert isinstance(repr(instance), str)


class TestPlaceholderStrategiesAreUnsupported:
    @pytest.mark.parametrize(
        "finding_type",
        [
            "SQL_INJECTION",
            "XSS",
            "CSRF",
            "COMMAND_INJECTION",
            "SSRF",
            "SOMETHING_ELSE",
        ],
    )
    def test_every_strategy_reports_unsupported(self, finding_type):
        engine = ReproductionEngine()

        result = engine.reproduce(
            {"type": finding_type, "endpoint": "https://example.com"},
            "https://example.com",
        )

        assert result["supported"] is False
        assert result["reproduced"] is False
        assert result["error"], "an unsupported strategy must say why it did not run"

    def test_no_strategy_ever_claims_a_reproduction(self):
        """A canned payload list is not an observation of the exploit."""
        engine = ReproductionEngine()
        findings = [
            {"type": t, "endpoint": "https://example.com"}
            for t in ("SQL_INJECTION", "XSS", "CSRF", "RCE", "SSRF", "LFI", "IDOR")
        ]

        results = [engine.reproduce(f, "https://example.com") for f in findings]

        assert all(r["reproduced"] is False and r["supported"] is False for r in results)

    def test_an_unknown_type_is_unsupported_too(self):
        engine = ReproductionEngine()

        result = engine.reproduce({"type": "BRAND_NEW"}, "https://example.com")

        assert result["supported"] is False
