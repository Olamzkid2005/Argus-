"""Tests for LLM Agent constants."""
import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.constants import (
    LLM_AGENT_ENABLED,
    LLM_AGENT_MODEL,
    LLM_AGENT_MAX_ITERATIONS,
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_MAX_TOKENS_PLAN,
    LLM_AGENT_MAX_TOKENS_SYNTH,
    LLM_AGENT_MAX_TOKENS_REPORT,
    LLM_AGENT_CONTEXT_MAX_TOKENS,
    LLM_AGENT_MAX_COST_USD,
    LLM_AGENT_COST_PER_1K_INPUT,
    LLM_AGENT_COST_PER_1K_OUTPUT,
    LLM_AGENT_TIMEOUT_SECONDS,
    LLM_AGENT_MAX_RETRIES,
    LLM_AGENT_ZERO_FINDING_STOP,
)


class TestAgentConstants:
    def test_constants_defaults_exist(self):
        """All new constants should exist and be correct types."""
        assert isinstance(LLM_AGENT_ENABLED, bool)
        assert isinstance(LLM_AGENT_MODEL, str)
        assert isinstance(LLM_AGENT_MAX_ITERATIONS, int)
        assert isinstance(LLM_AGENT_TEMPERATURE, float)
        assert isinstance(LLM_AGENT_MAX_TOKENS_PLAN, int)
        assert isinstance(LLM_AGENT_MAX_TOKENS_SYNTH, int)
        assert isinstance(LLM_AGENT_MAX_TOKENS_REPORT, int)
        assert isinstance(LLM_AGENT_CONTEXT_MAX_TOKENS, int)
        assert isinstance(LLM_AGENT_MAX_COST_USD, float)
        assert isinstance(LLM_AGENT_COST_PER_1K_INPUT, float)
        assert isinstance(LLM_AGENT_COST_PER_1K_OUTPUT, float)
        assert isinstance(LLM_AGENT_TIMEOUT_SECONDS, int)
        assert isinstance(LLM_AGENT_MAX_RETRIES, int)
        assert isinstance(LLM_AGENT_ZERO_FINDING_STOP, int)

    def test_agent_model_default(self):
        """Default model should be gpt-4o-mini."""
        assert LLM_AGENT_MODEL == "gpt-4o-mini"

    def test_cost_constants_non_negative(self):
        """All cost constants should be non-negative."""
        assert LLM_AGENT_COST_PER_1K_INPUT >= 0
        assert LLM_AGENT_COST_PER_1K_OUTPUT >= 0
        assert LLM_AGENT_MAX_COST_USD > 0

    def test_agent_max_iterations_reasonable(self):
        """Max iterations should be in a reasonable range."""
        assert 1 <= LLM_AGENT_MAX_ITERATIONS <= 50
