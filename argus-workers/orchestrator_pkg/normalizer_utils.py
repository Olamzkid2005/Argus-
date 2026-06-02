"""
Standalone normalize_finding function.

Extracted from Orchestrator._normalize_finding and ToolContext._normalize_finding
to provide a single shared implementation used by all callers.
"""

import logging

from parsers.normalizer import FindingNormalizer

logger = logging.getLogger(__name__)


def normalize_finding(
    normalizer: FindingNormalizer,
    raw_finding: dict,
    tool: str,
) -> dict | None:
    """Normalize a raw finding into a standard dict format.

    Uses the provided FindingNormalizer instance to validate and standardize
    the finding, then returns a dict with consistent keys: type, severity,
    endpoint, evidence, confidence, source_tool.

    Returns None if normalization fails (exception caught and logged).
    """
    try:
        finding = normalizer.normalize(raw_finding, tool)
        return {
            "type": finding.type,
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
