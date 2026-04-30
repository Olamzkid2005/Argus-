"""
LLM Report Generator - Uses LLM to write the final human-readable security report.

Produces: executive summary, technical findings with remediation,
and CVSS-prioritized action items.
"""
import json
import logging
from typing import Dict, List, Generator, Any

from config.constants import LLM_AGENT_MAX_TOKENS_REPORT
from agent.agent_prompts import REPORT_SYSTEM_PROMPT, build_report_prompt

logger = logging.getLogger(__name__)


class LLMReportGenerator:
    """
    Generates professional penetration test reports using LLM.

    Can produce reports as structured JSON or stream them token by token.
    """

    def __init__(self, llm_service):
        self._llm = llm_service

    def generate_report(
        self,
        synthesis: Dict,
        scored_findings: List[Dict],
        engagement: Dict,
        recon_context: Any = None,
    ) -> Dict:
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_report_prompt(synthesis, scored_findings, engagement, recon_summary)
        result = self._llm.chat_json(
            REPORT_SYSTEM_PROMPT, prompt,
            max_tokens=LLM_AGENT_MAX_TOKENS_REPORT,
        )
        return result

    def stream_report(
        self, synthesis: Dict, scored_findings: List[Dict],
        engagement: Dict, recon_context: Any = None,
    ) -> Generator[str, None, None]:
        recon_summary = ""
        if recon_context is not None:
            recon_summary = (
                recon_context.to_llm_summary()
                if hasattr(recon_context, "to_llm_summary")
                else str(recon_context)
            )

        prompt = build_report_prompt(synthesis, scored_findings, engagement, recon_summary)

        if hasattr(self._llm._client, "chat_stream"):
            for chunk in self._llm._client.chat_stream(
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

    def _fallback_report(self, engagement: Dict, scored_findings: List[Dict]) -> Dict:
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
            "scope_and_methodology": {"target": engagement.get("target_url", "N/A"),
                                       "findings_analyzed": total},
            "findings_summary_table": [
                {"severity": sev, "count": count}
                for sev, count in severity_counts.items() if count > 0
            ],
            "detailed_findings": [],
            "remediation_roadmap": [],
            "conclusion": "Report generated in fallback mode (LLM unavailable).",
        }
