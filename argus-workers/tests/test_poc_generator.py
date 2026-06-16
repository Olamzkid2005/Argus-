"""Tests for the PoC Generator."""

from poc_generator import PoCGenerator


class TestPoCShouldGenerate:
    def test_low_severity_skipped(self):
        gen = PoCGenerator()
        should, reason = gen.should_generate({
            "severity": "LOW", "confidence": 0.95,
        })
        assert should is False
        assert "severity" in reason.lower()

    def test_low_confidence_skipped(self):
        gen = PoCGenerator()
        should, reason = gen.should_generate({
            "severity": "HIGH", "confidence": 0.50,
        })
        assert should is False
        assert "confidence" in reason.lower()

    def test_high_severity_high_confidence_generates(self):
        gen = PoCGenerator()
        should, reason = gen.should_generate({
            "severity": "CRITICAL", "confidence": 0.90,
        })
        assert should is True
        assert reason == ""

    def test_invalid_confidence_returns_false(self):
        gen = PoCGenerator()
        should, reason = gen.should_generate({
            "severity": "HIGH", "confidence": "invalid",
        })
        assert should is False

    def test_info_severity_skipped(self):
        gen = PoCGenerator()
        should, reason = gen.should_generate({
            "severity": "INFO", "confidence": 1.0,
        })
        assert should is False
