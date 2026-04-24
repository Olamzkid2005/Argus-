"""
Tests for WAF detection functionality in web_scanner.py
"""

import pytest
from unittest.mock import Mock
from tools.web_scanner import detect_waf


class TestDetectWAF:
    """Test cases for WAF detection function."""

    def test_cloudflare_detection_cf_ray_header(self):
        """Test Cloudflare detection via CF-RAY header."""
        mock_response = Mock()
        mock_response.headers = {'CF-RAY': '1234567890abcdef'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'cloudflare'
        assert 'indicator' in details

    def test_cloudflare_detection_cloudflare_in_body(self):
        """Test Cloudflare detection via cloudflare string in body."""
        mock_response = Mock()
        mock_response.headers = {}
        mock_response.text = '<html>protected by cloudflare</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'cloudflare'

    def test_modsecurity_detection(self):
        """Test ModSecurity detection via headers or body."""
        mock_response = Mock()
        mock_response.headers = {'Server': 'Apache (mod_security)'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'mod_security'

    def test_modsecurity_detection_secureflag(self):
        """Test ModSecurity detection via secureflag indicator."""
        mock_response = Mock()
        mock_response.headers = {'SecureFlag': 'enabled'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'mod_security'

    def test_blocked_content_patterns(self):
        """Test detection of blocked content patterns."""
        mock_response = Mock()
        mock_response.headers = {}
        mock_response.text = '<html>ACCESS DENIED: Your request has been blocked</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert 'blocked_content' in details
        assert details['blocked_content'] is True

    def test_blocked_content_forbidden(self):
        """Test detection of 'forbidden' blocked content pattern."""
        mock_response = Mock()
        mock_response.headers = {}
        mock_response.text = '<html>403 Forbidden</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert 'blocked_content' in details
        assert details['blocked_content'] is True

    def test_no_waf_present(self):
        """Test when no WAF is present."""
        mock_response = Mock()
        mock_response.headers = {'Server': 'simple-server'}
        mock_response.text = '<html>welcome to our website</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is False
        assert waf_type is None
        assert details == {}

    def test_aws_waf_detection(self):
        """Test AWS WAF detection."""
        mock_response = Mock()
        mock_response.headers = {'X-AWS-WAF': 'detected'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'aws_waf'

    def test_f5_bigip_detection(self):
        """Test F5 BIG-IP detection."""
        mock_response = Mock()
        mock_response.headers = {'Server': 'BigIPServer'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'f5_bigip'

    def test_incapsula_detection(self):
        """Test Incapsula detection."""
        mock_response = Mock()
        mock_response.headers = {'Cookie': 'visid_incap_12345=test'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'incapsula'

    def test_sucuri_detection(self):
        """Test Sucuri detection."""
        mock_response = Mock()
        mock_response.headers = {'X-Sucuri-ID': '12345'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'sucuri'

    def test_akamai_detection(self):
        """Test Akamai detection."""
        mock_response = Mock()
        mock_response.headers = {'X-Akamai-Transformed': '9 - 0 pmb=mTOE,1'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'akamai'

    def test_case_insensitive_header_check(self):
        """Test that header checking is case insensitive."""
        mock_response = Mock()
        mock_response.headers = {'CF-RAY': '1234567890abcdef'}
        mock_response.text = '<html>normal page</html>'

        detected, waf_type, details = detect_waf(mock_response, 'https://example.com')

        assert detected is True
        assert waf_type == 'cloudflare'


class TestWebScannerIntegration:
    """Test WAF integration in WebScanner class."""

    def test_scanner_tags_findings_with_waf_interference(self):
        """Test that findings are tagged with waf_interference when WAF detected."""
        from tools.web_scanner import WebScanner
        import requests

        scanner = WebScanner('https://example.com')

        # Mock the requests.get call
        mock_response = Mock()
        mock_response.headers = {'CF-RAY': '1234567890abcdef'}
        mock_response.text = '<html>normal page</html>'
        mock_response.status_code = 200

        # Simulate adding a finding after WAF detection
        scanner.waf_info = {
            'detected': True,
            'type': 'cloudflare',
            'details': {'indicator': 'cf-ray'}
        }

        finding = {'type': 'test', 'message': 'Test finding'}
        scanner.add_finding(finding)

        assert 'waf_interference' in finding
        assert finding['waf_interference'] is True
        assert finding['waf_type'] == 'cloudflare'

    def test_scanner_no_waf_tag_when_no_waf(self):
        """Test that findings are not tagged when no WAF detected."""
        from tools.web_scanner import WebScanner

        scanner = WebScanner('https://example.com')
        scanner.waf_info = {
            'detected': False,
            'type': None,
            'details': {}
        }

        finding = {'type': 'test', 'message': 'Test finding'}
        scanner.add_finding(finding)

        assert 'waf_interference' not in finding
        assert 'waf_type' not in finding
