"""Phase: ldap_injection — _activate_ldap_injection and _ldap_injection_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# LDAP-related keywords and technologies for tech_stack matching
_LDAP_KEYWORDS: set[str] = {
    "ldap", "ldap injection", "openldap", "389ds",
    "active directory", "ad ds", "ad lds", "ad fs",
    "apache directory", "apacheds", "fedora directory",
    "unboundid", "novell edirectory", "oracle internet directory",
    "sun directory", "openam", "opendj", "pensieve ldap", "ldapjs",
    "spring-ldap", "spring data ldap",
    "ldaptive", "ldap3", "python-ldap", "ldapauthenticator",
    "django-auth-ldap", "flask-ldap", "php ldap",
}
def _activate_ldap_injection(rc) -> tuple[bool, str]:
    """Activate when LDAP-related keywords are detected in tech_stack.

    LDAP injection occurs when user input is embedded in LDAP query
    filters without proper sanitization. Impact ranges from authentication
    bypass to information disclosure (querying arbitrary directory entries).
    Common in enterprise applications using Active Directory for auth.

    Activates when:
      - ``has_ldap`` flag is set on ReconContext (forward-compatible)
      - ``ldap_endpoints`` list is populated (forward-compatible)
      - LDAP-related keywords appear in tech_stack
      - Auth endpoints are present (LDAP is frequently used for authentication)
      - Parameter-bearing URLs are present (LDAP injection vector)
    """
    # Forward-compatible: check for dedicated LDAP attribute
    has_ldap = _get_attr(rc, "has_ldap", False)
    if has_ldap:
        return True, "LDAP signals detected in recon"

    ldap_eps = _get_attr(rc, "ldap_endpoints", [])
    if ldap_eps and len(ldap_eps) > 0:
        return True, f"{len(ldap_eps)} LDAP endpoint(s) found"

    # Check tech_stack for LDAP-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _LDAP_KEYWORDS if kw in tech_lower]
        if matched:
            return True, f"LDAP technology detected: {', '.join(matched[:3])}"

    # LDAP is commonly used for authentication
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_login = _get_attr(rc, "has_login_page", False)
    reasons = []
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_login:
        reasons.append("login page")

    # Parameter-bearing URLs can be LDAP injection vectors
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")

    if reasons:
        return True, "possible LDAP context: " + "; ".join(reasons)

    return False, "no LDAP signals detected"


def _ldap_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for LDAP injection vulnerability testing.

    Tests for:
      - LDAP filter injection via login/username parameters
      - Blind LDAP injection via boolean-based inference
      - LDAP search filter manipulation
      - Active Directory-specific LDAP injection patterns
      - Authentication bypass via LDAP filter tampering
      - Information disclosure via crafted LDAP queries
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="LDAP injection vulnerability scanning (filter-based, auth bypass)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ldap,injection,ldapi,auth-bypass"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Active Directory and directory service exposure scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ldap,active-directory,exposure,disclosure"],
        ),
    ]
    return tools


# ── Phase: Cloud Metadata Probe ────────────────────────────────────────────

# Cloud provider keywords for matching against tech_stack
_CLOUD_PROVIDERS: dict[str, set[str]] = {
    "AWS": {"aws", "amazon web services", "amazon", "ec2", "s3", "lambda",
             "cloudfront", "route53", "elb", "ecs", "eks", "rds"},
    "GCP": {"gcp", "google cloud", "google cloud platform", "gke",
             "cloud run", "app engine", "bigquery", "cloud storage"},
    "Azure": {"azure", "microsoft azure", "azure vm", "azure functions",
               "azure storage", "aks", "azure ad"},
}
