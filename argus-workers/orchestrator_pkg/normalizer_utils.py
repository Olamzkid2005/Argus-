"""
Standalone normalize_finding function.

Extracted from Orchestrator._normalize_finding and ToolContext._normalize_finding
to provide a single shared implementation used by all callers.
"""

import logging

from parsers.normalizer import FindingNormalizer

logger = logging.getLogger(__name__)


# Readable fallbacks for finding types that parsers emit without a title.
# Every finding needs a non-empty title: findings.title is NOT NULL in the
# Postgres schema and reports render it directly.
_TITLE_FALLBACKS: dict[str, str] = {
    "OPEN_PORT": "Open port detected",
    "CRAWLED_ENDPOINT": "Endpoint discovered",
    "GENERIC_FINDING": "Generic finding",
    "TECH_DETECTED": "Technology detected",
    "SUBDOMAIN": "Subdomain discovered",
    "EXPOSED_SERVICE": "Exposed service",
}


def _derive_title(finding_type: str) -> str:
    """Return a readable title for a finding type that has none.

    Keeps the pipeline honest for the many low-level parsers (naabu, katana,
    httpx, ...) that report a type and endpoint but no human-readable title.
    """
    if not finding_type:
        return "Untitled finding"
    fallback = _TITLE_FALLBACKS.get(finding_type.upper())
    if fallback:
        return fallback
    # "SQL_INJECTION" -> "Sql injection"
    words = finding_type.replace("_", " ").replace("-", " ").strip()
    if not words:
        return "Untitled finding"
    return words[:1].upper() + words[1:].lower()


def normalize_finding(
    normalizer: FindingNormalizer,
    raw_finding: dict,
    tool: str,
) -> dict | None:
    """Normalize a raw finding into a standard dict format.

    Uses the provided FindingNormalizer instance to validate and standardize
    the finding, then returns a dict with consistent keys: type, title,
    severity, endpoint, evidence, confidence, source_tool.

    The parser's own ``title`` is preserved. Parsers that report no title (most
    low-level scanners) get a readable one derived from the type, so findings
    never reach the database or a report with an empty title.

    Returns None if normalization fails (exception caught and logged).
    """
    try:
        finding = normalizer.normalize(raw_finding, tool)
        # The Finding model has no title field, so take it from the raw parser
        # output and fall back to a derived label when the parser omitted one.
        title = str(raw_finding.get("title") or "").strip()
        return {
            "type": finding.type,
            "title": title or _derive_title(finding.type),
            "severity": (
                finding.severity.value
                if hasattr(finding.severity, "value")
                else finding.severity
            ),
            "endpoint": finding.endpoint,
            "evidence": finding.evidence,
            "confidence": finding.confidence,
            "source_tool": tool,
        }
    except Exception as e:
        logger.warning("Failed to normalize finding: %s", e)
        return None
