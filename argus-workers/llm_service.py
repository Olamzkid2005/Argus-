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
import time as _time
from dataclasses import dataclass

from config.constants import (
    LLM_AGENT_TEMPERATURE,
    LLM_AGENT_TIMEOUT_SECONDS,
)
from llm_client import LLMClient, LLMResponse

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

    def __init__(self, llm_client: LLMClient, config: LLMServiceConfig | None = None,
                 cost_tracker: "CostTracker" = None):
        self._client = llm_client
        self._config = config or LLMServiceConfig()
        self._cost_tracker = cost_tracker or CostTracker(max_cost_usd=self._config.max_cost_usd)

    def is_available(self) -> bool:
        """Check if the underlying LLM client is available for use."""
        return self._client is not None and self._client.is_available()

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 500,
        temperature: float | None = None,
    ) -> dict | list:
        """
        Call LLM and return parsed JSON dict.

        Returns a dict (never None, never raises). On error, returns a fallback dict.
        """
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("llm_service")
        slog.llm_start(self._client.model if hasattr(self._client, 'model') else 'unknown', system_prompt[:60])
        start = _time.time()

        if not self._client.is_available():
            slog.llm_result("LLM not available")
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
                logger.warning(
                    f"Cost cap reached (${self._cost_tracker.total:.4f}), using fallback"
                )
                return self._fallback("Cost cap exceeded")

            try:
                parsed = json.loads(response_text)
                duration_ms = int((_time.time() - start) * 1000)
                tokens = raw.output_tokens if isinstance(raw, LLMResponse) else 0
                slog.llm_complete(self._client.model if hasattr(self._client, 'model') else 'unknown', duration_ms=duration_ms, tokens=tokens, cost=cost)
                # Validate that the response is a dict or list (callers expect structured data)
                if not isinstance(parsed, (dict, list)):
                    logger.warning("LLM returned unexpected type %s, using fallback", type(parsed).__name__)
                    return self._fallback("Unexpected response type (expected dict or list)")
                return parsed
            except json.JSONDecodeError as e:
                logger.warning("LLM returned non-JSON response (%.200r...), using fallback: %s", response_text, e)
                return self._fallback(f"JSON parse error: {e}")

        except Exception as e:
            slog.llm_result(f"Failed: {e}")
            logger.warning(f"LLM call failed: {e}")
            return self._fallback(str(e))

    def _fallback(self, reason: str) -> dict:
        """Single fallback response for all callers."""
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("llm_service")
        slog.warn(f"Fallback: {reason}")
        logger.warning("LLM service using FALLBACK response — reason: %s. "
                       "All downstream analysis will be placeholder data.", reason)
        return {
            "_fallback": True,
            "_reason": reason,
            "_error": True,  # signal to callers that this is NOT real analysis
            "executive_summary": f"Analysis unavailable ({reason}). This is an automated fallback — do not treat as real analysis.",
            "risk_level": "unknown",  # unknown, not medium — don't mask failures
            "priority_findings": [],
            "attack_chains": [],
            "fp_candidates": [],
            "analyst_notes": f"LLM unavailable: {reason}",
        }
