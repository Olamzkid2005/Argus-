"""Authorization compares parsed target components, never strings.

Stage 3.2 item 1. Two textual tests used to grant authorization: an allowed
pattern counted if it was a *prefix* of the target (ignoring scheme and port),
and a bare hostname counted if it equalled the host of an allowed URL (so one
``host:port`` permission authorized every port on that host). Both are removed;
every path now parses the target and asks a typed permission about it.

The cases below are the ones that were authorized before this change and must
not be: another port, another scheme, a sibling origin, a path on a different
port, a redirect hop to an out-of-scope origin, and malformed input.
"""

from __future__ import annotations

import pytest

from tools.scope_validator import (
    TargetParseError,
    authorize_target,
    clear_process_scope,
    parse_scope_entry,
    parse_target,
    set_process_scope,
    validate_target_scope,
)


@pytest.fixture(autouse=True)
def clean_scope():
    """Every test starts and ends with no published run scope."""
    clear_process_scope()
    yield
    clear_process_scope()


class TestBroadHostPermission:
    """A host/port entry is broad over paths and schemes, not over ports."""

    def test_host_port_entry_does_not_authorize_another_port(self):
        set_process_scope("eng-1", "allowlist", ["example.com:8080"])

        assert (
            authorize_target("http://example.com:8080/any/path", "eng-1").authorized
            is True
        )
        assert (
            authorize_target("http://example.com:9090/any/path", "eng-1").authorized
            is False
        ), "a host:port permission must not authorize another port"

    def test_host_entry_authorizes_any_scheme_port_and_path(self):
        set_process_scope("eng-1", "allowlist", ["example.com"])

        assert (
            authorize_target("https://example.com:8443/deep/path?q=1", "eng-1").authorized
            is True
        )
        assert authorize_target("http://example.com/", "eng-1").authorized is True
        assert authorize_target("http://other.example.net/", "eng-1").authorized is False

    def test_wildcard_host_entry_matches_one_label_only(self):
        set_process_scope("eng-1", "allowlist", ["*.example.com"])

        assert authorize_target("https://api.example.com/v1", "eng-1").authorized is True
        assert (
            authorize_target("https://deep.api.example.com/v1", "eng-1").authorized
            is False
        )


class TestOriginPermission:
    """An origin entry grants scheme+host+port — not a sibling origin."""

    def test_origin_authorizes_its_own_paths(self):
        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert authorize_target("https://example.com/", "eng-1").authorized is True
        assert authorize_target("https://example.com/api/v2?q=1", "eng-1").authorized is True

    def test_origin_does_not_authorize_another_scheme(self):
        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert authorize_target("http://example.com/", "eng-1").authorized is False

    def test_origin_does_not_authorize_another_port(self):
        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert authorize_target("https://example.com:8443/", "eng-1").authorized is False
        assert authorize_target("https://example.com:443/", "eng-1").authorized is True

    def test_origin_does_not_authorize_a_sibling_origin(self):
        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert authorize_target("https://api.example.com/", "eng-1").authorized is False
        assert (
            authorize_target("https://example.com.evil.test/", "eng-1").authorized
            is False
        )

    def test_path_entry_requires_a_segment_boundary(self):
        set_process_scope("eng-1", "allowlist", ["https://example.com/app"])

        assert authorize_target("https://example.com/app/x", "eng-1").authorized is True
        assert authorize_target("https://example.com/application", "eng-1").authorized is False


class TestMalformedTargets:
    """Invalid input is refused rather than matched leniently."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "   ",
            "not a url",
            "http://",
            "http://exa mple.com/",
            "ftp://example.com/",
            "javascript:alert(1)",
            "//example.com/x",
            "example.com/path",  # scheme-less, more than host[:port]
            "https://example.com:99999/",
            "https://user:pass@example.com/",
            "https://example.com\\admin",
        ],
    )
    def test_authorize_target_rejects_malformed_input(self, bad):
        result = authorize_target(bad, "eng-1", allowed_targets=["*"])

        assert result.authorized is False
        assert result.target is None

    def test_scope_check_rejects_malformed_target_too(self):
        # Even a glob an operator wrote cannot authorize an unparseable value.
        assert (
            validate_target_scope(
                "example.com/admin", allowed_targets=["*example.com*"]
            )
            is False
        )

    def test_parse_target_normalizes_defaults(self):
        assert parse_target("https://example.com").port == 443
        assert parse_target("http://example.com").port == 80
        assert parse_target("https://example.com/p?q=1#frag").url == (
            "https://example.com/p?q=1"
        )
        assert parse_target("https://EXAMPLE.com./").hostname == "example.com"

    def test_parse_target_keeps_bare_host_form(self):
        parsed = parse_target("127.0.0.1")

        assert parsed.host_form is True
        assert parsed.scheme == ""
        assert parsed.port is None

    def test_parse_target_errors_are_reported(self):
        with pytest.raises(TargetParseError):
            parse_target("example.com/path")


class TestPermissionKinds:
    def test_entries_are_classified_by_kind(self):
        assert parse_scope_entry("example.com").kind == "host"
        assert parse_scope_entry("example.com:8080").kind == "host"
        assert parse_scope_entry("https://example.com").kind == "origin"
        assert parse_scope_entry("https://example.com/app").kind == "path"
        # An operator's explicit glob stays a glob, not a typed permission.
        assert parse_scope_entry("*example.com*") is None


class TestRedirectHop:
    """A redirect hop follows the same parsed authorization."""

    def test_redirect_to_another_port_is_refused(self):
        from tools.web_scanner import _validate_redirect_chain

        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert (
            _validate_redirect_chain(
                "https://example.com:8443/admin",
                "https://example.com",
                "eng-1",
            )
            is False
        )
        assert (
            _validate_redirect_chain(
                "https://example.com/admin", "https://example.com", "eng-1"
            )
            is True
        )

    def test_redirect_to_out_of_scope_origin_is_refused(self):
        from tools.web_scanner import _validate_redirect_chain

        set_process_scope("eng-1", "allowlist", ["https://example.com"])

        assert (
            _validate_redirect_chain(
                "https://example.org/landing", "https://example.com", "eng-1"
            )
            is False
        )

    def test_without_a_scope_only_the_scan_targets_origin_is_reachable(self):
        from tools.web_scanner import _validate_redirect_chain

        assert (
            _validate_redirect_chain(
                "https://example.com:8443/x", "https://example.com/x"
            )
            is False
        ), "same host, different port is a different origin"
        assert (
            _validate_redirect_chain("http://example.com/x", "https://example.com/x")
            is False
        )
        assert (
            _validate_redirect_chain("https://api.example.com/x", "https://example.com/x")
            is False
        ), "a hostname-suffix neighbour is not the same origin"
        assert (
            _validate_redirect_chain("https://example.com/x", "https://example.com/x")
            is True
        )


class TestCallerPathsUseTheEntryPoint:
    """Scanner crawl and swarm discovery share the one decision."""

    def test_crawl_link_follows_parsed_origin_rules(self):
        from tools.web_scanner import _is_in_scope

        assert _is_in_scope("https://example.com/x", "https://example.com", None) is True
        assert _is_in_scope("https://example.org/x", "https://example.com", None) is False
        assert (
            _is_in_scope("https://example.org/x", "https://example.com", "eng-1") is False
        )

    def test_swarm_peer_discovery_refuses_another_port_and_scheme_less_paths(self):
        from agent.swarm import _is_authorized_target

        set_process_scope("eng-1", "allowlist", ["example.com:8080"])

        assert _is_authorized_target("http://example.com:8080/x", "eng-1") is True
        assert _is_authorized_target("http://example.com:9090/x", "eng-1") is False
        assert _is_authorized_target("example.com/admin", "eng-1") is False


class TestBareHostPortInheritance:
    """The one exception in the parsed rules, pinned so it cannot drift.

    A port scanner is handed ``host`` with no port, so there is nothing to
    compare against a ``host:port`` entry. The decision inherits the entry's
    port and reports it as ``inherited_port``; a target that names its own port
    must still match. Choosing a different port is therefore a caller bug that
    is visible in the decision, not an implicit widening of scope.
    """

    @pytest.fixture(autouse=True)
    def allow_internal(self, monkeypatch):
        # 127.0.0.1 is an internal target; scanning it needs the explicit opt-in
        # as well as the scope entry (Stage 3.1 item 3).
        monkeypatch.setenv("ARGUS_ALLOW_INTERNAL_TARGETS", "1")

    def test_bare_host_inherits_the_authorized_port(self):
        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:8877"])

        result = authorize_target("127.0.0.1", "eng-1")

        assert result.authorized is True
        assert result.inherited_port == 8877

    def test_explicit_target_port_must_match(self):
        set_process_scope("eng-1", "allowlist", ["http://127.0.0.1:8877"])

        assert authorize_target("127.0.0.1:9999", "eng-1").authorized is False
        assert authorize_target("127.0.0.1:8877", "eng-1").inherited_port is None

    def test_host_wide_entry_inherits_nothing(self):
        set_process_scope("eng-1", "allowlist", ["127.0.0.1"])

        result = authorize_target("127.0.0.1", "eng-1")

        assert result.authorized is True
        assert result.inherited_port is None, (
            "an entry with no port authorizes the host as-is; there is no single "
            "port to report, so callers must not claim one"
        )
