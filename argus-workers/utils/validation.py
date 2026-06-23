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

    Used for SSRF prevention across the codebase.

    Args:
        ip: IP address string (IPv4 or IPv6)

    Returns:
        True if the IP is a private/internal address
    """
    # IPv4 check
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        if parts[0] == "10":
            return True  # RFC 1918 Class A
        if parts[0] == "127":
            return True  # Loopback
        if parts[0] == "169" and parts[1] == "254":
            return True  # Link-local / cloud metadata
        if parts[0] == "0":
            return True  # Current network
        if parts[0] == "172" and 16 <= int(parts[1]) <= 31:
            return True  # RFC 1918 Class B
        if parts[0] == "192" and parts[1] == "168":
            return True  # RFC 1918 Class C
        if parts[0] == "100" and 64 <= int(parts[1]) <= 127:
            return True  # CGNAT (RFC 6598)
        if parts[0] == "198" and parts[1] == "18":
            return True  # Benchmarking (RFC 2544)
        if parts[0] == "198" and parts[1] == "19":
            return True  # Benchmarking (RFC 2544)

    # IPv6 check — normalize to lowercase first
    ip_lower = ip.lower()

    # Loopback
    if ip_lower == "::1":
        return True
    if ip_lower == "::":
        return True

    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1)
    if "::ffff:" in ip_lower:
        ipv4_part = ip_lower.rsplit(":", 1)[-1]
        return is_private_ip(ipv4_part)
    if "::" in ip_lower and "." in ip_lower:
        # Other IPv4-compatible/compat formats
        ipv4_part = ip_lower.rsplit(":", 1)[-1]
        if "." in ipv4_part:
            return is_private_ip(ipv4_part)

    # IPv6 Unique Local Address (ULA, RFC 4193): fc00::/7
    if ip_lower.startswith("fc") or ip_lower.startswith("fd"):
        return True

    # IPv6 Link-Local (fe80::/10)
    if ip_lower.startswith("fe80"):
        return True

    # IPv6 Documentation (2001:db8::/32)
    return bool(ip_lower.startswith("2001:db8"))
