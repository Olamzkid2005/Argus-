"""
LLM Synthesizer - Uses LLM to preside over scored findings and produce a structured analysis.

Separate from IntelligenceEngine (rule-based scoring). The LLM adds narrative
reasoning, attack chain identification, false positive analysis, and prioritization
on top of already-scored data.
"""
import json
import logging
from typing import Dict, List, Optional, Any

from config.constants import LLM_AGENT_MAX_TOKENS_SYNTH
from agent.agent_prompts import SYNTHESIS_SYSTEM_PROMPT, build_synthesis_prompt
from llm_client import LLMResponse

logger = logging.getLogger(__name__)


class LLMSynthesizer:
    """
    Uses LLM to synthesize scored findings into structured analysis.

    Produces: executive summary, priority findings, attack chains,
    false positive candidates, risk level, and analyst notes.
    """

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLMClient instance
        """
        self.llm_client = llm_client

    def synthesize(
        self,
        scored_findings: List[Dict],
        attack_paths: List[Dict],
        recon_context: Any = None,
    ) -> Dict:
        """
        Call LLM to synthesize findings into structured analysis.

        Args:
            scored_findings: List of scored finding dicts
            attack_paths: List of attack path dicts
            recon_context: Optional ReconContext for additional context

        Returns:
            Dict with keys: executive_summary, priority_findings,
            attack_chains, fp_candidates, risk_level, analyst_notes
        """
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_synthesis_prompt(scored_findings, attack_paths, recon_summary)

        try:
            raw = self.llm_client.chat_sync(
                messages=[
                    {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=LLM_AGENT_MAX_TOKENS_SYNTH,
                response_format={"type": "json_object"},
            )

            response_text = raw.text if isinstance(raw, LLMResponse) else raw
            return json.loads(response_text)

        except Exception as e:
            logger.warning(f"LLM synthesis failed (non-fatal): {e}")
            return self._fallback_synthesis(scored_findings)

    def _fallback_synthesis(self, scored_findings: List[Dict]) -> Dict:
        """Return a minimal synthesis when LLM is unavailable."""
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in scored_findings:
            sev = (f.get("severity", "") or "").lower()
            if sev in severity_counts:
                severity_counts[sev] += 1

        return {
            "executive_summary": (
                f"Analysis completed with {len(scored_findings)} findings. "
                f"Critical: {severity_counts['critical']}, "
                f"High: {severity_counts['high']}, "
                f"Medium: {severity_counts['medium']}, "
                f"Low: {severity_counts['low']}."
            ),
            "risk_level": (
                "critical"
                if severity_counts["critical"] > 0
                else "high" if severity_counts["high"] > 0
                else "medium" if severity_counts["medium"] > 0
                else "low"
            ),
            "priority_findings": [],
            "attack_chains": [],
            "fp_candidates": [],
            "analyst_notes": "LLM synthesis unavailable — using fallback summary.",
        }
