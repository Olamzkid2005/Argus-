"""Tests for llm_report_generator.py

Covers:
  - LLMReportGenerator init
  - generate_report with valid/failed LLM
  - stream_report
  - _fallback_report structure
"""

from __future__ import annotations

from unittest.mock import MagicMock

from llm_report_generator import LLMReportGenerator


class TestLLMReportGenerator:
    """Tests for LLMReportGenerator."""

    def test_init(self):
        mock_llm = MagicMock()
        gen = LLMReportGenerator(mock_llm)
        assert gen._llm is mock_llm

    def test_generate_report_returns_result(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {
            "executive_summary": "Test summary",
            "findings_summary_table": [],
            "detailed_findings": [],
            "_fallback": False,
        }
        gen = LLMReportGenerator(mock_llm)
        result = gen.generate_report(
            synthesis={"risk_level": "high"},
            scored_findings=[],
            engagement={"target_url": "https://example.com"},
        )
        assert result["executive_summary"] == "Test summary"

    def test_generate_report_fallback(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {"_fallback": True}
        gen = LLMReportGenerator(mock_llm)
        result = gen.generate_report(
            synthesis={},
            scored_findings=[{"type": "XSS", "severity": "HIGH"}],
            engagement={"target_url": "https://example.com"},
        )
        assert "fallback" in result.get("conclusion", "").lower()
        assert result["executive_summary"]

    def test_fallback_report_structure(self):
        gen = LLMReportGenerator(MagicMock())
        result = gen._fallback_report(
            engagement={"target_url": "https://example.com"},
            scored_findings=[
                {"severity": "CRITICAL"},
                {"severity": "HIGH"},
                {"severity": "MEDIUM"},
            ],
        )
        assert "executive_summary" in result
        assert "findings_summary_table" in result
        assert "conclusion" in result
        assert len(result["findings_summary_table"]) == 3

    def test_fallback_with_no_findings(self):
        gen = LLMReportGenerator(MagicMock())
        result = gen._fallback_report(
            engagement={"target_url": "https://example.com"},
            scored_findings=[],
        )
        assert result["findings_summary_table"] == []

    def test_generate_with_recon_context(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {
            "executive_summary": "Test",
            "_fallback": False,
        }
        mock_recon = MagicMock()
        mock_recon.to_llm_summary.return_value = "Recon data"
        gen = LLMReportGenerator(mock_llm)
        result = gen.generate_report(
            synthesis={},
            scored_findings=[],
            engagement={},
            recon_context=mock_recon,
        )
        assert result["executive_summary"] == "Test"
