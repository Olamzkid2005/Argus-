"""
Input validation utilities for security and data integrity.

Provides:
- UUID validation to prevent PostgreSQL errors
- Private IP detection for SSRF prevention
- Redis key sanitization
"""

import re
import urllib.parse
import uuid

# Pre-compiled regex for Redis key sanitization
_REDIS_KEY_CLEAN = re.compile(r"[^a-zA-Z0-9\-_.]")


def sanitize_redis_key(component: str) -> str:
    """
    Sanitize a key component for use in Redis keys.

    Strips characters that could be used for Redis key injection,
    such as newlines, carriage returns, null bytes, and colons
    that could alter the intended key hierarchy.

    Uses percent-encoding for special characters to preserve
    uniqueness while preventing key injection.

    Args:
        component: Raw key component string

    Returns:
        Sanitized key component safe for Redis key construction
    """
    return urllib.parse.quote(component, safe="")


def validate_uuid(value: str, field_name: str = "engagement_id") -> str:
    """
    Validate that a string is a properly formatted UUID.

    Args:
        value: The string to validate as a UUID
        field_name: Name of the field (for error messages)

    Returns:
        The validated UUID string (canonical form)

    Raises:
        ValueError: If the value is not a valid UUID
    """
    try:
        # Convert to UUID object and back to get canonical form
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ValueError(
            f"Invalid {field_name}: '{value}' is not a valid UUID. "
            f"Expected format: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'"
        ) from None


def is_private_ip(ip: str) -> bool:
    """
    Check if an IP address is private, loopback, link-local, or otherwise
    internal (RFC 1918, RFC 4193, RFC 4291, RFC 6598, etc.).

    Gap 13.1: Delegates to ``ScopeValidator.is_internal_address()`` from
    ``tools/scope_validator.py`` — the single source of truth for ALL
    SSRF/private-IP/internal-target validation. Previously had its own
    hand-rolled IP range parsing (IPv4 octet splitting + IPv6 prefix
    checks) that could drift from the canonical implementation.

    The callers of this function (``post_finding_hooks.py``,
    ``llm_review.py``, ``repo_scan.py``) pass bare IP addresses, so
    no hostname resolution is needed — the IP is passed directly.

    Args:
        ip: IP address string (IPv4 or IPv6)

    Returns:
        True if the IP is a private/internal address
    """
    from tools.scope_validator import ScopeValidator

    # ScopeValidator.is_internal_address() handles:
    # - Static cloud metadata hostnames
    # - Bare IP address checks (private, loopback, link-local, multicast)
    # - IPv4-mapped IPv6 addresses
    # - DNS resolution for hostname inputs
    # Since callers pass bare IPs, the fast path (static check + bare IP)
    # is used, avoiding DNS resolution.
    return ScopeValidator.is_internal_address(ip)
