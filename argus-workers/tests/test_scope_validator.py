"""
Tests for Scope Validator
"""
import pytest

from tools.scope_validator import ScopeValidator, ScopeViolationError


class TestScopeValidator:
    """Test suite for ScopeValidator"""

    def test_exact_domain_match(self):
        """Test exact domain matching"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com"],
            "ipRanges": []
        })

        assert validator.validate_target("https://staging.app.com/api")

    def test_exact_domain_mismatch_raises_error(self):
        """Test that non-matching domain raises error"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com"],
            "ipRanges": []
        })

        with pytest.raises(ScopeViolationError):
            validator.validate_target("https://production.app.com/api")

    def test_wildcard_subdomain_match(self):
        """Test wildcard subdomain matching"""
        validator = ScopeValidator("eng-123", {
            "domains": ["*.dev.app.com"],
            "ipRanges": []
        })

        assert validator.validate_target("https://test.dev.app.com/api")
        assert validator.validate_target("https://staging.dev.app.com/api")

    def test_wildcard_does_not_match_parent_domain(self):
        """Test that wildcard doesn't match parent domain"""
        validator = ScopeValidator("eng-123", {
            "domains": ["*.dev.app.com"],
            "ipRanges": []
        })

        with pytest.raises(ScopeViolationError):
            validator.validate_target("https://app.com/api")

    def test_ip_address_in_range(self):
        """Test IP address within CIDR range"""
        validator = ScopeValidator("eng-123", {
            "domains": [],
            "ipRanges": ["10.0.0.0/24"]
        })

        assert validator.validate_target("http://10.0.0.50/api")
        assert validator.validate_target("http://10.0.0.1/api")

    def test_ip_address_outside_range_raises_error(self):
        """Test that IP outside range raises error"""
        validator = ScopeValidator("eng-123", {
            "domains": [],
            "ipRanges": ["10.0.0.0/24"]
        })

        with pytest.raises(ScopeViolationError):
            validator.validate_target("http://10.0.1.50/api")

    def test_multiple_domains_any_match(self):
        """Test that any matching domain is valid"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com", "dev.app.com"],
            "ipRanges": []
        })

        assert validator.validate_target("https://staging.app.com/api")
        assert validator.validate_target("https://dev.app.com/api")

    def test_multiple_ip_ranges_any_match(self):
        """Test that any matching IP range is valid"""
        validator = ScopeValidator("eng-123", {
            "domains": [],
            "ipRanges": ["10.0.0.0/24", "192.168.1.0/24"]
        })

        assert validator.validate_target("http://10.0.0.50/api")
        assert validator.validate_target("http://192.168.1.100/api")

    def test_case_insensitive_domain_matching(self):
        """Test that domain matching is case insensitive"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com"],
            "ipRanges": []
        })

        assert validator.validate_target("https://STAGING.APP.COM/api")
        assert validator.validate_target("https://Staging.App.Com/api")

    def test_is_in_scope_returns_boolean(self):
        """Test that is_in_scope returns boolean without raising"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com"],
            "ipRanges": []
        })

        assert validator.is_in_scope("https://staging.app.com/api") is True
        assert validator.is_in_scope("https://production.app.com/api") is False

    def test_invalid_url_raises_error(self):
        """Test that invalid URL raises error"""
        validator = ScopeValidator("eng-123", {
            "domains": ["staging.app.com"],
            "ipRanges": []
        })

        with pytest.raises(ScopeViolationError):
            validator.validate_target("not-a-url")
