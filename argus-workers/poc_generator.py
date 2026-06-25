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
            "curl_command",
            "browser_poc",
            "blind_xss_payload",
            "impact_demo",
            "developer_fix_hint",
        ],
        "instruction": (
            "Generate a reflected XSS PoC using the detected payload and endpoint."
        ),
    },
    "SQL_INJECTION": {
        "fields": [
            "curl_command",
            "sqlmap_command",
            "manual_payload",
            "data_extraction_query",
            "developer_fix_hint",
        ],
        "instruction": (
            "Generate SQLi PoC with extraction example using the parameter."
        ),
    },
    "SSRF": {
        "fields": [
            "curl_command",
            "imds_test",
            "internal_scan_example",
            "oob_detection_url",
            "developer_fix_hint",
        ],
        "instruction": (
            "Generate SSRF PoC targeting cloud IMDS and internal services."
        ),
    },
    "IDOR": {
        "fields": [
            "account_a_request",
            "account_b_request",
            "expected_403_vs_actual",
            "automation_script",
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

        # Check budget — duck-type: support both has_remaining_budget() and exceeded()
        if cost_tracker:
            _has_remaining = getattr(cost_tracker, "has_remaining_budget", None)
            _exceeded = getattr(cost_tracker, "exceeded", None)
            if (_has_remaining and not _has_remaining()) or (_exceeded and _exceeded()):
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
        if vuln_type and vuln_type != "UNKNOWN":
            for template_key in POC_TEMPLATES:
                if template_key == vuln_type:
                    template = POC_TEMPLATES[template_key]
                    break

        evidence = finding.get("evidence") or {}
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except (json.JSONDecodeError, TypeError):
                evidence = {"raw": evidence[:500]}
        elif not isinstance(evidence, dict):
            evidence = {"raw": str(evidence)[:500]}

        # Redact sensitive data from evidence before sending to LLM provider.
        # M-v4-07: Enhanced regex covers Unicode whitespace, JSON-escaped values,
        # backslash-escaped quotes, and Base64-encoded tokens. Also catches
        # shorter tokens (min 8 chars) and X-API-Key / Bearer patterns.
        import re as _redact_re

        def _redact(t: str) -> str:
            # Strip common prompt injection patterns
            _INJECTION_PATTERNS = [
                r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|directions|prompts)",
                r"forget\s+(all\s+)?(your\s+)?(instructions|directions|prompts|rules)",
                r"you\s+(are\s+)?(now|must)\s+",
                r"new\s+(instruction|prompt|rule|direction)",
            ]
            for pattern in _INJECTION_PATTERNS:
                t = _redact_re.sub(pattern, "[REDACTED]", t, flags=_redact_re.IGNORECASE)
            # Redact key=value or key:value patterns (supports Unicode whitespace and JSON escaping)
            t = _redact_re.sub(
                r"(?i)(api[_-]?key|secret|token|password|auth|credential|private_key|access_key|session_id)"
                r'(?:\s*[:=]\s*|["\']?\s*:\s*["\']?)'
                r'["\']?[^\s"\'&]+["\']?',
                r"\1=__REDACTED__",
                t[:800],
            )
            # Redact bearer tokens (Base64 and short tokens, min 8 chars)
            t = _redact_re.sub(
                r"(?i)(bearer\s+|token\s+)[a-z0-9+/_.=-]{8,}", r"\1__REDACTED__", t
            )
            # Redact standalone JWT-like patterns (three dot-separated Base64 segments)
            t = _redact_re.sub(
                r"(?i)[a-z0-9+/_-]{20,}\.[a-z0-9+/_-]{4,}\.[a-z0-9+/_-]{4,}",
                "__REDACTED_JWT__",
                t,
            )
            return t

        user_prompt = json.dumps(
            {
                "finding_type": vuln_type,
                "endpoint": finding.get("endpoint", ""),
                "severity": finding.get("severity", ""),
                "evidence": {
                    "request": f"---BEGIN EVIDENCE---\n{_redact(str(evidence.get('request', ''))[:400])}\n---END EVIDENCE---",
                    "response": f"---BEGIN EVIDENCE---\n{_redact(str(evidence.get('response', ''))[:300])}\n---END EVIDENCE---",
                    "payload": f"---BEGIN EVIDENCE---\n{_redact(str(evidence.get('payload', ''))[:200])}\n---END EVIDENCE---",
                },
                "instruction": template["instruction"],
                "required_fields": template["fields"],
            },
            indent=2,
        )

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

            # Track cost — llm_service.chat_json() tracks internally;
            # also update external cost_tracker with an estimated cost.
            # Note: result is parsed JSON from the LLM, NOT an LLMResponse,
            # so cost_usd is never present in the dict.
            if cost_tracker:
                _record = getattr(cost_tracker, "add", None) or getattr(cost_tracker, "record_llm_call", None)
                if _record:
                    _record(0.005)  # ~$0.005 estimated per 800-token call

            result["generated_at"] = datetime.now(UTC).isoformat()
            result["finding_type"] = vuln_type
            result["endpoint"] = finding.get("endpoint", "")
            result["_warning"] = (
                "FOR AUTHORIZED SECURITY TESTING ONLY. "
                "This PoC was auto-generated by an LLM and may contain inaccuracies. "
                "Verify all steps before execution. Unauthorized use is prohibited."
            )

            return result

        except Exception as e:
            logger.warning("PoC generation failed for %s: %s", vuln_type, e)
            return None
