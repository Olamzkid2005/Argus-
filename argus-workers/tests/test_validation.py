"""
Tests for validation utilities
"""
import pytest

from utils.validation import validate_uuid


class TestValidateUUID:
    """Tests for validate_uuid function"""

    def test_valid_uuid_returns_canonical_form(self):
        """Test that a valid UUID string is accepted and returned"""
        result = validate_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_uuid_without_dashes(self):
        """Test UUID without dashes is still valid"""
        result = validate_uuid("550e8400e29b41d4a716446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_valid_uuid_uppercase(self):
        """Test uppercase UUID is valid and returned lowercase"""
        result = validate_uuid("550E8400-E29B-41D4-A716-446655440000")
        assert result == "550e8400-e29b-41d4-a716-446655440000"

    def test_invalid_uuid_raises_value_error(self):
        """Test that an invalid UUID string raises ValueError"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            validate_uuid("not-a-uuid")

    def test_test_uuid_like_eng_123_raises_error(self):
        """Test that test-style IDs like 'eng-123' raise ValueError"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            validate_uuid("eng-123")

    def test_test_uuid_like_test_123_raises_error(self):
        """Test that test-style IDs like 'test-123' raise ValueError"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            validate_uuid("test-123")

    def test_empty_string_raises_error(self):
        """Test that empty string raises ValueError"""
        with pytest.raises(ValueError, match="not a valid UUID"):
            validate_uuid("")

    def test_custom_field_name_in_error(self):
        """Test that custom field_name appears in error message"""
        with pytest.raises(ValueError, match="custom_field"):
            validate_uuid("bad-uuid", field_name="custom_field")
