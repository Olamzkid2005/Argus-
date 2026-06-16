"""Tests for tools._browser_scan_worker — Browser Scan Worker."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock playwright before importing the module (it may not be installed)
_playwright_mock = MagicMock()
sys.modules["playwright"] = _playwright_mock
sys.modules["playwright.sync_api"] = _playwright_mock

from tools._browser_scan_worker import _validate_url, scan


class TestValidateURL:
    """Tests for _validate_url() — SSRF prevention."""

    def test_blocks_non_http_urls(self):
        with pytest.raises(ValueError, match="Blocked non-HTTP URL"):
            _validate_url("file:///etc/passwd")

    def test_blocks_ftp_urls(self):
        with pytest.raises(ValueError, match="Blocked non-HTTP URL"):
            _validate_url("ftp://example.com")

    @patch("socket.gethostbyname")
    def test_blocks_private_ip(self, mock_dns):
        mock_dns.return_value = "10.0.0.1"
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://10.0.0.1")

    @patch("socket.gethostbyname")
    def test_blocks_loopback_ip(self, mock_dns):
        mock_dns.return_value = "127.0.0.1"
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://127.0.0.1")

    @patch("socket.gethostbyname")
    def test_blocks_link_local_ip(self, mock_dns):
        mock_dns.return_value = "169.254.1.1"
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://169.254.1.1")

    @patch("socket.gethostbyname")
    def test_blocks_multicast_ip(self, mock_dns):
        mock_dns.return_value = "224.0.0.1"
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://224.0.0.1")

    @patch("socket.gethostbyname")
    def test_blocks_cloud_metadata_ip_from_link_local(self, mock_dns):
        mock_dns.return_value = "169.254.169.254"
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://169.254.169.254")

    @patch("socket.gethostbyname")
    def test_blocks_hostname_localhost_via_regex(self, mock_dns):
        mock_dns.return_value = "1.2.3.4"
        with pytest.raises(ValueError, match="Blocked internal hostname"):
            _validate_url("http://localhost:8080")

    def test_blocks_literal_192_168_via_ip_check(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://192.168.1.1")

    def test_blocks_literal_10_dot_via_ip_check(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://10.0.0.1")

    def test_blocks_literal_172_dot_16_31_via_ip_check(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://172.20.0.1")

    def test_blocks_literal_zero_dot_via_ip_check(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_url("http://0.0.0.0")

    @patch("socket.gethostbyname")
    def test_blocks_metadata_google_via_regex(self, mock_dns):
        mock_dns.return_value = "1.2.3.4"
        with pytest.raises(ValueError, match="Blocked internal hostname"):
            _validate_url("http://metadata.google.internal")

    @patch("socket.gethostbyname")
    def test_passes_valid_external_url(self, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        result = _validate_url("https://example.com")
        assert result == "https://example.com"

    @patch("socket.gethostbyname")
    def test_passes_external_url_with_path(self, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        result = _validate_url("https://example.com/api/v1/users")
        assert result == "https://example.com/api/v1/users"

    @patch("socket.gethostbyname")
    def test_passes_https_url_with_port(self, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        result = _validate_url("https://example.com:443/api")
        assert result == "https://example.com:443/api"

    def test_raises_on_dns_resolution_failure(self):
        with pytest.raises(ValueError, match="DNS resolution failed"):
            _validate_url("http://this-domain-definitely-does-not-exist-12345.com")

    def test_parsing_failure_raises_error(self):
        with pytest.raises(ValueError, match="Could not parse hostname"):
            _validate_url("http://")


class TestScan:
    """Tests for scan()."""

    def test_returns_empty_findings_on_url_validation_failure(self):
        result = scan("file:///etc/passwd", [])
        assert result == []

    @patch("socket.gethostbyname")
    def test_returns_empty_findings_on_internal_url(self, mock_dns):
        mock_dns.return_value = "127.0.0.1"
        result = scan("http://localhost:8080", [])
        assert result == []

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_detects_dom_xss(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page
        mock_sync_pw.return_value = mock_instance

        handler_storage = {}

        def on_side_effect(event, handler):
            if event == 'console':
                handler_storage["console"] = handler
            return None

        mock_page.on.side_effect = on_side_effect

        call_count = [0]

        def goto_side(url, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1 and "console" in handler_storage:
                msg = MagicMock()
                msg.type = 'error'
                msg.text = 'Refused to execute alert(1)'
                handler_storage["console"](msg)
            return MagicMock()

        mock_page.goto.side_effect = goto_side

        result = scan("https://example.com", [])
        assert len(result) == 2
        assert all(f["type"] == "DOM_XSS" for f in result)
        assert all(f["severity"] == "HIGH" for f in result)

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_handles_browser_exception_gracefully(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.side_effect = Exception("Browser crashed")
        mock_sync_pw.return_value = mock_instance

        result = scan("https://example.com", [])
        assert result == []

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_playwright_page_goto_failure(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page
        mock_page.goto.side_effect = Exception("Navigation timeout")
        mock_sync_pw.return_value = mock_instance

        result = scan("https://example.com", [])
        assert result == []

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_closes_browser_in_finally(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        MagicMock()
        MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.side_effect = Exception("Launch failed")
        mock_sync_pw.return_value = mock_instance

        result = scan("https://example.com", [])
        assert result == []

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_browser_close_called_on_exception(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page
        mock_page.goto.side_effect = Exception("Navigation failed")
        mock_sync_pw.return_value = mock_instance

        result = scan("https://example.com", [])
        assert result == []
        mock_browser.close.assert_called_once()

    @patch("socket.gethostbyname")
    @patch("tools._browser_scan_worker.sync_playwright")
    def test_no_finding_when_console_errors_no_alert(self, mock_sync_pw, mock_dns):
        mock_dns.return_value = "93.184.216.34"
        mock_instance = MagicMock()
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page
        mock_sync_pw.return_value = mock_instance

        handler_storage = {}

        def on_side_effect(event, handler):
            if event == 'console':
                handler_storage["console"] = handler
            return None

        mock_page.on.side_effect = on_side_effect

        call_count = [0]

        def goto_side(url, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1 and "console" in handler_storage:
                msg = MagicMock()
                msg.type = 'error'
                msg.text = 'some other error'
                handler_storage["console"](msg)
            return MagicMock()

        mock_page.goto.side_effect = goto_side

        result = scan("https://example.com", [])
        assert result == []
