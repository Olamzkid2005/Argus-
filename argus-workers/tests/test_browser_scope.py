"""The browser scan subprocess must be authorized by the run, not by its URL.

Stage 3.2 item 3. ``tools/_browser_scan_worker.py`` used to validate the shape
of the URL it was handed (scheme + SSRF) and then scan it, whatever the run was
authorized to do. The parent now passes the run's scope and the worker applies
``tools.scope_validator.authorize_target`` to the top-level URL, every
navigation, and every request the page makes on its own.
"""

from __future__ import annotations

from tools.browser_scope import (
    BrowserScopePayload,
    parse_scope_payload,
    request_authorized,
)
from tools.scope_validator import clear_process_scope


class TestScopePayload:
    def test_absent_payload_means_no_policy(self):
        assert parse_scope_payload(None) is None
        assert parse_scope_payload("") is None

    def test_malformed_payload_is_ignored_rather_than_permissive(self):
        assert parse_scope_payload("{not json") is None
        assert parse_scope_payload(["https://example.com"]) is None

    def test_empty_payload_is_not_a_policy(self):
        assert parse_scope_payload({"mode": "allowlist", "allowed_targets": []}) is None

    def test_parses_json_and_dict_forms(self):
        from_json = parse_scope_payload(
            '{"mode": "allowlist", "allowed_targets": ["https://example.com"]}'
        )
        from_dict = parse_scope_payload(
            {"mode": "allowlist", "allowed_targets": ["https://example.com"]}
        )

        assert from_json == from_dict
        assert from_json is not None
        assert from_json.configured is True
        assert from_json.allowed_targets == ("https://example.com",)

    def test_unknown_mode_falls_back_to_allowlist(self):
        payload = parse_scope_payload(
            {"mode": "whatever", "allowed_targets": ["https://example.com"]}
        )

        assert payload is not None
        assert payload.mode == "allowlist"


class TestRequestAuthorization:
    def setup_method(self):
        clear_process_scope()

    def teardown_method(self):
        clear_process_scope()

    def test_without_a_scope_only_the_scan_targets_origin_is_reached(self):
        target = "https://example.com/start"

        assert request_authorized("https://example.com/admin", target) is True
        assert request_authorized("https://example.com:8443/admin", target) is False
        assert request_authorized("http://example.com/admin", target) is False
        assert request_authorized("https://api.example.com/admin", target) is False
        assert request_authorized("https://evil.test/steal", target) is False

    def test_non_network_urls_are_never_authorized(self):
        assert request_authorized("javascript:alert(1)", "https://example.com/x") is False
        assert request_authorized("file:///etc/passwd", "https://example.com/x") is False

    def test_an_origin_scope_refuses_other_scheme_and_port(self):
        scope = BrowserScopePayload(
            mode="allowlist", allowed_targets=("https://example.com",)
        )

        assert (
            request_authorized("https://example.com/admin", "https://example.com", scope)
            is True
        )
        assert (
            request_authorized(
                "https://example.com:8443/admin", "https://example.com", scope
            )
            is False
        )
        assert (
            request_authorized("http://example.com/admin", "https://example.com", scope)
            is False
        )

    def test_the_scope_wins_over_the_target_url(self):
        # A target the run is not authorized for cannot authorize itself by
        # being the URL the worker was invoked with.
        scope = BrowserScopePayload(
            mode="allowlist", allowed_targets=("https://other.test",)
        )

        assert (
            request_authorized("https://example.com/x", "https://example.com/x", scope)
            is False
        )

    def test_a_host_port_scope_does_not_authorize_another_port(self):
        scope = BrowserScopePayload(mode="allowlist", allowed_targets=("example.com:8080",))

        assert request_authorized("http://example.com:8080/x", "http://example.com:8080", scope) is True
        assert (
            request_authorized("http://example.com:9090/x", "http://example.com:8080", scope)
            is False
        )
