"""
Tests for Scope Validator
"""

import pytest

from tools.scope_validator import (
    ScopeValidator,
    ScopeViolationError,
    validate_target_scope,
)


class TestScopeValidator:
    """Test suite for ScopeValidator"""

    def test_exact_domain_match(self):
        """Test exact domain matching"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com"], "ipRanges": []}
        )

        assert validator.validate_target("https://staging.app.com/api")

    def test_exact_domain_mismatch_raises_error(self):
        """Test that non-matching domain raises error"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com"], "ipRanges": []}
        )

        with pytest.raises(ScopeViolationError):
            validator.validate_target("https://production.app.com/api")

    def test_wildcard_subdomain_match(self):
        """Test wildcard subdomain matching"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["*.dev.app.com"], "ipRanges": []}
        )

        assert validator.validate_target("https://test.dev.app.com/api")
        assert validator.validate_target("https://staging.dev.app.com/api")

    def test_wildcard_does_not_match_parent_domain(self):
        """Test that wildcard doesn't match parent domain"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["*.dev.app.com"], "ipRanges": []}
        )

        with pytest.raises(ScopeViolationError):
            validator.validate_target("https://app.com/api")

    def test_ip_address_in_range(self):
        """Test IP address within CIDR range"""
        validator = ScopeValidator(
            "eng-123", {"domains": [], "ipRanges": ["10.0.0.0/24"]}
        )

        assert validator.validate_target("http://10.0.0.50/api")
        assert validator.validate_target("http://10.0.0.1/api")

    def test_ip_address_outside_range_raises_error(self):
        """Test that IP outside range raises error"""
        validator = ScopeValidator(
            "eng-123", {"domains": [], "ipRanges": ["10.0.0.0/24"]}
        )

        with pytest.raises(ScopeViolationError):
            validator.validate_target("http://10.0.1.50/api")

    def test_multiple_domains_any_match(self):
        """Test that any matching domain is valid"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com", "dev.app.com"], "ipRanges": []}
        )

        assert validator.validate_target("https://staging.app.com/api")
        assert validator.validate_target("https://dev.app.com/api")

    def test_multiple_ip_ranges_any_match(self):
        """Test that any matching IP range is valid"""
        validator = ScopeValidator(
            "eng-123", {"domains": [], "ipRanges": ["10.0.0.0/24", "192.168.1.0/24"]}
        )

        assert validator.validate_target("http://10.0.0.50/api")
        assert validator.validate_target("http://192.168.1.100/api")

    def test_case_insensitive_domain_matching(self):
        """Test that domain matching is case insensitive"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com"], "ipRanges": []}
        )

        assert validator.validate_target("https://STAGING.APP.COM/api")
        assert validator.validate_target("https://Staging.App.Com/api")

    def test_is_in_scope_returns_boolean(self):
        """Test that is_in_scope returns boolean without raising"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com"], "ipRanges": []}
        )

        assert validator.is_in_scope("https://staging.app.com/api") is True
        assert validator.is_in_scope("https://production.app.com/api") is False

    def test_invalid_url_raises_error(self):
        """Test that invalid URL raises error"""
        validator = ScopeValidator(
            "eng-123", {"domains": ["staging.app.com"], "ipRanges": []}
        )

        with pytest.raises(ScopeViolationError):
            validator.validate_target("not-a-url")


class TestValidateTargetScope:
    """Tests for standalone validate_target_scope() function (blocker 36)"""

    def test_allowlist_mode_allows_matching_target(self):
        """allowlist mode allows target that matches allowed_patterns"""
        result = validate_target_scope(
            target="https://example.com/api",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_allowlist_mode_blocks_mismatched_target(self):
        """allowlist mode blocks target that doesn't match allowed_patterns"""
        result = validate_target_scope(
            target="https://evil.com/api",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is False

    def test_allowlist_mode_without_allowed_targets_blocks_all(self):
        """allowlist mode with no allowed_targets blocks all targets (fail-closed)"""
        result = validate_target_scope(
            target="https://anything.com",
            mode="allowlist",
            allowed_targets=[],
        )
        assert result is False

    def test_allowlist_mode_with_none_allowed_targets_blocks_all(self):
        """allowlist mode with None allowed_targets blocks all targets (fail-closed)"""
        result = validate_target_scope(
            target="https://anything.com",
            mode="allowlist",
            allowed_targets=None,
        )
        assert result is False

    def test_warn_mode_allows_even_mismatched_target(self):
        """warn mode allows target even when not in allowed_targets (with warning)"""
        result = validate_target_scope(
            target="https://evil.com",
            mode="warn",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_open_mode_allows_all_targets(self):
        """open mode allows any target regardless of allowed_targets"""
        result = validate_target_scope(
            target="https://anything.com",
            mode="open",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_blocked_targets_always_block(self):
        """blocked_targets are checked before mode — always block if matched"""
        result = validate_target_scope(
            target="https://malware.com",
            mode="open",
            allowed_targets=["*"],
            blocked_targets=["*malware*"],
        )
        assert result is False

    def test_blocked_targets_checked_in_allowlist_mode(self):
        """blocked targets block even in allowlist mode with matching allowed"""
        result = validate_target_scope(
            target="https://example.com/admin",
            mode="allowlist",
            allowed_targets=["*example.com*"],
            blocked_targets=["*example.com/admin*"],
        )
        assert result is False

    def test_empty_blocked_targets_does_not_block(self):
        """empty blocked_targets list should not block any target"""
        result = validate_target_scope(
            target="https://example.com",
            mode="allowlist",
            allowed_targets=["*example.com*"],
            blocked_targets=[],
        )
        assert result is True

    def test_legacy_authorized_scope_path_allows(self):
        """Explicit authorized_scope dict should use legacy ScopeValidator path"""
        result = validate_target_scope(
            target="https://staging.app.com/api",
            authorized_scope={"domains": ["staging.app.com"], "ipRanges": []},
        )
        assert result is True

    def test_legacy_authorized_scope_path_blocks(self):
        """Legacy ScopeValidator path should block out-of-scope targets"""
        result = validate_target_scope(
            target="https://production.app.com/api",
            authorized_scope={"domains": ["staging.app.com"], "ipRanges": []},
        )
        assert result is False

    def test_empty_authorized_scope_allows_all(self):
        """Empty authorized_scope dict allows all targets"""
        result = validate_target_scope(
            target="https://anything.com",
            authorized_scope={},
        )
        assert result is True

    def test_glob_pattern_matching_in_allowed(self):
        """Glob patterns in allowed_targets should match correctly"""
        result = validate_target_scope(
            target="https://sub.example.com",
            mode="allowlist",
            allowed_targets=["*example.com", "*example.org"],
        )
        assert result is True

        result = validate_target_scope(
            target="https://other.com",
            mode="allowlist",
            allowed_targets=["*example.com", "*example.org"],
        )
        assert result is False

    def test_combined_blocked_overrides_allowed(self):
        """blocked_targets should override allowed_targets when both match"""
        result = validate_target_scope(
            target="https://example.com/admin",
            mode="allowlist",
            allowed_targets=["*example.com*"],
            blocked_targets=["*admin*"],
        )
        assert result is False

    def test_blocked_checked_before_mode_even_in_open(self):
        """blocked_targets checked before mode, even in open mode"""
        result = validate_target_scope(
            target="https://evil.com",
            mode="open",
            blocked_targets=["*evil*"],
        )
        assert result is False

    def test_different_url_schemes_match_glob(self):
        """Target with different URL schemes should match glob patterns"""
        result = validate_target_scope(
            target="http://example.com",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

        result = validate_target_scope(
            target="https://example.com",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

        result = validate_target_scope(
            target="ftp://example.com",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_target_with_query_params_matches(self):
        """Target with query parameters should still match glob"""
        result = validate_target_scope(
            target="https://example.com/page?foo=bar&baz=qux",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_target_with_fragment_matches(self):
        """Target with fragment should still match glob"""
        result = validate_target_scope(
            target="https://example.com/page#section",
            mode="allowlist",
            allowed_targets=["*example.com*"],
        )
        assert result is True

    def test_legacy_authorized_scope_with_engagement_id(self):
        """Legacy ScopeValidator path works with engagement_id"""
        result = validate_target_scope(
            target="https://staging.app.com/api",
            engagement_id="eng-test-456",
            authorized_scope={"domains": ["staging.app.com"], "ipRanges": []},
        )
        assert result is True


class TestIsInternalAddress:
    """Tests for ScopeValidator.is_internal_address() — SSRF prevention."""

    def test_blocks_cloud_metadata_aws(self):
        assert ScopeValidator.is_internal_address("169.254.169.254") is True

    def test_blocks_cloud_metadata_gcp(self):
        assert ScopeValidator.is_internal_address("metadata.google.internal") is True

    def test_blocks_cloud_metadata_alibaba(self):
        assert ScopeValidator.is_internal_address("100.100.100.200") is True

    def test_blocks_loopback_localhost(self):
        assert ScopeValidator.is_internal_address("localhost") is True

    def test_blocks_loopback_ipv4(self):
        assert ScopeValidator.is_internal_address("127.0.0.1") is True

    def test_blocks_private_ip_10_dot(self):
        assert ScopeValidator.is_internal_address("10.0.0.1") is True

    def test_blocks_private_ip_172_dot(self):
        assert ScopeValidator.is_internal_address("172.16.0.1") is True

    def test_blocks_private_ip_192_168(self):
        assert ScopeValidator.is_internal_address("192.168.1.1") is True

    def test_blocks_link_local(self):
        assert ScopeValidator.is_internal_address("169.254.1.1") is True

    def test_blocks_multicast(self):
        assert ScopeValidator.is_internal_address("224.0.0.1") is True

    def test_allows_public_ip(self):
        assert ScopeValidator.is_internal_address("93.184.216.34") is False

    def test_allows_public_hostname(self):
        assert ScopeValidator.is_internal_address("example.com") is False

    def test_allows_empty_string(self):
        assert ScopeValidator.is_internal_address("") is False


class TestValidateUrlScheme:
    """Tests for ScopeValidator.validate_url_scheme()."""

    def test_allows_https(self):
        assert ScopeValidator.validate_url_scheme("https://example.com") == "https://example.com"

    def test_allows_http(self):
        assert ScopeValidator.validate_url_scheme("http://example.com") == "http://example.com"

    def test_raises_on_file_url(self):
        with pytest.raises(ValueError, match="Blocked non-HTTP URL"):
            ScopeValidator.validate_url_scheme("file:///etc/passwd")

    def test_raises_on_ftp(self):
        with pytest.raises(ValueError, match="Blocked non-HTTP URL"):
            ScopeValidator.validate_url_scheme("ftp://example.com")

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match="Blocked non-HTTP URL"):
            ScopeValidator.validate_url_scheme("")


class TestValidateSafeTarget:
    """Tests for ScopeValidator.validate_safe_target() — combined SSRF + scope."""

    def test_allows_public_target_in_scope(self):
        validator = ScopeValidator(
            "eng-123", {"domains": ["example.com"], "ipRanges": []}
        )
        assert validator.validate_safe_target("https://example.com/api")

    def test_blocks_ssrf_target_even_if_in_scope(self):
        validator = ScopeValidator(
            "eng-123", {"domains": ["*"], "ipRanges": []}
        )
        with pytest.raises(ScopeViolationError, match="internal or cloud-metadata"):
            validator.validate_safe_target("http://169.254.169.254")

    def test_blocks_out_of_scope_target(self):
        validator = ScopeValidator(
            "eng-123", {"domains": ["example.com"], "ipRanges": []}
        )
        with pytest.raises(ScopeViolationError, match="not in authorized scope"):
            validator.validate_safe_target("https://evil.com")

    def test_is_safe_target_returns_boolean(self):
        validator = ScopeValidator(
            "eng-123", {"domains": ["example.com"], "ipRanges": []}
        )
        assert validator.is_safe_target("https://example.com/api") is True
        assert validator.is_safe_target("https://evil.com") is False
        assert validator.is_safe_target("http://169.254.169.254") is False


class TestCheckBlocked:
    """Tests for _check_blocked helper"""

    def test_matches_blocked_pattern(self):
        from tools.scope_validator import _check_blocked
        assert _check_blocked("https://evil.com", ["*evil*"]) is True

    def test_no_match_returns_false(self):
        from tools.scope_validator import _check_blocked
        assert _check_blocked("https://good.com", ["*evil*"]) is False

    def test_none_blocked_list_returns_false(self):
        from tools.scope_validator import _check_blocked
        assert _check_blocked("https://example.com", None) is False

    def test_empty_blocked_list_returns_false(self):
        from tools.scope_validator import _check_blocked
        assert _check_blocked("https://example.com", []) is False

    def test_exact_match_in_blocked_list(self):
        from tools.scope_validator import _check_blocked
        assert _check_blocked("https://example.com/admin", ["*admin*"]) is True


class TestCheckAllowed:
    """Tests for _check_allowed helper"""

    def test_matching_target_returns_true(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://example.com", ["*example.com*"], "allowlist")
        assert result is True

    def test_no_allowed_targets_in_allowlist_returns_false(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://example.com", [], "allowlist")
        assert result is False

    def test_no_allowed_targets_in_warn_returns_true(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://example.com", [], "warn")
        assert result is True

    def test_non_matching_target_in_allowlist_returns_false(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://evil.com", ["*example.com*"], "allowlist")
        assert result is False

    def test_non_matching_target_in_warn_returns_true(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://evil.com", ["*example.com*"], "warn")
        assert result is True

    def test_none_allowed_targets_in_allowlist_returns_false(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://example.com", None, "allowlist")
        assert result is False

    def test_none_allowed_targets_in_warn_returns_true(self):
        from tools.scope_validator import _check_allowed
        result = _check_allowed("https://example.com", None, "warn")
        assert result is True
