"""Tests for post_finding_hooks.py

Covers:
  - fire_finding_webhooks severity filtering
  - fire_finding_webhooks without engagement_id
  - _get_matching_webhooks
  - _dispatch success/failure
  - _mark_triggered
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

from post_finding_hooks import (
    _dispatch,
    _get_matching_webhooks,
    _mark_triggered,
    _validate_webhook_url,
    fire_finding_webhooks,
)


class TestFireFindingWebhooks:
    """Tests for fire_finding_webhooks."""

    def test_skips_low_severity(self):
        result = fire_finding_webhooks(
            {
                "id": "finding-1",
                "engagement_id": "eng-001",
                "severity": "LOW",
                "type": "XSS",
            }
        )
        assert result is None  # No webhooks fired for LOW severity

    def test_fires_for_critical(self):
        with patch(
            "post_finding_hooks._get_matching_webhooks", return_value=[]
        ) as mock_get:
            fire_finding_webhooks(
                {
                    "id": "finding-1",
                    "engagement_id": "eng-001",
                    "severity": "CRITICAL",
                    "type": "SQL_INJECTION",
                    "endpoint": "/api",
                    "source_tool": "nuclei",
                    "confidence": 0.9,
                }
            )
            mock_get.assert_called_once_with("eng-001")

    def test_skips_without_engagement_id(self):
        fire_finding_webhooks(
            {
                "id": "finding-1",
                "severity": "CRITICAL",
            }
        )  # Should return without error

    def test_fires_webhooks(self):
        with (
            patch(
                "post_finding_hooks._get_matching_webhooks",
                return_value=[
                    {"id": "wh-1", "webhook_url": "https://hooks.example.com"}
                ],
            ),
            patch("post_finding_hooks._dispatch") as mock_dispatch,
        ):
            fire_finding_webhooks(
                {
                    "id": "finding-1",
                    "engagement_id": "eng-001",
                    "severity": "HIGH",
                    "type": "XSS",
                    "endpoint": "/search",
                }
            )
            mock_dispatch.assert_called_once()


class TestGetMatchingWebhooks:
    """Tests for _get_matching_webhooks."""

    def test_db_error_returns_empty(self):
        mock_db = MagicMock()
        mock_db.get_connection.side_effect = Exception("DB error")
        with patch("database.connection.get_db", return_value=mock_db):
            result = _get_matching_webhooks("eng-001")
            assert result == []


class TestValidateWebhookUrl:
    """Tests for _validate_webhook_url SSRF validation."""

    def test_blocks_disallowed_scheme(self):
        assert _validate_webhook_url("http://example.com/hook") is False
        assert _validate_webhook_url("ftp://example.com/hook") is False
        assert _validate_webhook_url("file:///etc/passwd") is False

    def test_blocks_known_metadata_hosts(self):
        assert _validate_webhook_url("https://169.254.169.254/latest/meta-data/") is False
        assert _validate_webhook_url("https://metadata.google.internal/") is False
        assert _validate_webhook_url("https://localhost:9000/hook") is False
        assert _validate_webhook_url("https://127.0.0.1/hook") is False
        assert _validate_webhook_url("https://0.0.0.0/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_allows_public_ip_hostname(self, mock_getaddrinfo):
        """Hostname resolving to a public IP should pass."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("93.184.216.34", 0))
        ]
        assert _validate_webhook_url("https://example.com/hook") is True

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_private_ip_resolution(self, mock_getaddrinfo):
        """Hostname resolving to 10.x.x.x should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("10.0.0.1", 0))
        ]
        assert _validate_webhook_url("https://internal-service.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_loopback_ip_resolution(self, mock_getaddrinfo):
        """Hostname resolving to 127.x.x.x should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("127.0.0.1", 0))
        ]
        assert _validate_webhook_url("https://myservice.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_cloud_metadata_resolution(self, mock_getaddrinfo):
        """Hostname resolving to 169.254.169.254 should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("169.254.169.254", 0))
        ]
        assert _validate_webhook_url("https://cloud-metadata.evil.com/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_ipv6_private_ula(self, mock_getaddrinfo):
        """Hostname resolving to IPv6 ULA (fc00::/7) should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("fc00::1", 0))
        ]
        assert _validate_webhook_url("https://ipv6-ula.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_ipv6_link_local(self, mock_getaddrinfo):
        """Hostname resolving to IPv6 link-local (fe80::/10) should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("fe80::1", 0))
        ]
        assert _validate_webhook_url("https://ipv6-linklocal.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_ipv4_mapped_ipv6_private(self, mock_getaddrinfo):
        """IPv4-mapped IPv6 with private embedded IPv4 should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("::ffff:127.0.0.1", 0))
        ]
        assert _validate_webhook_url("https://ipv6-mapped.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_blocks_ipv6_loopback(self, mock_getaddrinfo):
        """Hostname resolving to ::1 should be blocked."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("::1", 0))
        ]
        assert _validate_webhook_url("https://ipv6-loopback.local/hook") is False

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_allows_ipv6_public(self, mock_getaddrinfo):
        """Hostname resolving to public IPv6 should pass."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("2001:470:1f15:1abc::1", 0))
        ]
        assert _validate_webhook_url("https://ipv6-public.local/hook") is True

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_allows_multiple_addrinfo_first_public(self, mock_getaddrinfo):
        """When hostname resolves to multiple IPs, first public one passes."""
        mock_getaddrinfo.return_value = [
            (0, 0, 0, "", ("93.184.216.34", 0)),
        ]
        assert _validate_webhook_url("https://multi-ip.example.com/hook") is True

    @patch("post_finding_hooks.socket.getaddrinfo")
    def test_dns_failure_does_not_block(self, mock_getaddrinfo):
        """If DNS resolution fails, allow the URL (static blocklist already checked)."""
        mock_getaddrinfo.side_effect = socket.gaierror("Name or service not known")
        assert _validate_webhook_url("https://some-random-hostname.xyz/hook") is True


class TestDispatch:
    """Tests for _dispatch."""

    def test_successful_dispatch(self):
        class FakeResponse:
            status_code = 200

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def post(self, url, json=None):
                return FakeResponse()

        with (
            patch("post_finding_hooks.httpx.Client", return_value=FakeClient()),
            patch("post_finding_hooks._mark_triggered") as mock_mark,
        ):
            _dispatch("https://hooks.example.com", {"event": "test"}, "wh-1")
            mock_mark.assert_called_once_with("wh-1", success=True)

    def test_failed_dispatch(self):
        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def post(self, url, json=None):
                raise Exception("Connection error")

        with (
            patch("post_finding_hooks.httpx.Client", return_value=FakeClient()),
            patch("post_finding_hooks._mark_triggered") as mock_mark,
        ):
            _dispatch("https://hooks.example.com", {"event": "test"}, "wh-1")
            mock_mark.assert_called_once_with("wh-1", success=False)


class TestMarkTriggered:
    """Tests for _mark_triggered."""

    def test_successful_update(self):
        mock_db = MagicMock()
        with patch("database.connection.get_db", return_value=mock_db):
            _mark_triggered("wh-1", success=True)
            # Should not raise

    def test_db_error(self):
        mock_db = MagicMock()
        mock_db.get_connection.side_effect = Exception("DB error")
        with patch("database.connection.get_db", return_value=mock_db):
            _mark_triggered("wh-1", success=True)
            # Should not raise
