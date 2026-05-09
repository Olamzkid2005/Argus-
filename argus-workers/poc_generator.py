"""
PoC Generator — automatically weaponises confirmed HIGH/CRITICAL findings.

Only generates PoC for findings with:
  - confidence >= 0.75
  - severity in (HIGH, CRITICAL)

Respects per-engagement LLM budget via LlmCostTracker.
Type-specific templates ensure structured, predictable output.
"""

import json
import logging
from datetime import UTC
from typing import Any

logger = logging.getLogger(__name__)


POC_SYSTEM_PROMPT = """
You are a senior penetration tester generating proof-of-concept demonstrations.
Given a confirmed security finding with evidence, produce a weaponised PoC.

CRITICAL RULES:
- All commands must be specific to the actual finding — never generic
- Include actual URLs, payloads, and parameters from the evidence
- Do NOT invent vulnerabilities — only work with what's in the evidence
- Output valid JSON only

Return exactly the fields specified in the template.
"""


# ── Type-specific PoC templates ─────────────────────────────────────

POC_TEMPLATES: dict[str, dict[str, Any]] = {
    "XSS": {
        "fields": [
            "curl_command", "browser_poc", "blind_xss_payload",
            "impact_demo", "developer_fix_hint",
        ],
        "instruction": (
            "Generate a reflected XSS PoC using the detected payload and endpoint."
        ),
    },
    "SQL_INJECTION": {
        "fields": [
            "curl_command", "sqlmap_command", "manual_payload",
            "data_extraction_query", "developer_fix_hint",
        ],
        "instruction": (
            "Generate SQLi PoC with extraction example using the parameter."
        ),
    },
    "SSRF": {
        "fields": [
            "curl_command", "imds_test", "internal_scan_example",
            "oob_detection_url", "developer_fix_hint",
        ],
        "instruction": (
            "Generate SSRF PoC targeting cloud IMDS and internal services."
        ),
    },
    "IDOR": {
        "fields": [
            "account_a_request", "account_b_request",
            "expected_403_vs_actual", "automation_script",
            "developer_fix_hint",
        ],
        "instruction": (
            "Generate two-account IDOR PoC showing cross-user data access."
        ),
    },
}

DEFAULT_TEMPLATE = {
    "fields": ["curl_command", "manual_steps", "developer_fix_hint"],
    "instruction": (
        "Generate a generic PoC for this finding with curl and reproduction."
    ),
}


class PoCGenerator:
    """Generates PoC demonstrations for confirmed findings. Budget-aware.

    Type-specific templates produce structured output for XSS, SQLI,
    SSRF, IDOR, and other vulnerability types.
    """

    MIN_CONFIDENCE = 0.75
    ALLOWED_SEVERITIES = {"CRITICAL", "HIGH"}

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def should_generate(self, finding: dict) -> tuple[bool, str]:
        """Check whether PoC generation is warranted for this finding.

        Args:
            finding: Scored finding dict

        Returns:
            (True, "") or (False, "reason for skipping")
        """
        severity = finding.get("severity", "INFO").upper()
        if severity not in self.ALLOWED_SEVERITIES:
            return False, f"severity={severity} not allowed"

        confidence = finding.get("confidence", 0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return False, "invalid confidence"

        if confidence < self.MIN_CONFIDENCE:
            return False, f"confidence={confidence:.2f} < {self.MIN_CONFIDENCE}"

        return True, ""

    def generate(
        self,
        finding: dict,
        llm_service: Any = None,
        cost_tracker: Any = None,
    ) -> dict | None:
        """Generate PoC for a single finding.

        Args:
            finding: Scored finding dict
            llm_service: LLMService instance for chat_json
            cost_tracker: Optional LlmCostTracker to check budget

        Returns:
            PoC dict with type-specific fields, or None if skipped/failed
        """
        should, reason = self.should_generate(finding)
        if not should:
            logger.debug("Skipping PoC: %s", reason)
            return None

        if not llm_service and not self.llm_client:
            logger.warning("No LLM available for PoC generation")
            return None

        # Check budget
        if cost_tracker and not cost_tracker.has_remaining_budget():
            logger.info(
                "LLM budget exhausted — skipping PoC for engagement %s",
                getattr(cost_tracker, "engagement_id", "?"),
            )
            return None

        if llm_service and not llm_service.is_available():
            return None

        vuln_type = finding.get("type", "UNKNOWN").upper()
        # Find matching template
        template = DEFAULT_TEMPLATE
        for template_key in POC_TEMPLATES:
            if template_key in vuln_type or vuln_type in template_key:
                template = POC_TEMPLATES[template_key]
                break

        evidence = finding.get("evidence", {})
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except (json.JSONDecodeError, TypeError):
                evidence = {"raw": evidence[:500]}

        user_prompt = json.dumps({
            "finding_type": vuln_type,
            "endpoint": finding.get("endpoint", ""),
            "severity": finding.get("severity", ""),
            "evidence": {
                "request": str(evidence.get("request", ""))[:400],
                "response": str(evidence.get("response", ""))[:300],
                "payload": str(evidence.get("payload", ""))[:200],
            },
            "instruction": template["instruction"],
            "required_fields": template["fields"],
        }, indent=2)

        try:
            from datetime import datetime

            if llm_service:
                result = llm_service.chat_json(
                    system_prompt=POC_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=800,
                    temperature=0.1,
                )
            else:
                from llm_service import LLMService as LLMSvc
                svc = LLMSvc(llm_client=self.llm_client)
                result = svc.chat_json(
                    system_prompt=POC_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=800,
                    temperature=0.1,
                )

            if result.get("_fallback"):
                logger.warning("PoC generation returned fallback for %s", vuln_type)
                return None

            # Track cost
            if cost_tracker and "cost_usd" in result:
                cost_tracker.record_llm_call(result.get("cost_usd", 0))

            result["generated_at"] = datetime.now(UTC).isoformat()
            result["finding_type"] = vuln_type
            result["endpoint"] = finding.get("endpoint", "")

            return result

        except Exception as e:
            logger.warning("PoC generation failed for %s: %s", vuln_type, e)
            return None
