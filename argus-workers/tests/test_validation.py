"""
Tests for validation utilities
"""

import pytest

from utils.validation import is_private_ip, validate_uuid


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


class TestIsPrivateIp:
    """Tests for is_private_ip function."""

    # ── IPv4 private ranges ──

    def test_ipv4_10_dot_is_private(self):
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.255") is True

    def test_ipv4_172_16_31_is_private(self):
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.255") is True

    def test_ipv4_172_outside_range_is_public(self):
        assert is_private_ip("172.32.0.1") is False
        assert is_private_ip("172.15.0.1") is False

    def test_ipv4_192_168_is_private(self):
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.255") is True

    def test_ipv4_loopback_is_private(self):
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.255.255.255") is True

    def test_ipv4_link_local_is_private(self):
        assert is_private_ip("169.254.1.1") is True
        assert is_private_ip("169.254.254.254") is True

    def test_ipv4_current_network_is_private(self):
        assert is_private_ip("0.0.0.0") is True

    def test_ipv4_cgnat_is_private(self):
        assert is_private_ip("100.64.0.1") is True
        assert is_private_ip("100.127.255.255") is True

    def test_ipv4_benchmarking_is_private(self):
        assert is_private_ip("198.18.0.1") is True
        assert is_private_ip("198.19.255.255") is True

    def test_ipv4_public_is_not_private(self):
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("93.184.216.34") is False
        assert is_private_ip("1.1.1.1") is False

    # ── IPv6 private ranges ──

    def test_ipv6_loopback_is_private(self):
        assert is_private_ip("::1") is True

    def test_ipv6_unspecified_is_private(self):
        assert is_private_ip("::") is True

    def test_ipv6_ula_is_private(self):
        assert is_private_ip("fc00::1") is True
        assert is_private_ip("fd00::1") is True
        assert is_private_ip("fd12:3456:789a::1") is True

    def test_ipv6_link_local_is_private(self):
        assert is_private_ip("fe80::1") is True
        assert is_private_ip("fe80::abcd:1234") is True

    def test_ipv6_documentation_is_private(self):
        assert is_private_ip("2001:db8::1") is True
        assert is_private_ip("2001:db8:1234::") is True

    def test_ipv6_public_is_not_private(self):
        assert is_private_ip("2001:470:1f15:1abc::1") is False
        assert is_private_ip("2606:4700::6810:8fa7") is False

    # ── IPv4-mapped IPv6 ──

    def test_ipv4_mapped_ipv6_private(self):
        assert is_private_ip("::ffff:127.0.0.1") is True
        assert is_private_ip("::ffff:10.0.0.1") is True
        assert is_private_ip("::ffff:192.168.1.1") is True

    def test_ipv4_mapped_ipv6_public(self):
        assert is_private_ip("::ffff:8.8.8.8") is False
        assert is_private_ip("::ffff:93.184.216.34") is False
