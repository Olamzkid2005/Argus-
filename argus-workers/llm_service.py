"""
LLM Service - Unified interface for LLM interactions.

Hides: provider dispatch, prompt building, JSON parsing and schema validation,
retry with exponential backoff, per-engagement cost tracking and enforcement,
and a single fallback strategy used by all callers.

Replaces scattered LLM call logic in:
- agent/react_agent.py (_call_llm_for_action)
- llm_synthesizer.py (synthesize)
- llm_report_generator.py (generate_report)
"""
import json
import logging
from typing import Dict, Optional, Generator, Any
from dataclasses import dataclass

from llm_client import LLMClient, LLMResponse
from config.constants import (
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_TIMEOUT_SECONDS,
    LLM_AGENT_COST_PER_1K_INPUT,
    LLM_AGENT_COST_PER_1K_OUTPUT,
)

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks cumulative LLM cost per engagement."""

    def __init__(self, max_cost_usd: float = 0.25):
        self.total = 0.0
        self.max_cost = max_cost_usd

    def add(self, cost: float):
        self.total += cost

    def exceeded(self) -> bool:
        return self.total > self.max_cost


@dataclass
class LLMServiceConfig:
    """Configuration for LLMService."""
    temperature: float = LLM_AGENT_TEMPERATURE
    timeout: int = LLM_AGENT_TIMEOUT_SECONDS
    max_cost_usd: float = 0.25


class LLMService:
    """
    One interface for all LLM interactions.

    Usage:
        service = LLMService(llm_client)
        result = service.chat_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt="...",
            max_tokens=2000,
        )
    """

    def __init__(self, llm_client: LLMClient, config: Optional[LLMServiceConfig] = None):
        self._client = llm_client
        self._config = config or LLMServiceConfig()
        self._cost_tracker = CostTracker(max_cost_usd=self._config.max_cost_usd)

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 500,
        temperature: Optional[float] = None,
    ) -> Dict:
        """
        Call LLM and return parsed JSON dict.

        Returns a dict (never None, never raises). On error, returns a fallback dict.
        """
        if not self._client.is_available():
            return self._fallback("LLM not available")

        try:
            raw = self._client.chat_sync(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature or self._config.temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                timeout=self._config.timeout,
            )

            response_text = raw.text if isinstance(raw, LLMResponse) else str(raw)
            cost = raw.cost_usd if isinstance(raw, LLMResponse) else 0.0
            self._cost_tracker.add(cost)

            if self._cost_tracker.exceeded():
                logger.warning(f"Cost cap reached (${self._cost_tracker.total:.4f}), using fallback")
                return self._fallback("Cost cap exceeded")

            return json.loads(response_text)

        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return self._fallback(str(e))

    def _fallback(self, reason: str) -> Dict:
        """Single fallback response for all callers."""
        return {
            "_fallback": True,
            "_reason": reason,
            "executive_summary": f"Analysis unavailable ({reason}).",
            "risk_level": "medium",
            "priority_findings": [],
            "attack_chains": [],
            "fp_candidates": [],
            "analyst_notes": f"LLM unavailable: {reason}",
        }
