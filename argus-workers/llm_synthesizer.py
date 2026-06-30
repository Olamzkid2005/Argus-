"""
LLM Synthesizer - Uses LLM to preside over scored findings and produce structured analysis.

Separate from IntelligenceEngine (rule-based scoring). The LLM adds narrative
reasoning, attack chain identification, false positive analysis, and prioritization
on top of already-scored data.

Also provides a dedicated ``update_hypotheses()`` call — separate from
``synthesize()`` — so hypothesis updates can timeout independently and
fail without blocking the rest of the pipeline.
"""

import logging
import time as _time
from typing import Any

from agent.agent_prompts import (
    SYNTHESIS_SYSTEM_PROMPT,
    build_synthesis_prompt,
)
from config.constants import LLM_AGENT_MAX_TOKENS_SYNTH
from models.hypothesis import validate_hypothesis_update

logger = logging.getLogger(__name__)


_HYPOTHESIS_UPDATE_SYSTEM_PROMPT = """
You are an automated penetration testing analyst evaluating hypotheses.

You receive:
  - A list of current hypotheses with descriptions, confidence, and status
  - Recent observations (tool results, new findings, synthesis summary)

For each hypothesis, decide:
  1. Status: CONFIRMED, REJECTED, or UNVERIFIED (keep as is)
  2. Confidence: Adjust based on new evidence (0.0 - 1.0)
  3. Reasoning: Brief justification

Rules:
  - CONFIRMED if strong evidence supports the hypothesis (e.g., tool produced
    findings matching the expected vulnerability type)
  - REJECTED if strong evidence contradicts it (e.g., tool ran cleanly with
    no findings, and it was a capable verifier)
  - UNVERIFIED if insufficient evidence either way
  - Raise confidence when evidence supports, lower when evidence contradicts
  - Be conservative — prefer UNVERIFIED over premature CONFIRM/REJECT

Return a JSON array of update objects, one per hypothesis:
[
  {
    "hypothesis_id": "<uuid>",
    "status": "UNVERIFIED|CONFIRMED|REJECTED",
    "confidence": 0.85,
    "reasoning": "<brief justification>"
  }
]

Return an empty array if no updates are needed.
"""


class LLMSynthesizer:
    """
    Uses LLM to synthesize scored findings into structured analysis.

    Produces: executive summary, priority findings, attack chains,
    false positive candidates, risk level, and analyst notes.

    Also provides a dedicated ``update_hypotheses()`` call for
    hypothesis status transitions.
    """

    def __init__(self, llm_service):
        self._llm = llm_service

    def synthesize(
        self,
        scored_findings: list[dict],
        attack_paths: list[dict],
        recon_context: Any = None,
    ) -> dict:
        from utils.logging_utils import ScanLogger

        slog = ScanLogger("llm_synthesizer")
        slog.llm_start(
            "synthesizer",
            f"{len(scored_findings)} findings, {len(attack_paths)} attack paths",
        )
        start = _time.time()

        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_synthesis_prompt(scored_findings, attack_paths, recon_summary)
        result = self._llm.chat_json(
            SYNTHESIS_SYSTEM_PROMPT,
            prompt,
            max_tokens=LLM_AGENT_MAX_TOKENS_SYNTH,
        )
        duration_ms = int((_time.time() - start) * 1000)
        slog.llm_complete("synthesizer", duration_ms=duration_ms)

        if result is None or result.get("_fallback"):
            slog.warn("LLM synthesis returned fallback or None")
            logger.warning(
                "LLM synthesis returned fallback or None — findings will lack LLM analysis"
            )
            result = result or {}
            result["_synthesis_fallback"] = True
        else:
            slog.llm_result("Risk level: %s", result.get("risk_level", "unknown"))

        return result

    def update_hypotheses(
        self,
        hypotheses: list[dict],
        context: str,
    ) -> list[dict]:
        """Evaluate and update hypotheses via a dedicated LLM call.

        Each returned dict:
          {"hypothesis_id": "...", "status": "UNVERIFIED|CONFIRMED|REJECTED",
           "confidence": 0.85, "reasoning": "..."}

        Returns empty list on failure (fail open — hypotheses retain current state).
        """
        if not hypotheses:
            return []

        hypothesis_lines = []
        for h in hypotheses:
            hypothesis_lines.append(
                f"- [{h.get('id', '?')}] {h.get('description', '')} "
                f"(confidence={h.get('confidence', 0)}, "
                f"status={h.get('status', 'UNVERIFIED')})"
            )

        user_prompt = (
            "Current hypotheses:\n"
            + "\n".join(hypothesis_lines)
            + "\n\nRecent context:\n"
            + (context[:3000] if context else "No context available.")
        )

        try:
            result = self._llm.chat_json(
                _HYPOTHESIS_UPDATE_SYSTEM_PROMPT,
                user_prompt,
                max_tokens=2000,
            )
        except Exception as e:
            logger.warning("LLM call failed in update_hypotheses: %s", e)
            return []

        if result is None:
            return []

        # chat_json may return a dict with a fallback key, or a list
        if isinstance(result, dict):
            if result.get("_fallback"):
                return []
            return []

        if not isinstance(result, list):
            return []

        updates = []
        for raw_update in result:
            if not isinstance(raw_update, dict):
                continue
            try:
                validated = validate_hypothesis_update(raw_update, source="llm")
                updates.append(validated)
            except ValueError as e:
                logger.debug("Skipping invalid hypothesis update: %s", e)

        return updates
