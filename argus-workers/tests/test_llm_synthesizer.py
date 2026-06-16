"""Tests for llm_synthesizer.py

Covers:
  - LLMSynthesizer init
  - synthesize with scored findings and attack paths
  - synthesize with recon_context
  - synthesize fallback handling
  - synthesize with no findings
"""

from __future__ import annotations

from unittest.mock import MagicMock

from llm_synthesizer import LLMSynthesizer


class TestLLMSynthesizer:
    """Tests for LLMSynthesizer."""

    def test_init(self):
        mock_llm = MagicMock()
        synth = LLMSynthesizer(mock_llm)
        assert synth._llm is mock_llm

    def test_synthesize_returns_result(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {
            "risk_level": "high",
            "executive_summary": "Test summary",
            "_fallback": False,
        }
        synth = LLMSynthesizer(mock_llm)
        result = synth.synthesize(
            scored_findings=[{"type": "XSS", "severity": "HIGH"}],
            attack_paths=[],
        )
        assert result["risk_level"] == "high"
        mock_llm.chat_json.assert_called_once()

    def test_synthesize_with_recon_context(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {"risk_level": "medium", "_fallback": False}
        mock_recon = MagicMock()
        mock_recon.to_llm_summary.return_value = "Target: example.com"
        synth = LLMSynthesizer(mock_llm)
        result = synth.synthesize(
            scored_findings=[],
            attack_paths=[],
            recon_context=mock_recon,
        )
        assert result["risk_level"] == "medium"

    def test_synthesize_fallback(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = {"_fallback": True}
        synth = LLMSynthesizer(mock_llm)
        result = synth.synthesize([], [])
        assert result.get("_synthesis_fallback") is True

    def test_synthesize_returns_none_fallback(self):
        mock_llm = MagicMock()
        mock_llm.chat_json.return_value = None
        synth = LLMSynthesizer(mock_llm)
        result = synth.synthesize([], [])
        assert result.get("_synthesis_fallback") is True
