"""
Tests for modern vulnerability checks in web_scanner.py
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, MagicMock

# Add argus-workers to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../argus-workers"))

from tools.web_scanner import WebScanner


@pytest.fixture
def scanner():
    """Create a WebScanner instance for testing."""
    s = WebScanner(timeout=5, rate_limit=0)
    s.target_url = "http://test.com"
    return s


class TestGraphQLIntrospection:
    def test_introspection_enabled(self, scanner):
        """Test GraphQL introspection detection."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"__schema": {"types": []}}}
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_graphql_introspection()
            # Check that finding was added
            assert any(f["type"] == "GRAPHQL_INTROSPECTION_ENABLED" for f in scanner.findings)
    
    def test_introspection_disabled(self, scanner):
        """Test when GraphQL introspection is disabled."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"errors": [{"message": "Introspection disabled"}]}
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_graphql_introspection()
            assert not any(f["type"] == "GRAPHQL_INTROSPECTION_ENABLED" for f in scanner.findings)


class TestJWTAlgorithmConfusion:
    def test_jwt_alg_none_accepted(self, scanner):
        """Test JWT alg:none vulnerability."""
        # Mock JWT token
        import base64
        header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({"user": "test"}).encode()).decode().rstrip("=")
        jwt_token = f"{header}.{payload}.signature"
        
        # Mock response with JWT
        mock_main_resp = MagicMock()
        mock_main_resp.status_code = 200
        mock_main_resp.text = f"token: {jwt_token}"
        
        # Mock response for none JWT test
        mock_test_resp = MagicMock()
        mock_test_resp.status_code = 200
        
        with patch.object(scanner, "_safe_request", side_effect=[mock_main_resp, mock_test_resp]):
            scanner.check_jwt_algorithm_confusion()
            assert any(f["type"] == "JWT_ALGORITHM_CONFUSION" for f in scanner.findings)
    
    def test_no_jwt_found(self, scanner):
        """Test when no JWT tokens are present."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "No tokens here"
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_jwt_algorithm_confusion()
            assert not any(f["type"] == "JWT_ALGORITHM_CONFUSION" for f in scanner.findings)


class TestPrototypePollution:
    def test_prototype_pollution_detected(self, scanner):
        """Test prototype pollution detection."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "isAdmin: true"
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_prototype_pollution()
            assert any(f["type"] == "PROTOTYPE_POLLUTION" for f in scanner.findings)
    
    def test_no_pollution(self, scanner):
        """Test when no prototype pollution is present."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not found"
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_prototype_pollution()
            assert not any(f["type"] == "PROTOTYPE_POLLUTION" for f in scanner.findings)


class TestOpenAPIDiscovery:
    def test_openapi_spec_found(self, scanner):
        """Test OpenAPI spec discovery."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"openapi": "3.0.0", "paths": {"/api/test": {}}}
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_openapi_discovery()
            assert any(f["type"] == "OPENAPI_SPEC_EXPOSED" for f in scanner.findings)
    
    def test_no_openapi_spec(self, scanner):
        """Test when no OpenAPI spec is exposed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        
        with patch.object(scanner, "_safe_request", return_value=mock_resp):
            scanner.check_openapi_discovery()
            assert not any(f["type"] == "OPENAPI_SPEC_EXPOSED" for f in scanner.findings)


class TestScanIntegration:
    def test_new_checks_in_scan(self, scanner):
        """Test that new checks are called in main scan flow."""
        with patch.object(scanner, "check_graphql_introspection") as mock_graphql, \
             patch.object(scanner, "check_jwt_algorithm_confusion") as mock_jwt, \
             patch.object(scanner, "check_openapi_discovery") as mock_openapi:
            
            # Mock other checks to avoid side effects
            with patch.object(scanner, "check_security_headers"), \
                 patch.object(scanner, "check_csp"), \
                 patch.object(scanner, "check_cookies"), \
                 patch.object(scanner, "check_cors"), \
                 patch.object(scanner, "check_sensitive_files"), \
                 patch.object(scanner, "check_js_secrets"), \
                 patch.object(scanner, "check_open_redirects"), \
                 patch.object(scanner, "check_host_header_injection"), \
                 patch.object(scanner, "check_verb_tampering"), \
                 patch.object(scanner, "check_debug_endpoints"), \
                 patch.object(scanner, "check_auth_endpoints"), \
                 patch.object(scanner, "check_mass_assignment"), \
                 patch.object(scanner, "check_xss"), \
                 patch.object(scanner, "check_ssti"), \
                 patch.object(scanner, "check_lfi"), \
                 patch.object(scanner, "check_xxe"):
                
                scanner.scan("http://test.com")
                mock_graphql.assert_called_once()
                mock_jwt.assert_called_once()
                mock_openapi.assert_called_once()
