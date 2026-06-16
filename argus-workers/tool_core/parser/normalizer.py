SEVERITY_MAP = {
    "info": 0, "informational": 0, "INFO": 0, "INFORMATIONAL": 0,
    "low": 1, "LOW": 1,
    "medium": 2, "MEDIUM": 2,
    "high": 3, "HIGH": 3,
    "critical": 4, "CRITICAL": 4,
}

CONFIDENCE_MAP = {
    "confirmed": 5, "CONFIRMED": 5,
    "high": 4, "HIGH": 4, "verified": 4, "VERIFIED": 4,
    "medium": 3, "MEDIUM": 3, "probable": 3, "PROBABLE": 3,
    "low": 2, "LOW": 2, "candidate": 2, "CANDIDATE": 2,
    "informational": 1, "INFORMATIONAL": 1,
}


def normalize_severity(severity_str: str, default: int = 2) -> int:
    return SEVERITY_MAP.get(severity_str, default)


def normalize_confidence(confidence_str: str, default: int = 3) -> int:
    return CONFIDENCE_MAP.get(confidence_str, default)
