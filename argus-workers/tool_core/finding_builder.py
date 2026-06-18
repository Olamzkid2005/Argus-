"""
tool_core/finding_builder.py — FindingBuilder

Standardized finding creation for all scanners. Replaces the ad-hoc
``_add_finding()`` patterns found across WebScanner, APIScanner,
WebSocketScanner, etc.

Benefits:
    - All findings have identical schema (no more ad-hoc key differences)
    - Required fields enforced at construction time
    - Optional ``emit_finding`` callback handled automatically
    - Evidence sanitization applied automatically
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class FindingBuilder:
    """
    Standardized finding creation for all scanners.

    Each scanner gets a ``FindingBuilder`` instance. Instead of manually
    constructing dicts with ``_add_finding()``, scanners call::

        builder.vulnerability("XSS", "HIGH", endpoint, evidence, confidence=0.8)
        builder.info("PARAMETER_DISCOVERY", endpoint, evidence)

    Args:
        source_tool: Name of the tool creating the finding.
        engagement_id: Optional engagement UUID for streaming.
        emit_finding: Optional callback(engagement_id, finding_dict, tool_name).
    """

    # Severity → allowed values
    SEVERITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"})

    KNOWN_VULN_TYPES = frozenset(
        {
            "XSS",
            "SQL_INJECTION",
            "COMMAND_INJECTION",
            "SSTI",
            "LFI",
            "XXE",
            "SSRF",
            "IDOR",
            "CSRF",
            "OPEN_REDIRECT",
            "HOST_HEADER_INJECTION",
            "CACHE_POISONING",
            "HTTP_REQUEST_SMUGGLING",
            "PROTOTYPE_POLLUTION",
            "JWT_ALGORITHM_CONFUSION",
            "INSECURE_COOKIE",
            "MISSING_SECURITY_HEADERS",
            "MISSING_CSP",
            "WEAK_CSP",
            "WILDCARD_CORS",
            "REFLECTED_ORIGIN_CORS",
            "REFLECTED_XSS",
            "DOM_BASED_XSS",
            "CORS_MISCONFIGURATION",
            "AUTH_BYPASS",
            "SESSION_FIXATION",
            "RATE_LIMIT_BYPASS",
            "INFO_LEAKAGE",
            "DIRECTORY_LISTING",
            "WEAK_TLS",
            "DEPRECATED_TLS",
            "MISSING_HSTS",
            "PARAMETER_DISCOVERY",
            "HIDDEN_ENDPOINT",
            "OPEN_PORT",
            "UNENCRYPTED_SERVICE",
            "DEFAULT_CREDENTIALS",
            "MISSING_AUTH",
            "MASS_ASSIGNMENT",
            "NOSQL_INJECTION",
            "LDAP_INJECTION",
            "XPATH_INJECTION",
            "UNVALIDATED_REDIRECT",
            "SSL_CERTIFICATE_ERROR",
            "NULL_ORIGIN_CORS",
            "HTTP_VERB_TAMPERING",
            "EXPOSED_SENSITIVE_FILE",
            "CORRELATION_SUMMARY",
            "CORRELATION_GROUP",
            "TREND_ANALYSIS",
            "PATTERN_DETECTION",
        }
    )

    def __init__(
        self,
        source_tool: str,
        engagement_id: str = "",
        emit_finding: Callable[[str, dict, str], None] | None = None,
    ) -> None:
        self.source_tool = source_tool
        self.engagement_id = engagement_id
        self.emit_finding = emit_finding
        self._findings: list[dict[str, Any]] = []

    def add(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
        **extra: Any,
    ) -> dict[str, Any]:
        """
        Create and register a finding.

        Args:
            finding_type: Uppercase type string (e.g., ``"XSS"``, ``"SQL_INJECTION"``).
            severity: One of ``CRITICAL``, ``HIGH``, ``MEDIUM``, ``LOW``, ``INFO``.
            endpoint: The affected URL or resource path.
            evidence: Dict with details (sanitized automatically).
            confidence: 0.0 to 1.0.
            **extra: Additional fields merged into the finding dict.

        Returns:
            The constructed finding dict (for inspection, not modification).
        """
        severity_upper = severity.upper()
        if severity_upper not in self.SEVERITIES:
            raise ValueError(
                f"Invalid severity: {severity!r}. Must be one of {self.SEVERITIES}"
            )

        if finding_type not in self.KNOWN_VULN_TYPES:
            raise ValueError(
                f"Unknown finding type: {finding_type!r}. "
                f"Must be one of known vulnerability types."
            )

        finding: dict[str, Any] = {
            "type": finding_type,
            "severity": severity_upper,
            "endpoint": endpoint,
            "evidence": self._sanitize(evidence),
            "confidence": min(max(confidence, 0.0), 1.0),
            "source_tool": self.source_tool,
        }
        if extra:
            finding.update(extra)

        self._findings.append(finding)

        # Real-time streaming via callback
        if self.emit_finding and self.engagement_id:
            try:
                self.emit_finding(self.engagement_id, finding, self.source_tool)
            except Exception:
                logger.warning(
                    "Failed to emit finding via callback for engagement %s",
                    self.engagement_id,
                    exc_info=True,
                )

        return finding

    # ── Convenience methods ──────────────────────────────────────────

    def vulnerability(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        """Convenience: same as ``add()`` with severity validation enforced."""
        return self.add(finding_type, severity, endpoint, evidence, confidence)

    def info(self, finding_type: str, endpoint: str, evidence: dict) -> dict[str, Any]:
        """Add an INFO-level finding."""
        return self.add(finding_type, "INFO", endpoint, evidence, confidence=0.8)

    # ── Collection access ────────────────────────────────────────────

    @property
    def findings(self) -> list[dict[str, Any]]:
        """Return a copy of the findings list."""
        return list(self._findings)

    @findings.setter
    def findings(self, value: list[dict]) -> None:
        """Allow direct assignment for backward compat during migration.

        Applies sanitization to each finding to ensure consistent schema (L2).
        """
        self._findings = []
        for item in value:
            if isinstance(item, dict):
                finding = {
                    "type": item.get("type", "UNKNOWN"),
                    "severity": item.get("severity", "INFO").upper(),
                    "endpoint": item.get("endpoint", ""),
                    "evidence": self._sanitize(item.get("evidence", {})),
                    "confidence": min(max(item.get("confidence", 0.8), 0.0), 1.0),
                    "source_tool": item.get("source_tool", self.source_tool),
                }
                # Pass through extra keys
                for k, v in item.items():
                    if k not in finding:
                        finding[k] = v
                self._findings.append(finding)

    def clear(self) -> None:
        """Clear all collected findings."""
        self._findings.clear()

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _sanitize(evidence: dict) -> dict:
        """Sanitize evidence before storing (redact secrets, trim size)."""
        try:
            from utils.sanitization import sanitize_evidence
        except ImportError:
            raise RuntimeError(
                "Sanitization module required but not available"
            ) from None

        return sanitize_evidence(evidence)
