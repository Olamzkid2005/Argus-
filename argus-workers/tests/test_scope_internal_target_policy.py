"""Policy tests for internal / loopback scan targets.

Internal addresses (loopback, RFC1918, CGNAT) are blocked by default as SSRF
defense. They are permitted only when the operator does BOTH of:

  1. opts in via ARGUS_ALLOW_INTERNAL_TARGETS, and
  2. has the target explicitly authorized in the engagement scope.

Cloud metadata / link-local targets are exempt from the opt-in and stay blocked
under every configuration. Note that ScopeValidator.is_internal_address()
deliberately keeps its original semantics (loopback IS internal) — only the
block *decision* moved to is_blocked_internal_target().
"""

from __future__ import annotations

import pytest

from tools.scope_validator import ScopeValidator


@pytest.fixture
def no_opt_in(monkeypatch):
    monkeypatch.delenv("ARGUS_ALLOW_INTERNAL_TARGETS", raising=False)


@pytest.fixture
def opt_in(monkeypatch):
    monkeypatch.setenv("ARGUS_ALLOW_INTERNAL_TARGETS", "1")


class TestMetadataIsAlwaysBlocked:
    """Cloud metadata and link-local must never be scannable."""

    @pytest.mark.parametrize(
        "host",
        [
            "169.254.169.254",
            "metadata.google.internal",
            "metadata",
            "instance-data",
            "instance-data.us-east-1.compute.internal",
            "100.100.100.200",
        ],
    )
    def test_blocked_even_when_opted_in_and_authorized(self, opt_in, host):
        assert ScopeValidator.is_always_blocked_target(host) is True
        assert (
            ScopeValidator.is_blocked_internal_target(host, authorized=True) is True
        )

    def test_other_link_local_is_blocked(self, opt_in):
        assert ScopeValidator.is_blocked_internal_target(
            "169.254.10.10", authorized=True
        ) is True

    def test_metadata_is_not_an_internal_address(self, opt_in):
        """Metadata IPs are link-local, not is_internal_address() members, but
        they must still be caught by the always-blocked predicate."""
        assert ScopeValidator.is_always_blocked_target("metadata.google.internal")


class TestInternalTargetOptIn:
    def test_loopback_blocked_by_default(self, no_opt_in):
        assert (
            ScopeValidator.is_blocked_internal_target("127.0.0.1", authorized=True)
            is True
        )

    def test_private_ranges_blocked_by_default(self, no_opt_in):
        for host in ("10.0.0.5", "172.16.4.4", "192.168.1.10"):
            assert (
                ScopeValidator.is_blocked_internal_target(host, authorized=True) is True
            ), host

    def test_opt_in_alone_is_not_enough(self, opt_in):
        """Opting in must not permit an internal target that is not authorized."""
        assert (
            ScopeValidator.is_blocked_internal_target("127.0.0.1", authorized=False)
            is True
        )

    def test_opt_in_plus_authorization_allows_loopback(self, opt_in):
        assert (
            ScopeValidator.is_blocked_internal_target("127.0.0.1", authorized=True)
            is False
        )

    def test_opt_in_plus_authorization_allows_private_range(self, opt_in):
        assert (
            ScopeValidator.is_blocked_internal_target("10.0.0.5", authorized=True)
            is False
        )

    def test_authorization_alone_is_not_enough(self, no_opt_in):
        assert (
            ScopeValidator.is_blocked_internal_target("127.0.0.1", authorized=True)
            is True
        )


class TestPublicTargetsUnaffected:
    @pytest.mark.parametrize("host", ["example.com", "93.184.216.34", "8.8.8.8"])
    def test_public_addresses_are_never_blocked_by_the_internal_policy(
        self, opt_in, host
    ):
        assert ScopeValidator.is_blocked_internal_target(host) is False
        assert ScopeValidator.is_blocked_internal_target(host, authorized=True) is False

    def test_empty_hostname_is_not_blocked(self, opt_in):
        assert ScopeValidator.is_blocked_internal_target("") is False


class TestIsInternalAddressSemanticsUnchanged:
    """Regression guard: the SSRF predicate itself must keep its meaning.

    tests/test_scope_validator.py asserts these values; the opt-in work must not
    silently flip is_internal_address() to return False for loopback.
    """

    def test_loopback_still_internal(self, opt_in):
        assert ScopeValidator.is_internal_address("127.0.0.1") is True
        assert ScopeValidator.is_internal_address("localhost") is True

    def test_public_still_external(self, opt_in):
        assert ScopeValidator.is_internal_address("example.com") is False
