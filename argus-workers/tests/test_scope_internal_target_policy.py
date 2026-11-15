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


# ── Path coverage: the policy must reach the agents and the web scanner ──


class TestReactAgentInternalPolicy:
    """agent/react_agent.py: authorized + opted-in internal targets must work."""

    def _registry(self):
        from agent.tool_registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(
            "nuclei",
            lambda *_: None,
            {
                "name": "nuclei",
                "parameters": [
                    {"name": "target", "param_type": "string", "required": True}
                ],
            },
        )
        return registry

    def _action(self, target):
        from types import SimpleNamespace

        return SimpleNamespace(tool="nuclei", arguments={"target": target})

    def _agent(self, monkeypatch, scope):
        from agent.react_agent import ReActAgent
        from orchestrator_pkg.engagement import EngagementService

        monkeypatch.setattr(
            EngagementService,
            "load_authorized_scope",
            staticmethod(lambda _engagement_id: scope),
        )
        return ReActAgent(self._registry(), engagement_id="eng-1")

    def test_authorized_opted_in_internal_target_is_allowed(self, opt_in, monkeypatch):
        agent = self._agent(monkeypatch, {"domains": ["127.0.0.1"], "ipRanges": []})
        assert agent._validate_arguments(self._action("http://127.0.0.1:8080/")) is True

    def test_opt_in_alone_is_not_authorization(self, opt_in, monkeypatch):
        agent = self._agent(monkeypatch, None)
        assert agent._validate_arguments(self._action("http://127.0.0.1:8080/")) is False

    def test_authorized_without_opt_in_is_refused(self, no_opt_in, monkeypatch):
        agent = self._agent(monkeypatch, {"domains": ["127.0.0.1"], "ipRanges": []})
        assert agent._validate_arguments(self._action("http://127.0.0.1:8080/")) is False

    def test_metadata_stays_blocked_when_authorized_and_opted_in(
        self, opt_in, monkeypatch
    ):
        agent = self._agent(
            monkeypatch, {"domains": ["169.254.169.254"], "ipRanges": []}
        )
        action = self._action("http://169.254.169.254/latest/meta-data/")
        assert agent._validate_arguments(action) is False


class TestSwarmInternalPolicy:
    """agent/swarm.py: one decision for targets, peers and specialist tools."""

    @pytest.fixture(autouse=True)
    def clean_scope(self):
        from tools.scope_validator import clear_process_scope

        clear_process_scope()
        yield
        clear_process_scope()

    def _publish(self, monkeypatch, allowed):
        from tools.scope_validator import set_process_scope

        monkeypatch.setenv("ARGUS_ALLOW_INTERNAL_TARGETS", "1")
        set_process_scope("eng-1", "allowlist", allowed)

    def test_authorized_opted_in_internal_target_is_allowed(self, monkeypatch):
        from agent.swarm import _is_authorized_target

        self._publish(monkeypatch, ["http://127.0.0.1:9000"])
        assert _is_authorized_target("http://127.0.0.1:9000/api", "eng-1") is True

    def test_opt_in_alone_is_not_authorization(self, monkeypatch):
        from agent.swarm import _is_authorized_target

        self._publish(monkeypatch, [])
        assert _is_authorized_target("http://127.0.0.1:9000/api", "eng-1") is False

    def test_authorized_without_opt_in_is_refused(self, no_opt_in):
        from agent.swarm import _is_authorized_target
        from tools.scope_validator import set_process_scope

        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:9000"])
        assert _is_authorized_target("http://127.0.0.1:9000/api", "eng-1") is False

    def test_metadata_stays_blocked(self, monkeypatch):
        from agent.swarm import _is_authorized_target

        self._publish(monkeypatch, ["http://169.254.169.254"])
        assert (
            _is_authorized_target("http://169.254.169.254/latest/meta-data/", "eng-1")
            is False
        )


class TestWebScannerInternalPolicy:
    """tools/web_scanner.py: the same opt-in + authorization decision."""

    @pytest.fixture(autouse=True)
    def clean_scope(self):
        from tools.scope_validator import clear_process_scope

        clear_process_scope()
        yield
        clear_process_scope()

    def _scanner(self, engagement_id="eng-1"):
        from tools.web_scanner import WebScanner

        scanner = object.__new__(WebScanner)
        scanner.engagement_id = engagement_id
        return scanner

    def test_authorized_opted_in_internal_target_is_allowed(self, opt_in):
        from tools.scope_validator import set_process_scope

        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:9000"])
        assert (
            self._scanner()._internal_target_authorized("http://127.0.0.1:9000") is True
        )

    def test_opt_in_alone_is_not_authorization(self, opt_in):
        assert (
            self._scanner()._internal_target_authorized("http://127.0.0.1:9000") is False
        )

    def test_no_engagement_cannot_authorize_an_internal_target(self, opt_in):
        from tools.scope_validator import set_process_scope

        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:9000"])
        assert (
            self._scanner(engagement_id="")._internal_target_authorized(
                "http://127.0.0.1:9000"
            )
            is False
        )


class TestWebScannerRedirectPolicy:
    """A redirect hop follows the same opt-in + authorization rule."""

    @pytest.fixture(autouse=True)
    def clean_scope(self):
        from tools.scope_validator import clear_process_scope

        clear_process_scope()
        yield
        clear_process_scope()

    def test_authorized_opted_in_internal_redirect_is_allowed(self, opt_in):
        from tools.scope_validator import set_process_scope
        from tools.web_scanner import _validate_redirect_chain

        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:9000"])
        assert (
            _validate_redirect_chain(
                "http://127.0.0.1:9000/admin", "http://127.0.0.1:9000", "eng-1"
            )
            is True
        )

    def test_internal_redirect_without_authorization_is_refused(self, opt_in):
        from tools.web_scanner import _validate_redirect_chain

        assert (
            _validate_redirect_chain(
                "http://127.0.0.1:9000/admin", "http://127.0.0.1:9000", "eng-1"
            )
            is False
        )

    def test_metadata_redirect_stays_blocked_when_authorized(self, opt_in):
        from tools.scope_validator import set_process_scope
        from tools.web_scanner import _validate_redirect_chain

        set_process_scope("eng-1", "allowlist", ["http://169.254.169.254"])
        assert (
            _validate_redirect_chain(
                "http://169.254.169.254/latest/meta-data/",
                "http://169.254.169.254",
                "eng-1",
            )
            is False
        )
