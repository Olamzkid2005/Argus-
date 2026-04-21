"""
Tests for API Security Scanner
"""
import pytest
from unittest.mock import Mock, patch
from tools.api_scanner import APISecurityScanner


class TestAPISecurityScanner:
    """Test APISecurityScanner"""

    @pytest.fixture
    def scanner(self):
        return APISecurityScanner()

    def test_analyze_security_headers(self, scanner):
        mock_response = Mock()
        mock_response.headers = {
            "Content-Type": "application/json",
            "X-Frame-Options": "DENY"
        }
        mock_response.status_code = 200

        with patch("requests.get", return_value=mock_response):
            result = scanner.analyze_security_headers("https://api.example.com")

        assert result["missing_headers"]
        assert "Strict-Transport-Security" in result["missing_headers"]
        assert result["status_code"] == 200

    def test_test_graphql_introspection_enabled(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"__schema": {"types": []}}}

        with patch("requests.post", return_value=mock_response):
            result = scanner.test_graphql("https://api.example.com/graphql")

        assert result["introspection_enabled"] is True
        assert result["findings"]

    def test_test_graphql_introspection_disabled(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"errors": [{"message": "Introspection is disabled"}]}

        with patch("requests.post", return_value=mock_response):
            result = scanner.test_graphql("https://api.example.com/graphql")

        assert result["introspection_enabled"] is False

    def test_test_authentication_jwt_none_alg(self, scanner):
        import jwt
        token = jwt.encode({"sub": "test"}, "", algorithm="none")
        result = scanner.test_authentication("https://api.example.com", auth_type="jwt", token=token)
        assert result["jwt_tests"]["algorithm_none_vulnerable"] is True

    def test_test_authentication_api_key_strength(self, scanner):
        result = scanner.test_authentication("https://api.example.com", auth_type="api_key", api_key="abc123")
        assert result["api_key_tests"]["strength"] == "weak"
        assert result["api_key_tests"]["length"] == 6

    def test_test_rate_limiting(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}

        with patch("requests.get", return_value=mock_response):
            result = scanner.test_rate_limiting("https://api.example.com", burst_size=5)

        assert result["tested_burst_size"] == 5
        assert result["responses_200"] == 5
        assert result["rate_limited"] is False

    def test_run_full_scan(self, scanner):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"data": {"__schema": {}}}

        with patch("requests.get", return_value=mock_response):
            with patch("requests.post", return_value=mock_response):
                result = scanner.run_full_scan("https://api.example.com")

        assert "security_headers" in result
        assert "graphql" in result
        assert "authentication" in result
        assert "rate_limiting" in result
        assert result["scan_time_ms"] >= 0
