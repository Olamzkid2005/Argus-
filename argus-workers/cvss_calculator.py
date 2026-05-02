"""
CVSS v3.1 Base Score Auto-Calculation for findings without a CVE.

Provides an approximate CVSS v3.1 base score based on finding type, severity,
and evidence strength. Used when the NVD enrichment does not return a score
(because the finding has no CVE).

NOTE: These are heuristic estimates, not certified CVSS scores.
They should be labeled "Estimated CVSS" in the UI.
"""


# CVSS v3.1 Base Score lookup — approximate, for findings without a CVE
# Based on typical CVSS v3.1 vector strings for each vulnerability type
TYPE_BASE_SCORES = {
    # Critical injection types
    "SQL_INJECTION": 9.8,  # AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
    "COMMAND_INJECTION": 9.8,
    "LDAP_INJECTION": 8.8,
    "XPATH_INJECTION": 8.8,
    # XSS variants
    "XSS": 6.1,  # AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N
    "STORED_XSS": 8.8,  # S:C (stored = no UI:R required)
    "DOM_XSS": 6.1,
    "REFLECTED_XSS": 6.1,
    # Authentication / access
    "BROKEN_AUTHENTICATION": 8.1,
    "BROKEN_ACCESS_CONTROL": 6.5,
    "IDOR": 6.5,
    "PRIVILEGE_ESCALATION": 8.8,
    "JWT_WEAKNESS": 7.5,
    "JWT_NONE_ALGORITHM": 8.1,
    "WEAK_PASSWORD_POLICY": 5.3,
    # Injection (non-SQL)
    "SSRF": 9.3,
    "XXE": 8.2,
    "SSTI": 9.8,
    "OPEN_REDIRECT": 6.1,
    "HEADER_INJECTION": 7.5,
    # Info disclosure
    "SENSITIVE_DATA_EXPOSURE": 7.5,
    "DIRECTORY_LISTING": 5.3,
    "ERROR_DISCLOSURE": 5.3,
    "PATH_DISCLOSURE": 5.3,
    "SOURCE_CODE_DISCLOSURE": 6.5,
    # Config / headers
    "MISSING_SECURITY_HEADERS": 3.7,
    "INSECURE_CORS": 6.5,
    "CSRF": 6.5,
    "CLICKJACKING": 4.7,
    # File / upload
    "FILE_UPLOAD": 8.8,
    "PATH_TRAVERSAL": 7.5,
    "LOCAL_FILE_INCLUSION": 7.5,
    "REMOTE_FILE_INCLUSION": 8.8,
    # Infra
    "EXPOSED_ADMIN": 7.2,
    "WEAK_SSL": 5.9,
    "OPEN_PORT": 5.3,
    "SERVICE_DETECTED": 3.7,
    # Technology detection
    "TECHNOLOGY_DETECTION": 2.5,
    "TECH_DETECTED": 2.5,
    # Secrets
    "EXPOSED_SECRET": 8.8,
    "COMMITTED_SECRET": 8.2,
    "HARDCODED_SECRET": 7.5,
    # Dependency
    "DEPENDENCY_VULNERABILITY": 7.5,
    "OUTDATED_DEPENDENCY": 5.9,
    # Generic
    "ENDPOINT_DISCOVERY": 2.5,
    "INFO_DISCLOSURE": 4.5,
}

SEVERITY_MULTIPLIERS = {
    "CRITICAL": 1.0,  # keep type score
    "HIGH": 0.9,
    "MEDIUM": 0.7,
    "LOW": 0.5,
    "INFO": 0.3,
}

EVIDENCE_ADJUSTMENTS = {
    "verified": 1.0,
    "strong": 0.95,
    "VERIFIED": 1.0,
    "REQUEST_RESPONSE": 0.9,
    "PAYLOAD": 0.85,
    "moderate": 0.85,
    "MINIMAL": 0.7,
    "weak": 0.7,
    "none": 0.6,
    "": 0.85,
}


def estimate_cvss(
    finding_type: str,
    severity: str,
    evidence_strength: str = "moderate",
) -> float:
    """
    Returns an approximate CVSS v3.1 base score for a finding.

    Formula: score = min(base_score × severity_multiplier × evidence_adjustment, 10.0)

    Args:
        finding_type: Type of finding (e.g., "SQL_INJECTION", "XSS")
        severity: Severity level (CRITICAL, HIGH, MEDIUM, LOW, INFO)
        evidence_strength: Evidence quality (verified, strong, moderate, weak)

    Returns:
        CVSS v3.1 base score (0.0–10.0), rounded to 1 decimal place

    NOTE: This is a heuristic estimate, not a certified CVSS score.
    """
    # Normalize inputs
    finding_type = finding_type.upper().strip() if finding_type else ""
    severity = severity.upper().strip() if severity else "INFO"
    evidence_strength = evidence_strength.strip() if evidence_strength else "moderate"

    # Look up base score, default to 5.0 (medium)
    base = TYPE_BASE_SCORES.get(finding_type, 5.0)

    # Apply severity multiplier
    multiplier = SEVERITY_MULTIPLIERS.get(severity, 0.7)

    # Apply evidence adjustment
    adj = EVIDENCE_ADJUSTMENTS.get(evidence_strength, 0.85)

    # Calculate final score
    score = round(min(base * multiplier * adj, 10.0), 1)

    return score


def get_cvss_label(has_cve: bool = False) -> str:
    """
    Returns the appropriate label for the CVSS score.

    Args:
        has_cve: True if the finding has an NVD-enriched CVE score

    Returns:
        "CVSS (NVD)" if has_cve, "Estimated CVSS" otherwise
    """
    return "CVSS (NVD)" if has_cve else "Estimated CVSS"
