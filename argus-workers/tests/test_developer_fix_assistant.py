"""Tests for developer_fix_assistant.py

Covers:
  - DeveloperFixAssistant init
  - should_generate severity filtering
  - generate with/without llm service
  - Budget exhaustion handling
  - LLM fallback handling
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from developer_fix_assistant import DeveloperFixAssistant


class TestDeveloperFixAssistant:
    """Tests for DeveloperFixAssistant."""

    @pytest.fixture
    def assistant(self):
        return DeveloperFixAssistant()

    def test_init(self, assistant):
        assert assistant.llm_client is None

    def test_init_with_client(self):
        mock_client = MagicMock()
        assistant = DeveloperFixAssistant(llm_client=mock_client)
        assert assistant.llm_client is mock_client

    def test_should_generate_critical(self, assistant):
        assert assistant.should_generate({"severity": "CRITICAL"}) is True

    def test_should_generate_high(self, assistant):
        assert assistant.should_generate({"severity": "HIGH"}) is True

    def test_should_generate_medium(self, assistant):
        assert assistant.should_generate({"severity": "MEDIUM"}) is True

    def test_should_generate_low(self, assistant):
        assert assistant.should_generate({"severity": "LOW"}) is False

    def test_should_generate_info(self, assistant):
        assert assistant.should_generate({"severity": "INFO"}) is False

    def test_should_generate_missing_severity(self, assistant):
        assert assistant.should_generate({}) is False

    def test_generate_no_llm(self, assistant):
        result = assistant.generate(
            finding={"type": "XSS", "severity": "HIGH"},
            tech_stack=["python", "flask"],
        )
        assert result is None

    def test_generate_with_llm(self, assistant):
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_json.return_value = {
            "vulnerable_pattern": "<code>",
            "fixed_pattern": "<fixed>",
            "explanation": "This fixes it",
            "_fallback": False,
        }
        result = assistant.generate(
            finding={"type": "XSS", "severity": "HIGH", "endpoint": "/search"},
            tech_stack=["python", "flask"],
            llm_service=mock_llm,
        )
        assert result is not None
        assert "generated_at" in result
        assert result["tech_stack"] == ["python", "flask"]

    def test_generate_llm_fallback(self, assistant):
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_llm.chat_json.return_value = {"_fallback": True}
        result = assistant.generate(
            finding={"type": "XSS", "severity": "HIGH"},
            tech_stack=[],
            llm_service=mock_llm,
        )
        assert result is None

    def test_generate_budget_exhausted(self, assistant):
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True
        mock_cost = MagicMock()
        mock_cost.has_remaining_budget.return_value = False
        result = assistant.generate(
            finding={"type": "XSS", "severity": "HIGH"},
            tech_stack=[],
            llm_service=mock_llm,
            cost_tracker=mock_cost,
        )
        assert result is None

    def test_generate_llm_not_available(self, assistant):
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False
        result = assistant.generate(
            finding={"type": "XSS", "severity": "HIGH"},
            tech_stack=[],
            llm_service=mock_llm,
        )
        assert result is None
