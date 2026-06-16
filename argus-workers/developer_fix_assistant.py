"""
Developer Fix Assistant — generates PR-ready remediation for findings.

Tech-stack-aware: adjusts output based on detected framework/language.
Budget-aware: respects per-engagement LLM cost limits via LlmCostTracker.
"""

import json
import logging
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


FIX_SYSTEM_PROMPT = """
You are a senior application security engineer generating developer-ready
remediation. Given a confirmed finding, the app's tech stack, and the
actual vulnerable code snippet (when available), produce:

1. vulnerable_pattern: The code pattern that caused this (use the provided code_snippet if available, or pseudocode)
2. fixed_pattern: The corrected version with security controls applied
3. explanation: Why the fix works (2-3 sentences, developer-friendly)
4. unit_test: A unit test that would catch this regression
5. library_recommendation: Library that makes this safer (or null)
6. additional_contexts: Other places this pattern might exist (or [])

Be specific to the actual tech stack and code. Never give generic advice.
Return valid JSON only.
"""


class DeveloperFixAssistant:
    """Generates developer-ready remediation for MEDIUM+ findings.

    Only generates for MEDIUM/HIGH/CRITICAL findings.
    Respects LLM budget via cost_tracker.
    Tech-stack-aware: output adjusts based on detected technology.
    """

    ALLOWED_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM"}

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def should_generate(self, finding: dict) -> bool:
        """Check whether fix generation is warranted.

        Args:
            finding: Finding dict with severity

        Returns:
            True if severity qualifies
        """
        severity = finding.get("severity", "INFO").upper()
        return severity in self.ALLOWED_SEVERITIES

    def generate(
        self,
        finding: dict,
        tech_stack: list[str],
        llm_service: Any = None,
        cost_tracker: Any = None,
    ) -> dict | None:
        """Generate developer fix for a single finding.

        Args:
            finding: Finding dict with type, endpoint, evidence, severity
            tech_stack: Detected technology stack (e.g. ['python', 'flask'])
            llm_service: LLMService instance
            cost_tracker: Optional LlmCostTracker for budget tracking

        Returns:
            Fix dict with vulnerable_pattern, fixed_pattern, etc., or None
        """
        if not self.should_generate(finding):
            return None

        if not llm_service and self.llm_client:
            from llm_service import LLMService
            llm_service = LLMService(llm_client=self.llm_client)

        if not llm_service or not llm_service.is_available():
            return None

        if cost_tracker and not cost_tracker.has_remaining_budget():
            logger.info(
                "LLM budget exhausted — skipping fix generation"
            )
            return None

        stack_str = (
            ", ".join(tech_stack[:5]) if tech_stack else "unknown"
        )
        evidence = finding.get("evidence", {})

        user_prompt = json.dumps({
            "finding_type": finding.get("type", "UNKNOWN"),
            "severity": finding.get("severity", "MEDIUM"),
            "endpoint": finding.get("endpoint", ""),
            "evidence": {
                "request": str(evidence.get("request", ""))[:400],
                "response": str(evidence.get("response", ""))[:300],
                "payload": str(evidence.get("payload", ""))[:200],
                "code_snippet": str(evidence.get("code", "") or evidence.get("code_snippet", "") or evidence.get("match", "") or "")[:500],
            },
            "tech_stack": tech_stack[:5],
            "instruction": (
                f"Generate remediation for this {finding.get('type')} "
                f"finding in a {stack_str} application."
            ),
        }, indent=2)

        try:
            from datetime import datetime

            result = llm_service.chat_json(
                system_prompt=FIX_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=900,
                temperature=0.1,
            )

            if result.get("_fallback"):
                return None

            if cost_tracker and "cost_usd" in result:
                cost_tracker.record_llm_call(result.get("cost_usd", 0))

            result["generated_at"] = datetime.now(
                UTC
            ).isoformat()
            result["tech_stack"] = tech_stack[:5]

            return result

        except Exception as e:
            logger.warning("Fix generation failed: %s", e)
            return None
