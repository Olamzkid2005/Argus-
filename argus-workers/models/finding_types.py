"""
Finding Type Families — shared SSOT for vulnerability type normalization.

Both HypothesisEngine and IntelligenceEngine import these maps so that
finding types like REFLECTED_XSS, STORED_XSS, DOM_XSS all normalize to
the canonical family "XSS" for grouping, tool suggestion, and correlation.
"""

# ── Type-to-family normalization map ──────────────────────────────────
# Maps each finding type string to its canonical vulnerability family.
# Adding a new vulnerability scanner? Add its finding types here.
TYPE_TO_FAMILY: dict[str, str] = {
    # SQL Injection
    "SQL_INJECTION": "SQLI",
    "BLIND_SQLI": "SQLI",
    "TIME_BASED_SQLI": "SQLI",
    "TIME_BASED_SQL_INJECTION": "SQLI",
    "ERROR_SQLI": "SQLI",
    # Cross-Site Scripting
    "REFLECTED_XSS": "XSS",
    "STORED_XSS": "XSS",
    "DOM_XSS": "XSS",
    "BLIND_XSS": "XSS",
    "CROSS_SITE_SCRIPTING": "XSS",
    # Remote Code Execution
    "COMMAND_INJECTION": "RCE",
    "SSTI": "RCE",
    # Local File Inclusion
    "PATH_TRAVERSAL": "LFI",
    "DIRECTORY_TRAVERSAL": "LFI",
    # SSRF / Open Redirect
    "SSRF": "SSRF",
    "OPEN_REDIRECT": "SSRF",
    # JWT
    "JWT": "JWT",
    "JWT_WEAKNESS": "JWT",
    # BOLA / IDOR
    "BOLA": "BOLA",
    "IDOR": "IDOR",
    # Secrets
    "EXPOSED_SECRET": "EXPOSED_SECRET",
    "COMMITTED_SECRET": "EXPOSED_SECRET",
}

# ── Verification tool map ────────────────────────────────────────────
# Maps canonical family → list of verification tool names.
# The first tool is the primary verifier; additional tools are fallbacks.
VERIFICATION_TOOL_MAP: dict[str, list[str]] = {
    "SQLI": ["sqlmap", "verification_agent"],
    "XSS": ["finding_verifier", "verification_agent"],
    "SSRF": ["finding_verifier", "verification_agent"],
    "RCE": ["finding_verifier", "verification_agent"],
    "OPEN_REDIRECT": ["finding_verifier", "verification_agent"],
    "JWT": ["jwt_tool", "verification_agent"],
    "BOLA": ["dual_auth_scanner", "verification_agent"],
    "IDOR": ["dual_auth_scanner", "verification_agent"],
    "EXPOSED_SECRET": ["credential_replay", "verification_agent"],
}


def normalize_finding_type(finding_type: str) -> str:
    """Normalize a finding type to its canonical family name.

    Returns the family name if a mapping exists, otherwise returns the
    uppercase version of the input type.
    """
    return TYPE_TO_FAMILY.get(finding_type.upper(), finding_type.upper())
