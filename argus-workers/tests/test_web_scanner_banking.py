"""Regression tests for the card / merchant / session-lifecycle checks.

These classes were unreachable before: the scanner had no card or merchant
endpoint knowledge and never replayed a token after logout, so "predictable
card numbers", "mass assignment in card limits", "merchant API key returned",
"no server-side token invalidation" and "no transaction verification" could
not be reported even on a target that has them all.
"""

from unittest.mock import Mock, patch

import requests

from tool_core.base import ToolContext
from tools.ai_vuln_scanner import AIVulnScanner
from tools.web_scanner import WebScanner


def _response(status_code=200, payload=None, text="", url=""):
    resp = Mock(status_code=status_code)
    resp.headers = {}
    resp.text = text
    resp.url = url
    resp.json.return_value = payload if payload is not None else {}
    return resp


def _scanner(authenticated=True):
    scanner = WebScanner()
    scanner.target_url = "https://bank.example"
    scanner._authenticated = authenticated
    scanner._base_response = None
    return scanner


def _types(scanner):
    return {f["type"] for f in (scanner._builder.findings if scanner._builder else [])}


class TestAuthenticationFallback:
    def test_bare_authmanager_session_falls_back_to_json_login(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"
        scanner._credentials = {"username": "u", "password": "p"}
        bare = requests.Session()

        def fake_json_login(session, username, password):
            session.headers["Authorization"] = "Bearer token"
            return session

        with (
            patch("tools.auth_manager.AuthManager.authenticate", return_value=bare),
            patch.object(scanner, "_json_login", side_effect=fake_json_login),
        ):
            assert scanner._authenticate_with_credentials() is True
        assert scanner.session.headers["Authorization"] == "Bearer token"

    def test_session_without_credentials_is_not_reported_authenticated(self):
        scanner = WebScanner()
        scanner.target_url = "https://bank.example"
        scanner._credentials = {"username": "u", "password": "p"}

        with (
            patch(
                "tools.auth_manager.AuthManager.authenticate",
                return_value=requests.Session(),
            ),
            patch.object(scanner, "_json_login", return_value=None),
        ):
            assert scanner._authenticate_with_credentials() is False
        assert scanner._authenticated is False


class TestCardSecurity:
    def test_plaintext_card_details_are_reported(self):
        scanner = _scanner()

        def fake_request(method, url, **kwargs):
            if method == "GET" and url.endswith("/api/virtual-cards"):
                return _response(
                    payload={
                        "cards": [
                            {
                                "id": 4,
                                "card_number": "4111111111111111",
                                "cvv": "123",
                                "expiry": "12/28",
                            }
                        ]
                    },
                    url=url,
                )
            return None

        with patch.object(scanner, "_safe_request", side_effect=fake_request):
            scanner.check_card_security()

        assert "CARD_DETAILS_EXPOSED" in _types(scanner)

    def test_two_cards_with_sequential_numbers_are_predictable(self):
        scanner = _scanner()
        created = {"n": 0}

        def fake_request(method, url, **kwargs):
            if method == "GET":
                return None
            if "/create" in url:
                created["n"] += 1
                return _response(
                    payload={
                        "card_details": {
                            "id": 7,
                            "card_number": f"41111111111110{created['n']:02d}",
                            "cvv": "321",
                        }
                    },
                    url=url,
                )
            if url.endswith("/update-limit"):
                return _response(payload={"status": "ok", "limit": 99999}, url=url)
            return None

        with patch.object(scanner, "_safe_request", side_effect=fake_request):
            scanner.check_card_security()

        assert "PREDICTABLE_CARD_NUMBER" in _types(scanner)

    def test_limit_update_reflecting_injected_fields_is_mass_assignment(self):
        scanner = _scanner()

        def fake_request(method, url, **kwargs):
            if method == "GET":
                return None
            if url.endswith("/create"):
                return _response(
                    payload={"card_details": {"id": 9, "card_number": "4111111111111111"}},
                    url=url,
                )
            if url.endswith("/update-limit"):
                return _response(
                    payload={"status": "ok", "limit": 99999, "balance": 999999},
                    url=url,
                )
            return None

        with patch.object(scanner, "_safe_request", side_effect=fake_request):
            scanner.check_card_security()

        assert "MASS_ASSIGNMENT_CARD_LIMITS" in _types(scanner)

    def test_anonymous_scan_does_not_create_cards(self):
        scanner = _scanner(authenticated=False)

        with patch.object(
            scanner, "_safe_request", side_effect=AssertionError("must not request")
        ):
            scanner.check_card_security()

        assert _types(scanner) == set()


class TestCardActivity:
    def test_new_card_with_empty_activity_log_is_reported(self):
        scanner = _scanner()
        scanner._probe_cards = [{"url": "https://bank.example/api/virtual-cards/create", "card": {"id": 3}}]

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(payload={"transactions": []}),
        ):
            scanner.check_card_activity_monitoring()

        assert "LACK_OF_CARD_ACTIVITY_MONITORING" in _types(scanner)

    def test_activity_entries_are_not_a_finding(self):
        scanner = _scanner()
        scanner._probe_cards = [{"url": "https://bank.example/api/virtual-cards/create", "card": {"id": 3}}]

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(payload={"transactions": [{"type": "created"}]}),
        ):
            scanner.check_card_activity_monitoring()

        assert _types(scanner) == set()


class TestTransactionVerification:
    def test_charge_without_challenge_is_no_verification(self):
        scanner = _scanner()

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(payload={"status": "approved", "payment_id": 12}),
        ):
            scanner.check_transaction_verification()

        assert "NO_TRANSACTION_VERIFICATION" in _types(scanner)

    def test_otp_challenge_is_not_a_finding(self):
        scanner = _scanner()

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(payload={"status": "otp_required"}),
        ):
            scanner.check_transaction_verification()

        assert _types(scanner) == set()


class TestMerchantApi:
    def test_api_key_in_login_response_is_reported(self):
        scanner = _scanner()

        def fake_request(method, url, **kwargs):
            if url.endswith("/register"):
                return _response(payload={"status": "success", "merchant_id": 5}, url=url)
            if url.endswith("/login"):
                return _response(
                    payload={"token": "merchant-token", "api_key": "mk_live_0123456789abcdef"},
                    url=url,
                )
            return None

        with (
            patch.object(scanner, "_safe_request", side_effect=fake_request),
            patch("requests.Session.get", return_value=_response(status_code=404)),
        ):
            scanner.check_merchant_api()

        assert "MERCHANT_KEY_IN_RESPONSE" in _types(scanner)

    def test_merchant_token_reading_other_payments_is_bola(self):
        scanner = _scanner()

        def fake_request(method, url, **kwargs):
            if url.endswith("/register"):
                return _response(payload={"status": "success", "merchant_id": 5}, url=url)
            if url.endswith("/login"):
                return _response(payload={"token": "merchant-token"}, url=url)
            return None

        payments = {"payments": [{"id": 1, "amount": 10, "merchant_id": 1}]}
        with (
            patch.object(scanner, "_safe_request", side_effect=fake_request),
            patch("requests.Session.get", return_value=_response(payload=payments)),
        ):
            scanner.check_merchant_api()

        assert "BOLA" in _types(scanner)


class TestTokenInvalidation:
    def test_token_still_valid_after_logout_is_reported(self):
        scanner = _scanner()
        scanner.session = Mock()
        scanner.session.headers = {"Authorization": "Bearer abc.def.ghi"}
        scanner.session.cookies = []
        scanner.session.request.return_value = _response(payload={"status": "ok"})

        with (
            patch.object(scanner, "_safe_request", return_value=_response(payload={"user": "a"})),
            patch("requests.Session.get", return_value=_response(payload={"user": "a"})),
        ):
            scanner.check_token_invalidation()

        assert "NO_SERVER_SIDE_TOKEN_INVALIDATION" in _types(scanner)

    def test_rejected_replay_is_not_a_finding(self):
        scanner = _scanner()
        scanner.session = Mock()
        scanner.session.headers = {"Authorization": "Bearer abc.def.ghi"}
        scanner.session.cookies = []
        scanner.session.request.return_value = _response(payload={"status": "ok"})

        with (
            patch.object(scanner, "_safe_request", return_value=_response(payload={"user": "a"})),
            patch("requests.Session.get", return_value=_response(status_code=401)),
        ):
            scanner.check_token_invalidation()

        assert _types(scanner) == set()


class TestAiSystemInfo:
    def test_exposed_model_and_prompt_are_reported(self):
        scanner = AIVulnScanner()
        scanner.target_url = "https://bank.example"
        scanner._builder = Mock()

        with patch.object(
            scanner,
            "_safe_request",
            return_value=_response(
                payload={"system_info": {"model": "deepseek-chat", "provider": "deepseek", "system_prompt": "You are a bank agent"}},
                text='{"system_info": {"model": "deepseek-chat", "api_provider": "deepseek", "system_prompt": "You are a bank agent"}}',
            ),
        ):
            scanner._check_system_info_exposure()

        assert scanner._builder.add.called
        assert scanner._builder.add.call_args[0][0] == "AI_SYSTEM_INFO_EXPOSURE"

    def test_hint_endpoints_are_read_from_extra(self):
        ctx = ToolContext(target="https://bank.example")
        ctx._ai_endpoints = '["/api/ai/chat"]'

        assert AIVulnScanner._hint_endpoints(ctx) == ["/api/ai/chat"]
