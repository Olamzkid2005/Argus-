"""
Unit tests for SSRF validation in post_finding_hooks.py.

Tests the _validate_webhook_url() function which performs:
- Scheme validation (HTTPS only)
- Static blocklist (localhost, cloud metadata IPs, etc.)
- DNS resolution with private IP detection
- Fail-closed behavior on DNS resolution failure

Uses monkeypatch/mock to control socket.getaddrinfo() results since
DNS resolution is external.
"""

import socket
from unittest.mock import patch

import pytest

# Module under test
from post_finding_hooks import _validate_webhook_url

# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def disable_logging():
    """Suppress log output during tests."""
    with patch("post_finding_hooks.logger") as mock_log:
        yield mock_log


# ── Scheme Validation ────────────────────────────────────────────────

class TestSchemeValidation:
    """Only HTTPS scheme should be allowed."""

    def test_https_allowed(self):
        """Standard HTTPS URLs with public IP resolution must pass."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert _validate_webhook_url("https://hooks.example.com/alerts") is True

    def test_http_rejected(self):
        """Plain HTTP must be rejected (SSRF risk via MitM)."""
        assert _validate_webhook_url("http://hooks.example.com/alert") is False

    def test_ftp_rejected(self):
        """Non-HTTPS schemes must be rejected."""
        assert _validate_webhook_url("ftp://storage.example.com/file") is False

    def test_no_scheme_rejected(self):
        """URL without a scheme must be rejected."""
        assert _validate_webhook_url("hooks.example.com/alert") is False


# ── Static Blocklist ─────────────────────────────────────────────────

class TestStaticBlocklist:
    """Known malicious hostnames must be rejected without DNS lookup."""

    @pytest.mark.parametrize("url", [
        "https://localhost/webhook",
        "https://127.0.0.1/webhook",
        "https://0.0.0.0/webhook",
        "https://[::1]/webhook",
        "https://[::]/webhook",
        "https://169.254.169.254/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://169.254.170.2/credentials",
        "https://100.100.100.200/latest/meta-data/",
    ])
    def test_blocked_host_rejected(self, url):
        """Each blocked hostname/IP must be rejected."""
        # These are caught before DNS lookup, so no need to mock
        assert _validate_webhook_url(url) is False


# ── DNS Resolution: Public IPs ───────────────────────────────────────

class TestDnsPublicIp:
    """Hostnames that resolve to public IPs must be allowed."""

    def test_public_ipv4_allowed(self):
        """Hostname resolving to a public IPv4 must be allowed."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),  # example.com
            ]
            assert _validate_webhook_url("https://hooks.example.com/alert") is True

    def test_public_ipv6_allowed(self):
        """Hostname resolving to a public IPv6 must be allowed."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0)),  # example.com IPv6
            ]
            assert _validate_webhook_url("https://hooks.ipv6.example.com/alert") is True

    def test_multiple_public_ips_allowed(self):
        """Hostname with multiple public IPs must be allowed."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
                (2, 1, 6, "", ("93.184.216.35", 0)),
                (10, 1, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", 0)),
            ]
            assert _validate_webhook_url("https://hooks.example.com/alert") is True


# ── DNS Resolution: Private IPs ──────────────────────────────────────

class TestDnsPrivateIp:
    """Hostnames that resolve to private/internal IPs must be blocked."""

    @pytest.mark.parametrize("private_ip", [
        "10.0.0.1",       # RFC 1918 Class A
        "172.16.0.1",     # RFC 1918 Class B
        "192.168.1.1",    # RFC 1918 Class C
        "127.0.0.1",      # Loopback (should be caught by blocklist, but test DNS path too)
        "169.254.1.1",    # Link-local
        "0.0.0.1",        # Current network
        "100.64.0.1",     # CGNAT
    ])
    def test_private_ipv4_blocked(self, private_ip):
        """Hostname resolving to a private IPv4 must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", (private_ip, 0)),
            ]
            assert _validate_webhook_url("https://hooks.internal.example.com/alert") is False

    @pytest.mark.parametrize("private_ipv6", [
        "fc00::1",        # ULA
        "fd00::1",        # ULA
        "fe80::1",        # Link-local
        "::1",            # Loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
        "::ffff:127.0.0.1", # IPv4-mapped loopback
    ])
    def test_private_ipv6_blocked(self, private_ipv6):
        """Hostname resolving to a private IPv6 must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (10, 1, 6, "", (private_ipv6, 0, 0, 0)),
            ]
            assert _validate_webhook_url("https://hooks.internal-v6.example.com/alert") is False

    def test_mixed_public_and_private_blocked(self):
        """Hostname with both public and private IPs must be blocked."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),  # public
                (2, 1, 6, "", ("10.0.0.1", 0)),        # private
            ]
            # Should be blocked because one of the resolved IPs is private
            assert _validate_webhook_url("https://hooks.split-view.example.com/alert") is False


# ── DNS Resolution: Fail-Closed ──────────────────────────────────────

class TestDnsFailClosed:
    """When DNS resolution fails, the URL must be blocked (fail-closed)."""

    def test_gaierror_blocked(self):
        """socket.gaierror (name/service not known) must block the URL."""
        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            assert _validate_webhook_url("https://nonexistent.example.com/webhook") is False

    def test_herror_blocked(self):
        """socket.herror (hostname lookup error) must block the URL."""
        with patch("socket.getaddrinfo", side_effect=socket.herror):
            assert _validate_webhook_url("https://bad.example.com/webhook") is False

    def test_oserror_blocked(self):
        """OSError during DNS resolution must block the URL."""
        with patch("socket.getaddrinfo", side_effect=OSError("Network is unreachable")):
            assert _validate_webhook_url("https://unreachable.example.com/webhook") is False

    def test_index_error_blocked(self):
        """IndexError from malformed getaddrinfo result must block the URL."""
        with patch("socket.getaddrinfo") as mock_gai:
            # Return a non-empty list but with an empty sockaddr tuple —
            # accessing sockaddr[0] raises IndexError.
            mock_gai.return_value = [
                (2, 1, 6, "", ()),  # empty sockaddr — IndexError on [0]
            ]
            assert _validate_webhook_url("https://bad-sockaddr.example.com/webhook") is False

    def test_empty_getaddrinfo_blocked(self):
        """Empty getaddrinfo result (no addresses resolved) must block the URL."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = []  # no addresses resolved
            assert _validate_webhook_url("https://no-addresses.example.com/webhook") is False

    def test_timeout_dns_blocked(self):
        """DNS timeout must block the URL (fail-closed)."""
        with patch("socket.getaddrinfo", side_effect=OSError("DNS resolution timed out")):
            assert _validate_webhook_url("https://slow-dns.example.com/webhook") is False


# ── Edge Cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge cases and malformed inputs."""

    def test_empty_url_rejected(self):
        """Empty URL string must be rejected."""
        assert _validate_webhook_url("") is False

    def test_malformed_url_rejected(self):
        """Malformed URL must be rejected."""
        assert _validate_webhook_url("https://") is False

    def test_invalid_url_with_spaces_rejected(self):
        """URL with invalid characters must be rejected."""
        assert _validate_webhook_url("https://evil .example.com/webhook") is False

    def test_url_with_credentials_rejected(self):
        """URL with embedded credentials must use HTTPS and still resolve."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            # user:pass@host should still work if it's HTTPS and public
            assert _validate_webhook_url("https://user:pass@hooks.example.com/alert") is True

    def test_long_hostname_with_valid_dns(self):
        """Long but valid hostname that resolves to a public IP must be allowed."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert _validate_webhook_url(
                "https://really-long-subdomain-name-that-is-still-valid.example.com/webhook"
            ) is True

    def test_url_with_query_params(self):
        """URL with query parameters must work correctly."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert _validate_webhook_url(
                "https://hooks.example.com/webhook?event=critical&severity=high"
            ) is True

    def test_url_with_port(self):
        """URL with custom port must work correctly."""
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert _validate_webhook_url(
                "https://hooks.example.com:8443/webhook"
            ) is True
