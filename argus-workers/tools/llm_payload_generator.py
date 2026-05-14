"""
LLM Payload Generator - Context-aware probe payloads.

Generates vulnerability-specific payloads tailored to the endpoint context
(parameter name, reflection context, framework hints). Augments static
payload lists with context-aware variants.

Graceful degradation: Returns empty list on any failure.
The system works exactly as today when LLM is unavailable.
"""
import hashlib
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

from utils.logging_utils import ScanLogger

# Try to import config constants (graceful if not available)
try:
    from config.constants import (
        LLM_MAX_GENERATED_PAYLOADS,
        LLM_PAYLOAD_CACHE_TTL,
        LLM_PAYLOAD_GENERATION_ENABLED,
        LLM_PAYLOAD_GENERATION_MODEL,
    )
except ImportError:
    LLM_PAYLOAD_GENERATION_ENABLED = True
    LLM_PAYLOAD_CACHE_TTL = 3600
    LLM_MAX_GENERATED_PAYLOADS = 2
    LLM_PAYLOAD_GENERATION_MODEL = "gpt-4o-mini"


class PayloadCache:
    """
    Simple in-memory TTL cache for generated payloads.

    Cache key: "{vuln_class}:{context_fingerprint}"
    Cache value: List[str] (payloads)

    Thread-safe via Python GIL for this use case.
    """

    def __init__(self, ttl: int = LLM_PAYLOAD_CACHE_TTL):
        self._cache: dict[str, tuple] = {}  # key -> (payloads, expiry)
        self.ttl = ttl

    def get(self, key: str) -> list[str] | None:
        """Get cached payloads if not expired."""
        if key in self._cache:
            payloads, expiry = self._cache[key]
            if time.time() < expiry:
                return payloads
            else:
                del self._cache[key]
        return None

    def set(self, key: str, payloads: list[str]):
        """Cache payloads with TTL."""
        self._cache[key] = (payloads, time.time() + self.ttl)

    def clear(self):
        """Clear all cached payloads."""
        self._cache.clear()


class LLMPayloadGenerator:
    """
    Generates context-aware probe payloads using LLM.

    Extracts endpoint context (param type, reflection context, framework)
    and generates targeted payloads that static lists miss.

    Results are cached by context fingerprint to avoid redundant LLM calls.
    """

    PAYLOAD_PROMPT = """You are a penetration testing payload generator. Generate {vuln_class} test payloads.

Target Context:
- Parameter name: {param_name}
- Reflection context: {context_type}
  (The parameter value will be placed in this HTML/JSON/JS context)
- Framework hints: {framework_hints}
- Current parameter value: {current_value}

Your payloads MUST:
1. Be syntactically valid for the injection context
2. Include a unique marker "{callback_marker}" for detection
3. Cover edge cases the standard payloads miss
4. Be progressively more complex (simple -> sophisticated)

Context-specific guidelines:
- href context: Use "javascript:..." or break out of quotes with "><...
- script context: Use </script><script> or JSON encoding tricks
- JSON value: Break string with \\" or use unicode escapes
- HTML attribute: Break out with " or ' followed by event handlers
- HTML body: Direct injection of tags

Examples of good context-aware payloads:
- href: "javascript:alert('{callback_marker}')"
- script: "</script><img src=x onerror=alert('{callback_marker}')>"
- JSON: "\\"-alert(1)-\\""
- attribute: " onfocus=alert({callback_marker}) autofocus=a

Return ONLY a JSON array of strings with exactly 3 payloads:
["payload_1", "payload_2", "payload_3"]"""

    # Reflection context detection patterns
    CONTEXT_PATTERNS = {
        "href": [
            r'href\s*=\s*["\'][^"\']*({param_pattern})[^"\']*["\']',
            r'href\s*=\s*(?:https?://)?[^"\'\s]*({param_pattern})',
        ],
        "src": [
            r'src\s*=\s*["\'][^"\']*({param_pattern})[^"\']*["\']',
        ],
        "script": [
            r'<script[^>]*>[^<]*({param_pattern})[^<]*</script>',
            r'<script[^>]*>\s*var\s+\w+\s*=\s*["\'][^"\']*({param_pattern})',
        ],
        "json_value": [
            r'["\']\w+["\']\s*:\s*["\'][^"\']*({param_pattern})[^"\']*["\']',
        ],
        "html_attribute": [
            r'<[^>]*\s+\w+\s*=\s*["\'][^"\']*({param_pattern})[^"\']*["\']',
        ],
        "html_body": [
            r'<[^>]*>(?:[^<]*)({param_pattern})(?:[^<]*)<',
            r'>({param_pattern})<',
        ],
    }

    def __init__(
        self,
        llm_client: Any,
        model: str | None = None,
        cache: PayloadCache | None = None,
        max_payloads: int = LLM_MAX_GENERATED_PAYLOADS,
    ):
        """
        Initialize LLM Payload Generator.

        Args:
            llm_client: LLMClient instance
            model: Model to use (defaults to LLM_PAYLOAD_GENERATION_MODEL or client's model)
            cache: Optional PayloadCache instance (creates one if not provided)
            max_payloads: Max payloads to generate per context (default 2)
        """
        self.llm = llm_client
        self.model = model or LLM_PAYLOAD_GENERATION_MODEL or getattr(llm_client, 'model', 'gpt-4o-mini')
        self.cache = cache or PayloadCache()
        self.max_payloads = max_payloads

    def is_available(self) -> bool:
        """Check if LLM is configured for payload generation."""
        return (
            LLM_PAYLOAD_GENERATION_ENABLED
            and self.llm.is_available()
        )

    def generate_sync(
        self,
        vuln_class: str,
        param_name: str,
        response_snippet: str = "",
        framework_hints: str | None = None,
    ) -> list[str]:
        """
        Generate context-aware payloads (synchronous).

        Used by scan-phase code. Returns cached payloads on cache hit,
        generates new ones on miss. Always returns at most max_payloads items.

        Args:
            vuln_class: Vulnerability class (e.g., "XSS", "SSTI", "SQL_INJECTION")
            param_name: The parameter name being tested
            response_snippet: First ~500 chars of the HTTP response for context inference
            framework_hints: Optional framework info (e.g., "Django", "React", "Express")

        Returns:
            List of payload strings (empty on failure or if LLM unavailable)
        """
        slog = ScanLogger("llm_payload_generator")
        slog.llm_start("payload_generation", vuln_class=vuln_class, param=param_name)

        try:
            if not self.is_available():
                slog.info("LLM payload generation not available")
                logger.debug("LLM payload generation not available")
                return []

            # Infer context type from response
            context_type = self._detect_reflection_context(param_name, response_snippet)

            # Build context fingerprint for caching
            fingerprint = self._build_context_fingerprint(vuln_class, param_name, response_snippet)
            cache_key = f"{vuln_class}:{fingerprint}"

            # Check cache
            cached = self.cache.get(cache_key)
            if cached is not None:
                slog.info(f"Cache hit: {cache_key}")
                logger.debug(f"LLM payload cache hit: {cache_key}")
                slog.llm_complete("payload_generation", cached=True, payloads=len(cached[:self.max_payloads]))
                return cached[:self.max_payloads]

            slog.info(f"Cache miss: {cache_key}, generating payloads...")

            # Generate callback marker for detection
            callback = f"LLM_{hashlib.md5(fingerprint.encode()).hexdigest()[:8]}"

            # Build prompt
            prompt_text = self.PAYLOAD_PROMPT.format(
                vuln_class=vuln_class,
                param_name=param_name,
                context_type=context_type,
                framework_hints=framework_hints or "unknown",
                current_value=response_snippet[:100] if response_snippet else "empty",
                callback_marker=callback,
            )

            messages = [
                {"role": "system", "content": "You are a penetration testing payload generator. Return only valid JSON arrays."},
                {"role": "user", "content": prompt_text},
            ]

            # Call LLM (sync)
            raw_response = self.llm.chat_sync(
                messages=messages,
                temperature=0.3,
                max_tokens=300,
                response_format={"type": "json_object"},
            )

            response_text = raw_response.text if hasattr(raw_response, "text") else raw_response

            # Parse payloads
            payloads = self._parse_payloads(response_text)

            # Inject callback marker into payloads (ensure detectability)
            payloads = [p.replace(callback, callback) for p in payloads]

            # Cache
            if payloads:
                self.cache.set(cache_key, payloads)
                slog.info(f"Generated {len(payloads)} payloads for {cache_key}")
                logger.debug(f"Generated {len(payloads)} LLM payloads for {cache_key}")

            slog.llm_complete("payload_generation", payloads=len(payloads[:self.max_payloads]))
            return payloads[:self.max_payloads]

        except Exception as e:
            slog.warn(f"LLM payload generation failed: {e}")
            logger.warning(f"LLM payload generation failed: {e}")
            return []

    def _detect_reflection_context(
        self,
        param_name: str,
        response_snippet: str,
    ) -> str:
        """
        Detect where in the HTML/JSON/JS response the parameter value
        would be reflected. Uses pattern matching against the response.

        Returns: "href", "src", "script", "json_value", "html_attribute", "html_body", or "unknown"
        """
        if not response_snippet:
            return "html_body"  # Default: assume HTML body context

        # Try to find the param name in the response and infer context
        for context_type, patterns in self.CONTEXT_PATTERNS.items():
            for pattern in patterns:
                try:
                    escaped_param = re.escape(param_name)
                    compiled = re.compile(pattern.format(param_pattern=escaped_param), re.IGNORECASE)
                    if compiled.search(response_snippet):
                        return context_type
                except re.error:
                    continue

        # Check content type hints
        if '"' in response_snippet[:100] and '{' in response_snippet[:100]:
            return "json_value"
        if '<script' in response_snippet.lower():
            return "script"

        return "html_body"  # Default fallback

    def _build_context_fingerprint(
        self,
        vuln_class: str,
        param_name: str,
        response_snippet: str,
    ) -> str:
        """
        Build a fingerprint of the injection context for caching.

        Uses: param name pattern (numeric/text/uuid), content type hints,
        framework indicators, context type.
        """
        # Classify param name
        if re.match(r'^[0-9]+$', param_name):
            param_type = "numeric"
        elif re.match(r'^[a-f0-9-]{36}$', param_name.lower()):
            param_type = "uuid"
        elif re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', param_name):
            param_type = "word"
        else:
            param_type = "other"

        # Detect context
        context = self._detect_reflection_context(param_name, response_snippet)

        # Check for framework hints in response
        framework = "unknown"
        snippet_lower = response_snippet.lower() if response_snippet else ""
        if "django" in snippet_lower:
            framework = "django"
        elif "laravel" in snippet_lower or "livewire" in snippet_lower:
            framework = "laravel"
        elif "spring" in snippet_lower or "javax" in snippet_lower:
            framework = "spring"
        elif "express" in snippet_lower or "node" in snippet_lower:
            framework = "express"
        elif "asp.net" in snippet_lower or "aspnet" in snippet_lower or "viewstate" in snippet_lower:
            framework = "aspnet"
        elif "rails" in snippet_lower or "ruby" in snippet_lower:
            framework = "rails"

        # Build hashable fingerprint
        raw = f"{vuln_class}|{param_name}|{param_type}|{context}|{framework}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _parse_payloads(self, raw_text: str) -> list[str]:
        """
        Parse LLM response into list of payload strings.

        Attempts JSON parsing, falls back to line-by-line extraction.
        """
        # Try JSON parsing
        try:
            # Extract JSON array from markdown code blocks
            json_match = re.search(r'```(?:json)?\s*\n?(\[[\s\S]*?\])\n?```', raw_text, re.DOTALL)
            if json_match:
                raw_text = json_match.group(1)

            # Also try extracting bare JSON array
            array_match = re.search(r'\[[\s\S]*\]', raw_text)
            if array_match:
                raw_text = array_match.group()

            payloads = json.loads(raw_text.strip())
            if isinstance(payloads, list):
                # Filter to strings only, strip whitespace
                return [str(p).strip() for p in payloads if isinstance(p, str) and p.strip()]
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Failed to parse payloads as JSON: {e}")

        # Fallback: line-by-line extraction
        lines = []
        for line in raw_text.split('\n'):
            line = line.strip().strip('"').strip("'").strip(',')
            if line and not line.startswith('[') and not line.startswith(']') and not line.startswith('```'):
                lines.append(line)

        return lines[:5]  # Max 5 fallback payloads
