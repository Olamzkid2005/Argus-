"""
LLM Report Generator - Uses LLM to write the final human-readable security report.

Produces: executive summary, technical findings with remediation,
and CVSS-prioritized action items. Supports streaming for real-time display.
"""
import json
import logging
from typing import Dict, List, Optional, Generator, Any

from config.constants import LLM_AGENT_MAX_TOKENS_REPORT
from agent.agent_prompts import REPORT_SYSTEM_PROMPT, build_report_prompt
from llm_client import LLMResponse

logger = logging.getLogger(__name__)


class LLMReportGenerator:
    """
    Generates professional penetration test reports using LLM.

    Can produce reports as structured JSON or stream them token by token.
    """

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLMClient instance
        """
        self.llm_client = llm_client

    def generate_report(
        self,
        synthesis: Dict,
        scored_findings: List[Dict],
        engagement: Dict,
        recon_context: Any = None,
    ) -> Dict:
        """
        Generate a complete report using LLM.

        Args:
            synthesis: Output from LLMSynthesizer
            scored_findings: List of scored finding dicts
            engagement: Engagement metadata dict
            recon_context: Optional ReconContext

        Returns:
            Dict with report sections: executive_summary, scope, findings_summary,
            detailed_findings, remediation_roadmap, conclusion
        """
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_report_prompt(synthesis, scored_findings, engagement, recon_summary)

        try:
            raw = self.llm_client.chat_sync(
                messages=[
                    {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=LLM_AGENT_MAX_TOKENS_REPORT,
                response_format={"type": "json_object"},
            )

            response_text = raw.text if isinstance(raw, LLMResponse) else raw
            return json.loads(response_text)

        except Exception as e:
            logger.warning(f"LLM report generation failed (non-fatal): {e}")
            return self._fallback_report(engagement, scored_findings)

    def stream_report(
        self, synthesis: Dict, scored_findings: List[Dict],
        engagement: Dict, recon_context: Any = None,
    ) -> Generator[str, None, None]:
        """
        Stream report generation token by token.

        Yields chunks of report text as they arrive from the LLM.
        Falls back to single-chunk emit if streaming not supported.
        """
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_report_prompt(synthesis, scored_findings, engagement, recon_summary)

        try:
            if hasattr(self.llm_client, "chat_stream"):
                for chunk in self.llm_client.chat_stream(
                    messages=[
                        {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=LLM_AGENT_MAX_TOKENS_REPORT,
                ):
                    yield chunk
            else:
                report = self.generate_report(synthesis, scored_findings, engagement, recon_context)
                yield json.dumps(report)

        except Exception as e:
            logger.warning(f"LLM report streaming failed: {e}")
            yield json.dumps(self._fallback_report(engagement, scored_findings))

    def _fallback_report(self, engagement: Dict, scored_findings: List[Dict]) -> Dict:
        """Return a minimal report when LLM is unavailable."""
        severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in scored_findings:
            sev = (f.get("severity", "") or "").upper()
            if sev in severity_counts:
                severity_counts[sev] += 1

        total = len(scored_findings)

        return {
            "executive_summary": (
                f"A security assessment of {engagement.get('target_url', 'N/A')} "
                f"identified {total} findings."
            ),
            "scope_and_methodology": {
                "target": engagement.get("target_url", "N/A"),
                "findings_analyzed": total,
            },
            "findings_summary_table": [
                {"severity": sev, "count": count}
                for sev, count in severity_counts.items()
                if count > 0
            ],
            "detailed_findings": [],
            "remediation_roadmap": [],
            "conclusion": "Report generated in fallback mode (LLM unavailable).",
        }
