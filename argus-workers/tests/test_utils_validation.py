"""Tests for utils/validation.py — input validation utilities."""

import pytest

from utils.validation import sanitize_redis_key, validate_uuid


class TestSanitizeRedisKey:
    def test_keeps_safe_chars(self):
        assert sanitize_redis_key("abc-123_def.SCAN") == "abc-123_def.SCAN"

    def test_replaces_dangerous_chars(self):
        result = sanitize_redis_key("abc\n123:456")
        assert "\n" not in result
        assert "%0A" in result or "%3A" in result

    def test_replaces_spaces(self):
        result = sanitize_redis_key("key with spaces")
        assert " " not in result
        assert "%20" in result

    def test_replaces_colons(self):
        result = sanitize_redis_key("namespace:key")
        assert ":" not in result
        assert "%3A" in result

    def test_empty_string(self):
        assert sanitize_redis_key("") == ""

    def test_only_safe_chars(self):
        assert sanitize_redis_key("hello_world-123.ABC") == "hello_world-123.ABC"


class TestValidateUUID:
    def test_valid_uuid(self):
        valid = "123e4567-e89b-12d3-a456-426614174000"
        result = validate_uuid(valid)
        assert result == valid

    def test_valid_uuid_no_hyphens(self):
        """UUID without hyphens should still validate and return canonical form."""
        result = validate_uuid("123e4567e89b12d3a456426614174000")
        assert result == "123e4567-e89b-12d3-a456-426614174000"

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValueError, match="Invalid engagement_id"):
            validate_uuid("not-a-uuid")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            validate_uuid("")

    def test_custom_field_name(self):
        with pytest.raises(ValueError, match="custom_field"):
            validate_uuid("bad-uuid", field_name="custom_field")
