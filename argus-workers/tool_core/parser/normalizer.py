SEVERITY_MAP = {
    "info": 0,
    "informational": 0,
    "INFO": 0,
    "INFORMATIONAL": 0,
    "low": 1,
    "LOW": 1,
    "medium": 2,
    "MEDIUM": 2,
    "high": 3,
    "HIGH": 3,
    "critical": 4,
    "CRITICAL": 4,
}

CONFIDENCE_MAP = {
    "confirmed": 5,
    "CONFIRMED": 5,
    "high": 4,
    "HIGH": 4,
    "verified": 4,
    "VERIFIED": 4,
    "medium": 3,
    "MEDIUM": 3,
    "probable": 3,
    "PROBABLE": 3,
    "low": 2,
    "LOW": 2,
    "candidate": 2,
    "CANDIDATE": 2,
    "informational": 1,
    "INFORMATIONAL": 1,
}


def _as_number(value, low: int, high: int) -> int | None:
    """Read a value that is already on the numeric scale, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        level = int(value)
        return level if low <= level <= high else None
    if isinstance(value, str) and value.strip().isdigit():
        level = int(value.strip())
        return level if low <= level <= high else None
    return None


def normalize_severity(severity_str, default: int = 2) -> int:
    """Map a severity name or number onto 0-4 (INFO..CRITICAL).

    Verifier scripts print ``"severity": 4``; reading that as a name missed the
    map and silently returned the MEDIUM default, so a confirmed finding was
    reported as MEDIUM and a clean ``"severity": 0`` result became a MEDIUM
    finding of its own.
    """
    numeric = _as_number(severity_str, 0, 4)
    if numeric is not None:
        return numeric
    if isinstance(severity_str, str):
        return SEVERITY_MAP.get(severity_str, default)
    return default


def normalize_confidence(confidence_str, default: int = 3) -> int:
    """Map a confidence name or 1-5 number onto the worker's 1-5 scale."""
    numeric = _as_number(confidence_str, 1, 5)
    if numeric is not None:
        return numeric
    if isinstance(confidence_str, str):
        return CONFIDENCE_MAP.get(confidence_str, default)
    return default
