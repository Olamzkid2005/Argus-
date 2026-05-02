"""
Tests for API Security Scanner
"""
from unittest.mock import Mock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from tools.api_scanner import APISecurityScanner


class TestAPISecurityScanner:
    """Test APISecurityScanner"""

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_scan_missing_security_headers(self, scanner):
        mock_response = Mock()
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.status_code = 200

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com")

        header_findings = [f for f in findings if f["type"] == "MISSING_API_SECURITY_HEADERS"]
        assert len(header_findings) == 1
        assert header_findings[0]["severity"] == "MEDIUM"

    def test_scan_wildcard_cors(self, scanner):
        mock_response = Mock()
        mock_response.headers = {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        }
        mock_response.status_code = 200

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com")

        cors_findings = [f for f in findings if f["type"] == "WILDCARD_CORS_API"]
        assert len(cors_findings) == 1
        assert cors_findings[0]["severity"] == "HIGH"

    def test_scan_graphql_introspection_enabled(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"data": {"__schema": {"types": []}}}

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com", api_type="graphql")

        intro_findings = [f for f in findings if "INTROSPECTION" in f["type"] or "GRAPHQL" in f["type"]]
        assert len(intro_findings) >= 1

    def test_scan_graphql_introspection_disabled(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"errors": [{"message": "Introspection is disabled"}]}

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com", api_type="graphql")

        assert isinstance(findings, list)

    def test_scan_with_api_key_auth(self, scanner):
        mock_response = Mock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.status_code = 200

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan(
                "https://api.example.com",
                auth_config={"type": "api_key", "header": "X-API-Key", "key": "test-key-123"}
            )

        assert isinstance(findings, list)

    def test_scan_rate_limiting(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com")

        assert isinstance(findings, list)

    def test_scan_request_failure(self, scanner):
        with patch.object(scanner.session, "request", side_effect=RequestsConnectionError("Connection error")):
            findings = scanner.scan("https://api.example.com")
        assert isinstance(findings, list)
        assert len(findings) == 0

    def test_scan_rest_endpoints(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {}

        with patch.object(scanner.session, "request", return_value=mock_response):
            findings = scanner.scan("https://api.example.com", api_type="rest")

        assert isinstance(findings, list)
