"""
LLM Detector - Post-response intelligence using LLM analysis.

Analyzes HTTP responses to detect subtle vulnerabilities that
regex/pattern-based detection misses. Designed as a second-pass
verifier for low-confidence findings.

Graceful degradation: All methods return None on failure.
The system works exactly as today when LLM is unavailable.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMAnalysisResult:
    """Structured result from LLM response analysis."""
    vulnerable: bool
    confidence: float          # 0.0-1.0, how confident LLM is in the finding
    evidence_quote: str        # Exact string from response that indicates vuln
    vuln_type: str             # e.g., "XSS", "SQL_INJECTION", "SSTI", "LFI"
    reasoning: str             # 1-sentence explanation
    model: str                 # LLM model used
    timestamp: str             # ISO timestamp


class LLMDetector:
    """
    Analyzes HTTP responses using LLM to detect vulnerabilities.
    Used as a second-pass verifier for low-confidence findings.
    All methods return None on failure (graceful degradation).
    """

    # Prompt template for vulnerability analysis
    ANALYSIS_PROMPT = """You are a penetration testing expert analyzing HTTP responses for vulnerability evidence.

Probe details:
- Vulnerability class: {vuln_class}
- Payload sent: {payload}
- Target URL: {test_url}

Response:
- Status code: {status_code}
- Content-Type: {content_type}
- Relevant headers: {headers}
- Response body (first {max_chars} chars):
{body_snippet}

Analyze the response for evidence of a successful {vuln_class} vulnerability.
Look for:
1. Payload reflection without encoding (unescaped HTML/JS/JSON injection)
2. Error messages that reference the payload or reveal internal state
3. Evaluation of template expressions (e.g., 7*7 = 49, ${{...}} expansion)
4. Successful authentication bypass or privilege escalation
5. File content inclusion in the response
6. Any unexpected behavior that indicates successful exploitation

Return ONLY a valid JSON object with these exact keys:
```json
{{
    "vulnerable": true,
    "confidence": 0.85,
    "evidence_quote": "exact string from response that indicates vulnerability",
    "vuln_type": "{vuln_class}",
    "reasoning": "1-sentence explanation of why this is vulnerable"
}}
```

If NOT vulnerable:
```json
{{
    "vulnerable": false,
    "confidence": 0.0,
    "evidence_quote": "",
    "vuln_type": "{vuln_class}",
    "reasoning": "No evidence of successful exploitation detected"
}}
```"""

    # Headers that may be useful for vulnerability analysis
    RELEVANT_HEADERS = [
        "content-type", "x-frame-options", "x-xss-protection",
        "content-security-policy", "set-cookie", "location",
        "www-authenticate", "access-control-allow-origin",
    ]

    def __init__(
        self,
        llm_client: Any,
        model: str | None = None,
        max_retries: int = 2,
    ):
        """
        Initialize LLM Detector.

        Args:
            llm_client: LLMClient instance for making LLM calls
            model: Model to use (defaults to LLMClient's model)
            max_retries: Max retry attempts for LLM calls
        """
        self.llm = llm_client
        self.model = model or getattr(llm_client, 'model', 'gpt-4o-mini')
        self.max_retries = max_retries

    async def analyze_async(
        self,
        test_url: str,
        vuln_class: str,
        payload: str,
        response: Any,
        context: dict | None = None,
        max_response_chars: int = 3000,
    ) -> LLMAnalysisResult | None:
        """
        Analyze an HTTP response for vulnerability evidence (async).

        Args:
            test_url: The URL that was probed
            vuln_class: Vulnerability class being tested (e.g., "XSS", "SQL_INJECTION")
            payload: The payload that was sent
            response: HTTP response object (needs .status_code, .headers, .text attributes)
            context: Optional dict with extra context (param name, etc.)
            max_response_chars: Max chars of response body to analyze

        Returns:
            LLMAnalysisResult if analysis succeeds, None on failure or if not vulnerable
        """
        try:
            if not self.llm.is_available():
                logger.debug("LLM not available, skipping response analysis")
                return None

            # Extract response data
            status_code = getattr(response, 'status_code', 0)
            headers = getattr(response, 'headers', {})
            body = getattr(response, 'text', getattr(response, 'content', b''))
            if isinstance(body, bytes):
                body = body.decode('utf-8', errors='replace')

            # Truncate body
            body_snippet = body[:max_response_chars]

            # Filter relevant headers
            header_str = "; ".join(
                f"{k}: {v}" for k, v in headers.items()
                if k.lower() in self.RELEVANT_HEADERS
            )
            content_type = headers.get("Content-Type", "unknown")

            # Build prompt
            prompt_text = self.ANALYSIS_PROMPT.format(
                vuln_class=vuln_class,
                payload=payload[:200],
                test_url=test_url,
                status_code=status_code,
                content_type=content_type,
                headers=header_str or "none",
                max_chars=max_response_chars,
                body_snippet=body_snippet,
            )

            messages = [
                {"role": "system", "content": "You are a security analysis assistant. Always return valid JSON."},
                {"role": "user", "content": prompt_text},
            ]

            # Call LLM
            raw_response = await self.llm.chat(
                messages=messages,
                temperature=0.1,  # Low temperature for deterministic output
                max_tokens=300,
                response_format={"type": "json_object"},
            )

            # Parse result
            result = self._parse_response(raw_response)
            if result:
                result.model = self.model
                result.timestamp = datetime.now(UTC).isoformat()
                return result

            return None

        except Exception as e:
            logger.warning(f"LLM response analysis failed: {e}")
            return None

    def analyze_sync(
        self,
        test_url: str,
        vuln_class: str,
        payload: str,
        response: Any,
        context: dict | None = None,
        max_response_chars: int = 3000,
    ) -> LLMAnalysisResult | None:
        """
        Synchronous version of analyze_async.
        Used by scan-phase code that can't use async.
        """
        # This is a stub that logs a warning — the scan phase should use
        # the post-scan task, not inline analysis.
        logger.warning(
            "LLMDetector.analyze_sync() called. "
            "Inline LLM analysis during scan is not recommended. "
            "Use the post-scan tasks.llm_review task instead."
        )
        return None

    def should_skip(self, finding: dict, response: Any) -> bool:
        """
        Determine if this finding should be skipped for LLM analysis.

        Skip if:
        - Confidence is already high (> 0.7, doesn't need review)
        - Confidence is very low (< 0.3, too noisy, likely false positive)
        - No response to analyze (replay failed)
        - Response is binary or empty

        Args:
            finding: Finding dictionary
            response: HTTP response object (fresh from _replay_request)

        Returns:
            True if this finding should be skipped
        """
        confidence = finding.get("confidence", 0.0)
        if confidence >= 0.7:
            return True  # Already confident enough
        if confidence < 0.3:
            return True  # Too noisy, skip

        if not response:
            return True

        body = getattr(response, 'text', '')
        if not body:
            body = getattr(response, 'content', b'')
            if isinstance(body, bytes):
                try:
                    body = body.decode('utf-8', errors='replace')
                except Exception:
                    body = ''
        if len(body.strip()) < 50:
            return True  # Response too short to analyze

        # Skip binary-looking responses
        return bool(body and '\x00' in body[:100])

    def _parse_response(self, raw_text: str) -> LLMAnalysisResult | None:
        """
        Parse LLM response into structured result.

        Attempts JSON parsing first, falls back to regex extraction.

        Args:
            raw_text: Raw LLM response text

        Returns:
            LLMAnalysisResult or None if parsing fails
        """
        # Try JSON parsing
        try:
            # Extract JSON from markdown code blocks if present
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(1)

            data = json.loads(raw_text.strip())

            return LLMAnalysisResult(
                vulnerable=bool(data.get("vulnerable", False)),
                confidence=float(data.get("confidence", 0.0)),
                evidence_quote=str(data.get("evidence_quote", "")),
                vuln_type=str(data.get("vuln_type", "UNKNOWN")),
                reasoning=str(data.get("reasoning", "")),
                model="unknown",
                timestamp="",
            )
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse LLM response as JSON: {e}")

            # Fallback: try regex extraction
            try:
                vulnerable = "true" in re.search(r'"vulnerable"\s*:\s*(true|false)', raw_text, re.IGNORECASE).group(1).lower()
                confidence_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', raw_text)
                confidence = float(confidence_match.group(1)) if confidence_match else 0.0
                evidence_match = re.search(r'"evidence_quote"\s*:\s*"([^"]*)"', raw_text)
                evidence_quote = evidence_match.group(1) if evidence_match else ""

                return LLMAnalysisResult(
                    vulnerable=vulnerable,
                    confidence=min(1.0, max(0.0, confidence)),
                    evidence_quote=evidence_quote,
                    vuln_type="UNKNOWN",
                    reasoning="Parsed via regex fallback",
                    model="unknown",
                    timestamp="",
                )
            except Exception:
                logger.debug("Regex fallback parsing also failed")
                return None
