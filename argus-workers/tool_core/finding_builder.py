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
            "SQLI",
            "PARAM_DISCOVERY",
            "WEBSOCKET_ORIGIN_BYPASS",
            "WEBSOCKET_NO_AUTH",
            "WEBSOCKET_INJECTION",
            "WEBSOCKET_NO_RATE_LIMIT",
            "API_BOLA",
            "API_MASS_ASSIGNMENT",
            "API_AUTH_BYPASS",
            "API_RATE_LIMITED",
            "API_NO_RATE_LIMIT",
            "API_RATE_LIMIT_INCONCLUSIVE",
            # Scanner-emitted types added for autonomous compatibility
            "EXPOSED_SECRET",
            "MISSING_API_SECURITY_HEADERS",
            "WILDCARD_CORS_API",
            "GRAPHQL_INTROSPECTION_ENABLED",
            "GRAPHQL_DEPTH_LIMIT_MISSING",
            "EXPOSED_OPENAPI_SPEC",
            "VERBOSE_API_ERROR",
            "MISSING_AUTHENTICATION",
            "JWT_ALG_NONE",
            "JWT_HMAC_ALGORITHM",
            "JWT_PRIVILEGE_ESCALATION",
            "JWT_LLM_DETECTED_WEAKNESS",
            "WEAK_API_KEY",
            "CONFIRMED_BOLA",
            "POTENTIAL_BOLA",
            "BOPLA_SENSITIVE_FIELDS",
            "ATTACK_SURFACE",
            "SUBDOMAIN",
            "MISSING_RATE_LIMITING",
            "BOLA",
            "STORED_XSS",
            "BLIND_XSS",
            "DOM_XSS",
            "BLIND_SQLI",
            "TIME_BASED_SQLI",
            "ERROR_SQLI",
            "PATH_TRAVERSAL",
            "DIRECTORY_TRAVERSAL",
            "COMMITTED_SECRET",
            # Scanner/recon types from parsers and scanners
            "SCAN_RESULT",
            "PROMPT_INJECTION",
            "AI_INFORMATION_DISCLOSURE",
            "SECRET_EXPOSURE",
            "SASTFinding",
            "CREDENTIAL_REPLAY_SUCCESS",
            "INTERNAL_SERVICE_DISCOVERY",
            "EXPOSED_DEBUG_ENDPOINT",
            "PARAMETER_FUZZ_500",
            "PARAMETER_REFLECTION",
            "POST_FUZZ_500",
            "LICENSE_COMPLIANCE",
            "STATIC_ANALYSIS_FINDING",
            "SNYK_VULNERABILITY",
            "EXPOSED_PRIVATE_KEY",
            "EXPOSED_ENV_FILE",
            "EXPOSED_CONFIG_SECRET",
            "DEPENDENCY_LISTING",
            "WAF_DETECTED",
            "TECHNOLOGY_DETECTED",
            "DEPENDENCY_VULNERABILITY",
            "CODE_VULNERABILITY",
            "TLS_VULNERABILITY",
            "WEB_SERVER_VULNERABILITY",
            "CRAWLED_ENDPOINT",
            "DISCOVERED_ENDPOINT",
            "JWT_VULNERABILITY",
            "HTTP_ENDPOINT",
            "SECRET_LEAK",
            "KNOWN_URL",
            "HISTORICAL_URL",
            "DIRECTORY_FOUND",
            "SUBDOMAIN_DISCOVERY",
            "GENERIC_FINDING",
            "CVE_REFERENCE",
            "RAW_OUTPUT",
            "WP_CORE_VULNERABILITY",
            "USER_ENUMERATION",
            "WP_VULNERABILITY_CORE",
            "WP_VULNERABILITY_PLUGIN",
            "WP_VULNERABILITY_THEME",
            # Web scanner checks (web_scanner.py)
            "POST_PARAMETER_REFLECTION",
            # WebSocket scanner
            "WEBSOCKET_RATE_LIMITED",
            # Browser security operator
            "FILE_UPLOAD_FORM",
            "MISSING_CSRF_TOKEN",
            "AUTH_DETECTED",
            "MISSING_X_FRAME_OPTIONS",
            "MISSING_X_CONTENT_TYPE_OPTIONS",
            # Infrastructure security analyzer
            "INFRA_SERVER_HEADER",
            "INFRA_VIA_HEADER",
            "INFRA_INFO_DISCLOSURE",
            "INFRA_WEB_SERVER",
            "TF_PUBLIC_ACL",
            "TF_OPEN_SG",
            "K8S_PRIVILEGED",
            "K8S_HOST_NETWORK",
            "DOCKER_LATEST_TAG",
            "DOCKER_SECRETS_IN_ENV",
            # Threat intelligence
            "DOMAIN_NOT_RESOLVED",
            "CERTIFICATE",
            # Orchestration/status events
            "ORCHESTRATION_PLAN",
            "PHASE_STARTED",
            "PHASE_COMPLETE",
            "VERIFICATION_RECOMMENDED",
            "ORCHESTRATION_COMPLETE",
            "VERIFICATION_SUMMARY",
            "ATTACK_PATHS",
            "REPORT_GENERATED",
            "ENGAGEMENT_ANALYTICS",
            "EVIDENCE_SUMMARY",
            "CWE_KNOWLEDGE",
            "OWASP_MAPPING",
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
            logger.warning(
                "Unknown finding type %r — normalizing to GENERIC_FINDING. "
                "Add %r to KNOWN_VULN_TYPES to suppress this warning.",
                finding_type, finding_type,
            )
            finding_type = "GENERIC_FINDING"

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
