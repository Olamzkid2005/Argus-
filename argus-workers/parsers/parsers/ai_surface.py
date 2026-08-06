"""
Parser for ai-surface JSON output (ai-surface scan . --output json).

Maps ai-surface's 8 detection categories and verdict system into Argus's
VulnerabilityFinding schema, with graduated confidence scores derived from
the ai-surface verdict (confirmed/likely/inventory).
"""

import json
import logging
import re
from typing import Any

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Mapping from ai-surface categories to Argus finding type prefixes
CATEGORY_TYPE_PREFIX: dict[str, str] = {
    "mcp-server": "AI_SURFACE_MCP_SERVER",
    "agent-framework": "AI_SURFACE_AGENT_FRAMEWORK",
    "llm-sdk": "AI_SURFACE_LLM_SDK",
    "env-key": "AI_SURFACE_ENV_KEY",
    "model-gateway": "AI_SURFACE_MODEL_GATEWAY",
    "ai-infra": "AI_SURFACE_AI_INFRA",
    "api": "AI_SURFACE_API",
    "vector-store": "AI_SURFACE_VECTOR_STORE",
}

# Severity mapping: ai-surface lowercase → Argus uppercase
SEVERITY_MAP: dict[str, str] = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFO",
}

# Confidence ranges based on verdict
# CONFIRMED: unambiguous code/config fact → 0.85-0.95
# LIKELY: inferred, needs review → 0.4-0.6
VERDICT_CONFIRMED_RANGE = (0.85, 0.95)
VERDICT_LIKELY_RANGE = (0.4, 0.6)
DEFAULT_CONFIDENCE = 0.5


def _compute_confidence(
    verdict: str | None,
    severity: str | None,
    has_risk_indicators: bool,
) -> float:
    """Map ai-surface verdict to a graduated confidence score.

    Uses severity as a scaling factor within each verdict range.
    """
    sev_rank = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
    scale = sev_rank.get(severity, 0.5) if severity else 0.5

    if verdict == "confirmed":
        lo, hi = VERDICT_CONFIRMED_RANGE
        return lo + (hi - lo) * scale
    elif verdict == "likely":
        lo, hi = VERDICT_LIKELY_RANGE
        return lo + (hi - lo) * scale
    elif has_risk_indicators:
        return 0.5
    return DEFAULT_CONFIDENCE


def _extract_endpoint(finding: dict) -> str:
    """Extract endpoint from ai-surface finding.

    For source code findings (MCP, agents), use the file path.
    For API findings, use the method + path.
    """
    evidence = finding.get("evidence", {}) or {}
    files = evidence.get("files", [])
    metadata = evidence.get("metadata", {}) or {}

    category = finding.get("category", "")
    if category == "api":
        method = metadata.get("method", "?")
        path = metadata.get("path", "")
        if method and path:
            return f"{method} {path}"
        # Reached only when method/path pair is incomplete — fall back to
        # whatever we have. Note: Python evaluates `a or b if c else d` as
        # `(a or b) if c else d`, which wrongly returned "UNKNOWN" when a
        # path was known but no files existed. Parenthesize explicitly.
        return (path or (files[0] if files else "")) or "UNKNOWN"

    if files:
        return f"file:{files[0]}"
    return "UNKNOWN"


# Metadata keys that may carry secrets / provider credentials and must be
# redacted from finding evidence. Matched case-insensitively on key name
# (substring match so e.g. "api_key", "AWS_SECRET", "auth_token" are caught).
_SENSITIVE_METADATA_SUBSTRINGS = (
    "secret", "token", "password", "passwd", "api_key", "apikey",
    "credential", "authorization", "bearer", "private_key",
    "access_key", "aws_", "azure_", "openai_", "anthropic_",
    "gemini_", "provider_key",
)


def _redact_metadata(metadata: dict) -> dict:
    """Copy metadata, dropping keys that look like credentials/secrets.

    ai-surface findings can surface exposed AI-provider keys; those raw
    values must not land in evidence verbatim.
    """
    return {
        k: v
        for k, v in metadata.items()
        if not any(s in k.lower() for s in _SENSITIVE_METADATA_SUBSTRINGS)
    }


def _build_evidence(finding: dict) -> dict:
    """Build structured evidence from the ai-surface finding."""
    evidence = finding.get("evidence", {}) or {}
    audit = finding.get("audit")

    result: dict[str, Any] = {
        "surface": finding.get("surface", ""),
        "category": finding.get("category", ""),
        "detector_name": finding.get("detector_name", ""),
        "disposition": finding.get("disposition", ""),
        "runtime_status": finding.get("runtime_status"),
        "runtime_question": finding.get("runtime_question"),
        "verdict": finding.get("verdict"),
        "files": evidence.get("files", []),
        "snippet": evidence.get("snippet", ""),
        "risk_indicators": finding.get("risk_indicators", []),
        "permissions": finding.get("permissions", []),
    }

    # Add audit details if present (deep-dive findings)
    if audit:
        result["audit"] = {
            "risk_flags": audit.get("risk_flags", []),
            "secrets": audit.get("secrets", []),
            "trust_score": audit.get("trust_score"),
            "trust_label": audit.get("trust_label", ""),
            "owasp_mappings": audit.get("owasp_mappings", []),
        }

    # Add bridges if present
    bridges = finding.get("bridges", [])
    if bridges:
        result["bridges"] = bridges

    # Include relevant metadata fields (redacted: no secrets/credentials)
    metadata = evidence.get("metadata", {}) or {}
    if metadata:
        result["metadata"] = _redact_metadata(metadata)

    return result


def _sanitize_type_name(name: str) -> str:
    """Convert a surface name to a safe type suffix.

    Example: "MCP Server: stripe-mcp" → "MCP_SERVER_STRIPE_MCP"
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_ ]", "", name)
    sanitized = sanitized.strip().replace(" ", "_")
    return sanitized.upper()[:80]


class AISurfaceParser(BaseParser):
    """Parser for ai-surface JSON output: `ai-surface scan . --output json`."""

    def parse(self, raw_output: str) -> list[dict]:
        """Parse ai-surface JSON output into Argus finding dicts.

        Args:
            raw_output: The raw JSON string from ai-surface --output json.

        Returns:
            List of finding dicts conforming to VulnerabilityFinding schema.
        """
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.warning("ai-surface parser: invalid JSON: %s", e)
            return []

        findings: list[dict[str, Any]] = []
        schema_version = data.get("schema_version", "1.0")
        tool_version = data.get("tool_version", "unknown")

        for item in data.get("findings", []):
            category = item.get("category", "unknown")
            type_prefix = CATEGORY_TYPE_PREFIX.get(category, "AI_SURFACE")
            severity_raw = item.get("severity")
            severity = SEVERITY_MAP.get(severity_raw, "INFO") if severity_raw else "INFO"
            verdict = item.get("verdict")
            risk_indicators = item.get("risk_indicators", [])

            # Derive type from category + surface name (sanitized)
            surface = item.get("surface", "UNKNOWN")
            finding_type = f"{type_prefix}_{_sanitize_type_name(surface)}"

            confidence = _compute_confidence(verdict, severity_raw, bool(risk_indicators))
            endpoint = _extract_endpoint(item)
            evidence = _build_evidence(item)

            finding: dict[str, Any] = {
                "type": finding_type,
                "severity": severity,
                "confidence": confidence,
                "endpoint": endpoint,
                "evidence": evidence,
                "source_tool": "ai-surface",
                "ai_surface_verdict": verdict,
                "ai_surface_category": category,
            }
            findings.append(finding)

        logger.info(
            "ai-surface parser: parsed %d findings from schema %s (tool %s)",
            len(findings),
            schema_version,
            tool_version,
        )
        return findings
