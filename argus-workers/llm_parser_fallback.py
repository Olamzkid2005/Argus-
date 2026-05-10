"""
LLM Parser Fallback — recovers findings when structured parsers return nothing.

Only activates when:
  - Feature flag "llm_parser_fallback" is enabled
  - The primary parser returned zero findings
  - Raw output is non-empty (length > 100 chars)

Sends raw tool output to a lightweight LLM that extracts findings into
standard JSON format. This recovers findings from:
  - New output formats the parsers don't yet handle
  - Tool version updates that change output structure
  - Edge cases in otherwise valid output

Cost-controlled: uses a cheap model, max 500 output tokens, and only
fires on parser miss — zero cost for scans where parsers work correctly.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

FALLBACK_SYSTEM_PROMPT = (
    "You are a security tool output parser. Given raw output from a "
    "penetration testing tool, determine if it contains any security "
    "findings. If yes, extract them into a JSON array of finding objects.\n\n"
    "Rules:\n"
    "- Only extract findings that are clearly present in the output\n"
    "- Do NOT invent or assume findings\n"
    "- Each finding must have: type, severity, endpoint, and evidence\n"
    "- severity must be one of: CRITICAL, HIGH, MEDIUM, LOW, INFO\n"
    "- evidence should contain relevant payload, request, or response data\n"
    "- If the output contains no findings, return an empty array []\n"
    "- Return valid JSON only — no explanation, no markdown"
)


class LLMParserFallback:
    """LLM-powered fallback that extracts findings from raw tool output.

    Only fired when structured parsers return zero findings.
    Gated behind the "llm_parser_fallback" feature flag.
    Uses a lightweight model to keep costs minimal.
    """

    FALLBACK_MODEL = os.getenv(
        "LLM_PARSER_FALLBACK_MODEL",
        "openai/gpt-4o-mini",
    )

    MIN_OUTPUT_LENGTH = 100

    def __init__(self, llm_service=None):
        """Initialize the fallback parser.

        Args:
            llm_service: Optional pre-configured LLMService instance.
                         If not provided, creates its own lightweight client
                         using the OpenRouter gpt-4o-mini model.
        """
        self._llm_service = llm_service
        self._service_initialized = False

    def _ensure_service(self):
        """Lazy-init LLM service on first call — avoids cost if never used."""
        if self._service_initialized:
            return self._llm_service is not None
        self._service_initialized = True

        if self._llm_service is not None:
            return True

        try:
            from llm_client import LLMClient

            client = LLMClient(model=self.FALLBACK_MODEL)
            if not client.is_available():
                logger.debug("LLMParserFallback: LLM not available")
                return False

            from llm_service import LLMService

            self._llm_service = LLMService(llm_client=client)
            return True
        except Exception as e:
            logger.warning(
                "LLMParserFallback: failed to initialize LLM service: %s", e
            )
            return False

    def extract_findings(self, tool_name: str, raw_output: str) -> list[dict]:
        """Attempt to extract findings from raw tool output using LLM.

        Args:
            tool_name: Name of the tool that produced the output
            raw_output: Raw stdout/stderr from the tool

        Returns:
            List of finding dicts in standard format, or empty list
        """
        if not self._ensure_service():
            return []

        is_available = False
        try:
            is_available = self._llm_service.is_available()  # type: ignore[union-attr]
        except Exception:
            pass

        if not is_available:
            return []

        # Truncate raw output to keep the LLM call manageable.
        # 10KB should be more than enough — parsers typically handle
        # structured output that's much smaller.
        max_input_len = 10000
        truncated = raw_output[:max_input_len]
        if len(raw_output) > max_input_len:
            truncated += f"\n\n[output truncated — {len(raw_output)} chars total]"

        user_prompt = (
            f"Tool: {tool_name}\n\n"
            f"Raw output:\n```\n{truncated}\n```\n\n"
            f"Does this output contain any security findings? "
            f"If yes, extract them as a JSON array."
        )

        try:
            result = self._llm_service.chat_json(  # type: ignore[union-attr]
                system_prompt=FALLBACK_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=500,
                temperature=0.0,
            )

            if result.get("_fallback"):
                logger.debug(
                    "LLMParserFallback: LLM call failed for %s", tool_name
                )
                return []

            findings = result if isinstance(result, list) else []

            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                finding.setdefault("source_tool", tool_name)
                finding.setdefault("parser_source", "llm_fallback")

            return findings

        except Exception as e:
            logger.warning(
                "LLMParserFallback: extraction failed for %s: %s", tool_name, e
            )
            return []
