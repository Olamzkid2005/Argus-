"""Pydantic schema for nuclei parser output validation."""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# We use typed dicts instead of pydantic to avoid adding a dependency.
# If pydantic is available, it can be swapped in later.

NUCLEI_REQUIRED_FIELDS = {"template-id", "matched-at", "info"}
NUCLEI_OPTIONAL_FIELDS = {"matcher-name", "extracted-results", "curl-command", "timestamp", "type", "host", "ip"}


def validate_nuclei_finding(data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Validate a single nuclei finding line.

    Returns the validated dict (possibly with defaults filled in)
    or None if the data is invalid.
    """
    # Check required top-level fields
    if not data.get("template-id") or not data.get("matched-at"):
        logger.warning("Nuclei finding missing required fields: template-id or matched-at")
        return None

    info = data.get("info")
    if not info or not isinstance(info, dict):
        logger.warning("Nuclei finding missing 'info' field")
        return None

    # Validate info sub-fields
    if not info.get("name"):
        logger.warning("Nuclei finding info missing 'name'")
        return None

    severity = (info.get("severity") or "info").upper()
    valid_severities = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
    if severity not in valid_severities:
        logger.warning(f"Invalid severity '{severity}', defaulting to INFO")
        severity = "INFO"

    # Build validated output
    validated = {
        "type": info.get("name", "UNKNOWN"),
        "severity": severity,
        "endpoint": data.get("matched-at", ""),
        "tool": "nuclei",
        "evidence": {
            "template_id": data.get("template-id"),
            "matcher_name": data.get("matcher-name"),
            "extracted_results": data.get("extracted-results", []),
            "curl_command": data.get("curl-command"),
        },
        "raw_output": data,  # Store raw for debugging
    }

    return validated
