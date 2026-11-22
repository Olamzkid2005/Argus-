"""Regression tests for the authenticated surface of the web scanner.

Why these exist: the scanner ran every request logged out. The executor does
forward engagement credentials (``--extra`` -> ``ctx._email/_password``), but
WebScanner never read them, so auth/BOLA/transaction checks answered 401 and
the planted auth/IDOR findings on the labs were invisible. These tests pin the
contract: credentials are picked up from the context, a failed login degrades
instead of raising, and BOLA is only reported when the object really belongs
to another principal.
"""

from unittest.mock import Mock, patch

from tool_core.base import ToolContext
from tools.web_scanner import WebScanner


def _response(status_code=200, payload=None, text="", url=""):
    resp = Mock(status_code=status_code)
    resp.headers = {}
    resp.text = text
    resp.url = url
    resp.json.return_value = payload if payload is not None else {}
    return resp


class TestCredentialExtraction:
    def test_reads_the_extra_attributes_run_agent_tool_sets(self):
        ctx = ToolContext(target="https://bank.example")
        ctx._email = "attacker@example.test"
        ctx._password = "hunter2"

        creds = WebScanner._extract_credentials(ctx)

        assert creds["email"] == "attacker@example.test"
        assert creds["password"] == "hunter2"

    def test_reads_a_credentials_mapping_and_json_string(self):
        ctx = ToolContext(target="https://bank.example")
        ctx._credentials = {"username": "alice", "password": "pw"}

        assert WebScanner._extract_credentials(ctx)["username"] == "alice"

        ctx._credentials = '{"username": "bob", "password": "pw2"}'
        assert WebScanner._extract_credentials(ctx)["username"] == "bob"

    def test_no_credentials_is_an_empty_mapping(self):
        assert WebScanner._extract_credentials(ToolContext(target="https://x.test")) == {}


class TestAuthentication:
    def test_no_credentials_means_anonymous_scan(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"

        assert scanner._authenticate_with_credentials() is False
        assert scanner._authenticated is False

    def test_failed_login_does_not_raise_or_claim_authentication(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"
        scanner._credentials = {"email": "a", "password": "b"}

        with patch("tools.auth_manager.AuthManager.authenticate", side_effect=RuntimeError("nope")):
            assert scanner._authenticate_with_credentials() is False

        assert scanner._authenticated is False


class TestBola:
    def test_authenticated_session_reading_another_owner_is_bola(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"
        scanner._authenticated = True

        def fake_request(method, url, **kwargs):
            if url.endswith("/api/data/2"):
                return _response(
                    payload={"id": 2, "owner": "victim", "amount": 900},
                    url=url,
                )
            return None

        with (
            patch.object(scanner, "_own_identity", return_value={"attacker"}),
            patch.object(scanner, "_safe_request", side_effect=fake_request),
        ):
            scanner.check_bola()

        bola = [f for f in scanner._builder.findings if f["type"] == "BOLA"]
        assert len(bola) == 1
        assert bola[0]["severity"] == "HIGH"
        assert bola[0]["evidence"]["object_owner"] == ["victim"]
        assert bola[0]["evidence"]["own_identity"] == ["attacker"]

    def test_own_object_is_not_a_finding(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"
        scanner._authenticated = True

        with (
            patch.object(scanner, "_own_identity", return_value={"attacker"}),
            patch.object(
                scanner,
                "_safe_request",
                return_value=_response(payload={"id": 1, "owner": "attacker"}),
            ),
        ):
            scanner.check_bola()

        assert scanner._builder is None or scanner._builder.findings == []

    def test_unauthenticated_scan_skips_bola(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"

        with patch.object(scanner, "_safe_request", side_effect=AssertionError("must not request")):
            scanner.check_bola()

        assert scanner._builder is None or scanner._builder.findings == []

    def test_owner_values_are_found_through_nesting(self):
        payload = {"data": {"items": [{"user_id": 7}, {"owner": "bob"}]}, "ok": True}
        assert WebScanner._owner_values(payload) == {"7", "bob"}


class TestSsrf:
    def test_connection_error_in_response_is_ssrf_evidence(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(
                status_code=500,
                text="Failed to connect: [Errno 111] Connection refused",
                url="https://bank.example/api/profile/image",
            ),
        ):
            scanner.check_ssrf()

        ssrf = [f for f in scanner._builder.findings if f["type"] == "SSRF"]
        assert len(ssrf) == 1
        assert ssrf[0]["severity"] == "HIGH"
        assert ssrf[0]["evidence"]["canary"].startswith("http://127.0.0.1:1/")

    def test_a_normal_response_is_not_ssrf(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(text='{"avatar_url": "/img/a.png"}'),
        ):
            scanner.check_ssrf()

        assert scanner._builder is None or scanner._builder.findings == []


class TestGraphqlContent:
    def test_deep_query_without_a_limit_is_reported(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example/graphql"

        def fake_request(method, url, **kwargs):
            body = kwargs.get("json") or {}
            if body.get("query") == WebScanner.GRAPHQL_DEPTH_QUERY:
                return _response(payload={"data": {"a": {}}}, url=url)
            if "__argus_no_such_field_xyz" in str(body.get("query", "")):
                return _response(
                    payload={"errors": [{"message": "Cannot query field"}]}, url=url
                )
            return _response(payload={"data": {"__schema": {"types": []}}}, url=url)

        with patch.object(scanner, "_safe_request", side_effect=fake_request):
            scanner._check_graphql_depth_and_errors("https://bank.example/graphql")

        types = {f["type"] for f in scanner._builder.findings}
        assert "GRAPHQL_DEPTH_LIMIT_MISSING" in types

    def test_raw_error_disclosure_is_reported(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example/graphql"

        def fake_request(method, url, **kwargs):
            body = kwargs.get("json") or {}
            if "__argus_no_such_field_xyz" in str(body.get("query", "")):
                return _response(
                    text="Error: Cannot query field. Did you mean 'id'? at resolver.js:42",
                    url=url,
                )
            return _response(payload={"data": {}, "errors": [{"message": "depth limit"}]}, url=url)

        with patch.object(scanner, "_safe_request", side_effect=fake_request):
            scanner._check_graphql_depth_and_errors("https://bank.example/graphql")

        types = {f["type"] for f in scanner._builder.findings}
        assert "VERBOSE_API_ERROR" in types
