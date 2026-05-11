"""
LLM Synthesizer - Uses LLM to preside over scored findings and produce structured analysis.

Separate from IntelligenceEngine (rule-based scoring). The LLM adds narrative
reasoning, attack chain identification, false positive analysis, and prioritization
on top of already-scored data.
"""
import logging
from typing import Any

from agent.agent_prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_prompt
from config.constants import LLM_AGENT_MAX_TOKENS_SYNTH

logger = logging.getLogger(__name__)


class LLMSynthesizer:
    """
    Uses LLM to synthesize scored findings into structured analysis.

    Produces: executive summary, priority findings, attack chains,
    false positive candidates, risk level, and analyst notes.
    """

    def __init__(self, llm_service):
        self._llm = llm_service

    def synthesize(
        self,
        scored_findings: list[dict],
        attack_paths: list[dict],
        recon_context: Any = None,
    ) -> dict:
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_synthesis_prompt(scored_findings, attack_paths, recon_summary)
        result = self._llm.chat_json(
            SYNTHESIS_SYSTEM_PROMPT, prompt,
            max_tokens=LLM_AGENT_MAX_TOKENS_SYNTH,
        )
        if result.get("_fallback"):
            logger.warning("LLM synthesis returned fallback — findings will lack LLM analysis")
            result["_synthesis_fallback"] = True
        return result
