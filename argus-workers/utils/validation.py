"""
Input validation utilities for security and data integrity.

Provides UUID validation to prevent PostgreSQL errors when
non-UUID values are passed to UUID-typed columns.
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
    return urllib.parse.quote(component, safe='')


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
