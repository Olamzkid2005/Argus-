"""
IntentParser — translates natural language scan requests into structured config.

Security model:
  1. User input sanitized: truncated to 2000 chars, control chars + prompt
     injection markers stripped before LLM
  2. LLM output validated against INTENT_SCHEMA — extra fields dropped,
     expected fields type-checked
  3. target_url validated as proper http/https URL
"""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


INTENT_SYSTEM_PROMPT = (
    "You translate a security analyst's intent description into a "
    "structured scan configuration. Extract: target URL, scan type, "
    "priority vulnerability classes, aggressiveness, auth credentials "
    "if mentioned, tech stack hints, any exclusions.\n\n"
    "Rules:\n"
    "- Only extract information that is EXPLICITLY stated\n"
    "- Do NOT assume or invent configuration values\n"
    "- If something is not mentioned, use the default\n"
    "- Return valid JSON only — no explanation, no markdown"
)

INTENT_SCHEMA: dict[str, type] = {
    "target_url": str,
    "scan_type": str,
    "aggressiveness": str,
    "agent_mode": bool,
    "mode": str,
    "priority_classes": list,
    "skip_vuln_types": list,
    "tech_stack_hints": list,
    "auth_config": dict,
    "severity_filter": str,
    "intent_summary": str,
}


def sanitize_input(text: str) -> str:
    """Sanitize user input before sending to LLM.

    Strips control characters and common prompt-injection patterns.
    Truncates to 2000 characters.

    Args:
        text: Raw user input

    Returns:
        Sanitized text safe for LLM prompt injection
    """
    # Strip control characters
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # Strip common prompt injection patterns
    sanitized = re.sub(
        r"(?i)(ignore\s+.*instructions|forget\s+.*prompt|"
        r"system\s+prompt|you\s+are\s+now|"
        r"new\s+instructions|override)",
        "[REDACTED]",
        sanitized,
    )
    return sanitized[:2000]


def validate_url(url: str) -> bool:
    """Basic URL validation — must be http or https with valid netloc.

    Args:
        url: URL string to validate

    Returns:
        True if valid
    """
    try:
        result = urlparse(url)
        return all([result.scheme in ("http", "https"), result.netloc])
    except Exception:
        return False


def validate_output(data: dict) -> dict:
    """Validate LLM output against INTENT_SCHEMA.

    - Drops any fields not in schema
    - Verifies types match expected type
    - Applies defaults for missing optional fields
    - Validates target_url

    Args:
        data: Raw LLM output dict

    Returns:
        Validated config dict with only schema fields
    """
    validated: dict[str, Any] = {}

    defaults = {
        "scan_type": "url",
        "aggressiveness": "default",
        "agent_mode": True,
        "mode": "standard",
        "severity_filter": "all",
        "priority_classes": [],
        "skip_vuln_types": [],
        "tech_stack_hints": [],
        "auth_config": {},
        "intent_summary": "",
    }

    for field, expected_type in INTENT_SCHEMA.items():
        value = data.get(field)

        if value is None:
            validated[field] = defaults.get(field)
            continue

        # Type checking
        if expected_type == str and isinstance(value, str):
            validated[field] = value.strip()
        elif expected_type == bool and isinstance(value, bool):
            validated[field] = value
        elif expected_type == list and isinstance(value, list):
            validated[field] = [str(v)[:100] for v in value[:20]]
        elif expected_type == dict and isinstance(value, dict):
            validated[field] = {
                str(k)[:50]: str(v)[:200] for k, v in value.items()
            }

    # Validate target_url
    if not validated.get("target_url") or not validate_url(
        validated["target_url"]
    ):
        validated["error"] = (
            "No valid target URL found in your description"
        )

    return validated


class IntentParser:
    """Translates natural language scan requests into structured config.

    Usage:
        parser = IntentParser()
        result = parser.parse("Scan https://example.com for SQLi")
        # result = {
        #     "target_url": "https://example.com",
        #     "scan_type": "url",
        #     "priority_classes": ["sqli"],
        #     ...
        # }
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def parse(
        self, intent_text: str, llm_service=None
    ) -> dict:
        """Parse natural language scan intent.

        Args:
            intent_text: Free-text description of scan intent
            llm_service: Optional LLMService instance

        Returns:
            Structured config dict, or dict with "error" key on failure
        """
        if not intent_text or not intent_text.strip():
            return {"error": "No input provided"}

        sanitized = sanitize_input(intent_text)

        if not llm_service and self.llm_client:
            from llm_service import LLMService
            llm_service = LLMService(llm_client=self.llm_client)

        if not llm_service or not llm_service.is_available():
            # Fallback: basic URL extraction
            urls = re.findall(r"https?://[^\s,;)]+", sanitized)
            if urls:
                return validate_output({
                    "target_url": urls[0],
                    "intent_summary": f"Scan {urls[0]}",
                })
            return {
                "error": "Could not parse scan intent",
                "raw": intent_text[:500],
            }

        try:
            result = llm_service.chat_json(
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_prompt=f"Translate this scan request:\n\n{sanitized}",
                max_tokens=600,
                temperature=0.1,
            )

            if result.get("_fallback"):
                return {
                    "error": "Could not parse intent: LLM fallback",
                    "raw": intent_text[:500],
                }

            return validate_output(result)

        except Exception as e:
            logger.warning("Intent parsing failed: %s", e)
            # Fallback: regex URL extraction
            urls = re.findall(r"https?://[^\s,;)]+", sanitized)
            if urls:
                return validate_output({
                    "target_url": urls[0],
                    "intent_summary": f"Scan {urls[0]}",
                })
            return {
                "error": f"Failed to parse intent: {e}",
                "raw": intent_text[:500],
            }
