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
    # ── Critical injection types ──────────────────────────────────
    "SQL_INJECTION": 9.8,  # AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
    "COMMAND_INJECTION": 9.8,
    "SSTI": 9.8,
    "SSRF": 9.3,
    "XXE": 8.2,
    "LDAP_INJECTION": 8.8,
    "XPATH_INJECTION": 8.8,
    "NOSQL_INJECTION": 8.8,
    "HEADER_INJECTION": 7.5,
    "HOST_HEADER_INJECTION": 7.5,

    # ── SQLi aliases (scanner-emitted variants) ───────────────────
    "SQLI": 9.8,
    "BLIND_SQLI": 8.0,
    "TIME_BASED_SQLI": 8.0,
    "ERROR_SQLI": 8.0,

    # ── XSS variants ─────────────────────────────────────────────
    "XSS": 6.1,  # AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N
    "STORED_XSS": 8.8,  # S:C (stored = no UI:R required)
    "DOM_XSS": 6.1,
    "REFLECTED_XSS": 6.1,
    "BLIND_XSS": 6.1,
    "DOM_BASED_XSS": 6.1,
    "POST_REFLECTED_XSS": 6.1,

    # ── Authentication / access ──────────────────────────────────
    "BROKEN_AUTHENTICATION": 8.1,
    "BROKEN_ACCESS_CONTROL": 6.5,
    "AUTH_BYPASS": 8.1,
    "MISSING_AUTH": 8.1,
    "MISSING_AUTHENTICATION": 8.1,
    "IDOR": 6.5,
    "BOLA": 6.5,
    "API_BOLA": 6.5,
    "CONFIRMED_BOLA": 8.1,
    "POTENTIAL_BOLA": 6.5,
    "BOPLA_SENSITIVE_FIELDS": 6.5,
    "PRIVILEGE_ESCALATION": 8.8,
    "DEFAULT_CREDENTIALS": 7.5,
    "SESSION_FIXATION": 6.5,

    # ── JWT ──────────────────────────────────────────────────────
    "JWT_WEAKNESS": 7.5,
    "JWT_NONE_ALGORITHM": 8.1,
    "JWT_ALGORITHM_CONFUSION": 8.1,
    "JWT_ALG_NONE": 8.1,
    "JWT_HMAC_ALGORITHM": 8.1,
    "JWT_PRIVILEGE_ESCALATION": 8.8,
    "JWT_LLM_DETECTED_WEAKNESS": 7.5,
    "WEAK_PASSWORD_POLICY": 5.3,
    "WEAK_API_KEY": 5.3,

    # ── Web / transport ──────────────────────────────────────────
    "OPEN_REDIRECT": 6.1,
    "UNVALIDATED_REDIRECT": 6.1,
    "CACHE_POISONING": 7.5,
    "HTTP_REQUEST_SMUGGLING": 8.8,
    "PROTOTYPE_POLLUTION": 8.8,
    "SSL_CERTIFICATE_ERROR": 5.9,
    "WEAK_SSL": 5.9,
    "WEAK_TLS": 5.9,
    "DEPRECATED_TLS": 5.9,
    "MISSING_HSTS": 3.7,

    # ── Info disclosure ──────────────────────────────────────────
    "SENSITIVE_DATA_EXPOSURE": 7.5,
    "DIRECTORY_LISTING": 5.3,
    "ERROR_DISCLOSURE": 5.3,
    "PATH_DISCLOSURE": 5.3,
    "SOURCE_CODE_DISCLOSURE": 6.5,
    "INFO_DISCLOSURE": 4.5,
    "INFO_LEAKAGE": 4.5,
    "VERBOSE_API_ERROR": 5.3,

    # ── Config / headers / CORS ──────────────────────────────────
    "MISSING_SECURITY_HEADERS": 3.7,
    "MISSING_API_SECURITY_HEADERS": 3.7,
    "MISSING_CSP": 3.7,
    "WEAK_CSP": 3.7,
    "INSECURE_CORS": 6.5,
    "CORS_MISCONFIGURATION": 6.5,
    "WILDCARD_CORS": 6.5,
    "WILDCARD_CORS_API": 6.5,
    "REFLECTED_ORIGIN_CORS": 6.5,
    "NULL_ORIGIN_CORS": 6.5,
    "CSRF": 6.5,
    "CLICKJACKING": 4.7,
    "HTTP_VERB_TAMPERING": 5.3,
    "INSECURE_COOKIE": 4.7,

    # ── File / upload ────────────────────────────────────────────
    "FILE_UPLOAD": 8.8,
    "UNRESTRICTED_FILE_UPLOAD": 7.5,
    "PATH_TRAVERSAL": 7.5,
    "DIRECTORY_TRAVERSAL": 7.5,
    "PATH_TRAVERSAL_IN_FILENAME": 6.5,
    "LOCAL_FILE_INCLUSION": 7.5,
    "LFI": 7.5,
    "REMOTE_FILE_INCLUSION": 8.8,
    "EXPOSED_SENSITIVE_FILE": 6.5,

    # ── Infra ────────────────────────────────────────────────────
    "EXPOSED_ADMIN": 7.2,
    "EXPOSED_DEBUG_ENDPOINT": 5.3,
    "EXPOSED_OPENAPI_SPEC": 4.7,
    "OPEN_PORT": 5.3,
    "SERVICE_DETECTED": 3.7,
    "UNENCRYPTED_SERVICE": 5.3,
    "HIDDEN_ENDPOINT": 2.5,
    "ATTACK_SURFACE": 2.5,
    "SUBDOMAIN": 2.5,

    # ── Technology detection ─────────────────────────────────────
    "TECHNOLOGY_DETECTION": 2.5,
    "TECH_DETECTED": 2.5,

    # ── Secrets ──────────────────────────────────────────────────
    "EXPOSED_SECRET": 8.8,
    "COMMITTED_SECRET": 8.2,
    "HARDCODED_SECRET": 7.5,
    "TOKEN_IN_LOCALSTORAGE": 4.7,

    # ── Dependency ───────────────────────────────────────────────
    "DEPENDENCY_VULNERABILITY": 7.5,
    "OUTDATED_DEPENDENCY": 5.9,

    # ── Rate limiting ────────────────────────────────────────────
    "RATE_LIMIT_BYPASS": 5.3,
    "MISSING_RATE_LIMITING": 5.3,
    "API_NO_RATE_LIMIT": 5.3,
    "API_RATE_LIMITED": 2.5,
    "API_RATE_LIMIT_INCONCLUSIVE": 2.5,

    # ── Mass assignment ──────────────────────────────────────────
    "MASS_ASSIGNMENT": 6.5,
    "API_MASS_ASSIGNMENT": 6.5,

    # ── API auth ─────────────────────────────────────────────────
    "API_AUTH_BYPASS": 8.1,

    # ── GraphQL ──────────────────────────────────────────────────
    "GRAPHQL_INTROSPECTION_ENABLED": 4.7,
    "GRAPHQL_DEEP_INTROSPECTION": 4.7,
    "GRAPHQL_DEPTH_LIMIT_MISSING": 5.3,
    "GRAPHQL_SQLI_RESOLVER": 8.8,

    # ── Parameter fuzzing ────────────────────────────────────────
    "PARAMETER_DISCOVERY": 2.5,
    "PARAM_DISCOVERY": 2.5,
    "PARAMETER_FUZZ_500": 2.5,
    "PARAMETER_REFLECTION": 2.5,
    "POST_FUZZ_500": 2.5,
    "POST_PARAMETER_REFLECTION": 2.5,

    # ── Business logic ───────────────────────────────────────────
    "NEGATIVE_AMOUNT_ACCEPTED": 6.5,
    "ZERO_AMOUNT_ACCEPTED": 5.3,
    "NO_TRANSACTION_LIMIT": 6.5,
    "REPLAY_VULNERABLE": 5.3,

    # ── Generic ──────────────────────────────────────────────────
    "ENDPOINT_DISCOVERY": 2.5,
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
    "request_response": 0.9,
    "payload": 0.85,
    "moderate": 0.85,
    "minimal": 0.7,
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
    # Normalize inputs — str() coercion prevents crash on non-string inputs
    finding_type = str(finding_type or "").upper().strip()
    severity = str(severity or "").upper().strip() or "INFO"
    evidence_strength = str(evidence_strength or "").lower().strip() or "moderate"

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
