"""
Input validation utilities for security and data integrity.

Provides UUID validation to prevent PostgreSQL errors when
non-UUID values are passed to UUID-typed columns.
"""
import uuid


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
        )
