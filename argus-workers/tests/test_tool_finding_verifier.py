"""
Tests for finding_verifier module.
"""
import urllib.parse
from unittest.mock import MagicMock, patch

import httpx
import pytest

from tools.finding_verifier import (
    _validate_verification_url,
    verify_finding,
    verify_open_redirect,
    verify_sqli,
    verify_xss,
)

pytestmark = pytest.mark.asyncio


class _Awaitable:
    """Wrap a return value so ``await mock_obj()`` returns it."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        yield
        return self.value


@pytest.fixture(autouse=True)
def mock_feature_flags():
    with patch("tools.finding_verifier.is_enabled", return_value=True):
        yield


@pytest.fixture
def mock_httpx_client():
    """Mock httpx.AsyncClient for all verifier tests."""
    client_instance = MagicMock()

    class _MockContextManager:
        async def __aenter__(self):
            return client_instance

        async def __aexit__(self, *args):
            return None

    with patch("tools.finding_verifier.httpx.AsyncClient", return_value=_MockContextManager()):
        yield client_instance


# ---------------------------------------------------------------------------
# _validate_verification_url
# ---------------------------------------------------------------------------

class TestValidateVerificationUrl:
    """Tests for _validate_verification_url."""

    def test_blocks_internal_ips(self):
        for ip in ("http://10.0.0.1", "http://192.168.1.1", "http://127.0.0.1", "http://169.254.1.1"):
            with pytest.raises(ValueError, match="Blocked internal IP"):
                _validate_verification_url(ip)

    def test_blocks_cloud_metadata_endpoints(self):
        with pytest.raises(ValueError, match="Blocked internal IP"):
            _validate_verification_url("http://169.254.169.254")

    def test_blocks_non_http_protocols(self):
        with pytest.raises(ValueError, match="Blocked protocol"):
            _validate_verification_url("gopher://internal:8080")
        with pytest.raises(ValueError, match="Blocked protocol"):
            _validate_verification_url("ftp://localhost")

    def test_rejects_missing_hostname(self):
        with pytest.raises(ValueError, match="Invalid or missing hostname"):
            _validate_verification_url("file:///etc/passwd")

    def test_allows_valid_external_urls(self):
        url = "https://example.com/api"
        assert _validate_verification_url(url) == url

    def test_blocks_known_metadata_hostnames(self):
        for host in ("metadata", "instance-data", "metadata.google.internal"):
            with pytest.raises(ValueError, match="Blocked metadata"):
                _validate_verification_url(f"http://{host}")


# ---------------------------------------------------------------------------
# verify_sqli
# ---------------------------------------------------------------------------

class TestVerifySqli:
    """Tests for verify_sqli."""

    async def test_returns_early_when_feature_flag_disabled(self):
        with patch("tools.finding_verifier.is_enabled", return_value=False):
            result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is False
        assert "disabled" in result["reason"]

    async def test_returns_blocked_for_internal_endpoints(self):
        result = await verify_sqli("http://127.0.0.1:8080", "' OR 1=1--")

        assert result["verified"] is False
        assert "Blocked" in result["reason"]

    async def test_differential_high_conf(self, mock_httpx_client):
        """Markers in original only -> high confidence."""
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="SQL syntax error occurred near SELECT")),
            _Awaitable(MagicMock(text="normal page response")),
        ]

        result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is True
        assert result["confidence"] == "high"

    async def test_differential_medium_conf(self, mock_httpx_client):
        """Markers in both -> medium confidence."""
        text = "sql error occurred"
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text=text)),
            _Awaitable(MagicMock(text=text)),
        ]

        result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is False
        assert result["confidence"] == "medium"

    async def test_differential_blind_low_conf(self, mock_httpx_client):
        """No markers in either -> low confidence (blind)."""
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="page loaded successfully")),
            _Awaitable(MagicMock(text="page loaded successfully")),
        ]

        result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is True
        assert result["confidence"] == "low"
        assert "blind" in result["reason"].lower()

    async def test_benign_triggers_markers_likely_fp(self, mock_httpx_client):
        """Benign triggers markers but original doesn't -> likely false positive."""
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="clean page with no errors")),
            _Awaitable(MagicMock(text="sql syntax error in query")),
        ]

        result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is False
        assert "Benign triggered markers" in result["reason"]

    async def test_httpx_exception_caught_gracefully(self, mock_httpx_client):
        """httpx exception -> caught gracefully."""
        exc = httpx.RequestError("connection failed")
        mock_httpx_client.get.side_effect = exc
        mock_httpx_client.post.side_effect = exc

        result = await verify_sqli("https://example.com", "' OR 1=1--")

        assert result["verified"] is False
        assert "error" in result["reason"].lower()


# ---------------------------------------------------------------------------
# verify_xss
# ---------------------------------------------------------------------------

class TestVerifyXss:
    """Tests for verify_xss."""

    async def test_returns_early_when_feature_flag_disabled(self):
        with patch("tools.finding_verifier.is_enabled", return_value=False):
            result = await verify_xss("https://example.com", "<script>alert(1)</script>")

        assert result["verified"] is False
        assert "disabled" in result["reason"]

    async def test_blocks_internal_endpoints(self):
        result = await verify_xss("http://127.0.0.1", "<script>alert(1)</script>")

        assert result["verified"] is False
        assert "Blocked" in result["reason"]

    async def test_payload_reflected_high_conf(self, mock_httpx_client):
        """Payload directly reflected in response -> high confidence."""
        payload = "<script>alert(1)</script>"
        mock_httpx_client.get.return_value = _Awaitable(MagicMock(text=payload))

        result = await verify_xss("https://example.com", payload)

        assert result["verified"] is True
        assert result["confidence"] == "high"

    async def test_url_encoded_reflection_medium_conf(self, mock_httpx_client):
        """URL-encoded reflection -> medium confidence."""
        payload = "<script>alert(1)</script>"
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(text=urllib.parse.quote(payload))
        )

        result = await verify_xss("https://example.com", payload)

        assert result["verified"] is True
        assert result["confidence"] == "medium"

    async def test_no_reflection_not_verified(self, mock_httpx_client):
        """No reflection at all -> not verified."""
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(text="clean page with no payload in it")
        )

        result = await verify_xss("https://example.com", "<script>alert(1)</script>")

        assert result["verified"] is False
        assert "No payload reflection" in result["reason"]

    async def test_iterates_through_multiple_payloads(self, mock_httpx_client):
        """First payload request fails, second succeeds — proves iteration."""
        mock_httpx_client.get.side_effect = [
            httpx.RequestError("timeout"),
            _Awaitable(MagicMock(text="<script>alert(1)</script> reflected")),
        ]

        result = await verify_xss("https://example.com", "<script>alert(1)</script>")

        assert result["verified"] is True

    async def test_httpx_exception_caught_gracefully(self, mock_httpx_client):
        """httpx exception on all payloads -> caught by inner continue, no reflection."""
        mock_httpx_client.get.side_effect = httpx.RequestError("connection failed")

        result = await verify_xss("https://example.com", "<script>alert(1)</script>")

        assert result["verified"] is False
        assert result["reason"] == "No payload reflection detected in response"


# ---------------------------------------------------------------------------
# verify_open_redirect
# ---------------------------------------------------------------------------

class TestVerifyOpenRedirect:
    """Tests for verify_open_redirect."""

    async def test_returns_early_when_disabled(self):
        with patch("tools.finding_verifier.is_enabled", return_value=False):
            result = await verify_open_redirect("https://example.com/redirect")

        assert result["verified"] is False
        assert "disabled" in result["reason"]

    async def test_blocks_internal_endpoints(self):
        result = await verify_open_redirect("http://127.0.0.1:8080/redirect")

        assert result["verified"] is False
        assert "Blocked" in result["reason"]

    async def test_external_redirect_high_conf(self, mock_httpx_client):
        """Redirect to external domain -> high confidence."""
        history_entry = MagicMock()
        history_entry.url = "https://example.com/old"
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(history=[history_entry], url="https://external.com/target")
        )

        result = await verify_open_redirect("https://example.com/redirect")

        assert result["verified"] is True
        assert result["confidence"] == "high"
        assert "Redirects" in result["reason"]

    async def test_same_domain_redirect_not_verified(self, mock_httpx_client):
        """Same-domain redirect -> not verified."""
        history_entry = MagicMock()
        history_entry.url = "https://example.com/a"
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(history=[history_entry], url="https://example.com/b")
        )

        result = await verify_open_redirect("https://example.com/a")

        assert result["verified"] is False
        assert "same domain" in result["reason"].lower()

    async def test_no_redirect_not_verified(self, mock_httpx_client):
        """No redirect at all -> not verified."""
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(history=[], url="https://example.com/page", status_code=200)
        )

        result = await verify_open_redirect("https://example.com/page")

        assert result["verified"] is False
        assert "No redirect" in result["reason"]

    async def test_httpx_http_error_caught_gracefully(self, mock_httpx_client):
        """httpx.HTTPError -> caught gracefully."""
        mock_httpx_client.get.side_effect = httpx.HTTPError("500 Server Error")

        result = await verify_open_redirect("https://example.com/redirect")

        assert result["verified"] is False
        assert "error" in result["reason"].lower()


# ---------------------------------------------------------------------------
# verify_finding
# ---------------------------------------------------------------------------

class TestVerifyFinding:
    """Tests for verify_finding dispatch."""

    async def test_dispatches_to_sqli_verifier(self, mock_httpx_client):
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="SQL error")),
            _Awaitable(MagicMock(text="normal")),
        ]

        finding = {"type": "sql-injection", "endpoint": "https://example.com", "evidence": {"payload": "' OR 1=1--"}}
        result = await verify_finding(finding)

        assert result["verification"]["confidence"] == "high"

    async def test_dispatches_to_xss_verifier(self, mock_httpx_client):
        mock_httpx_client.get.return_value = _Awaitable(MagicMock(text="<script>alert(1)</script>"))

        finding = {"type": "xss", "endpoint": "https://example.com", "evidence": {"payload": "<script>alert(1)</script>"}}
        result = await verify_finding(finding)

        assert result["verification"]["verified"] is True

    async def test_dispatches_to_open_redirect_verifier(self, mock_httpx_client):
        history_entry = MagicMock()
        history_entry.url = "https://example.com/a"
        mock_httpx_client.get.return_value = _Awaitable(
            MagicMock(history=[history_entry], url="https://external.com/b")
        )

        finding = {"type": "open-redirect", "endpoint": "https://example.com/a"}
        result = await verify_finding(finding)

        assert result["verification"]["verified"] is True

    async def test_returns_no_verifier_for_unknown_types(self):
        finding = {"type": "unknown-type", "endpoint": "https://example.com"}
        result = await verify_finding(finding)

        assert result["verification"]["verified"] is None
        assert "No verifier" in result["verification"]["reason"]

    async def test_passes_payload_and_endpoint_correctly(self, mock_httpx_client):
        """Verify endpoint and payload from finding dict are forwarded."""
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="SQL syntax error")),
            _Awaitable(MagicMock(text="clean page")),
        ]

        finding = {
            "type": "sql-injection",
            "endpoint": "https://target.com/search",
            "evidence": {"payload": "' OR '1'='1"},
        }
        result = await verify_finding(finding)

        assert result["verification"]["verified"] is True
        assert result["verification"]["confidence"] == "high"

    async def test_uses_url_when_endpoint_missing(self, mock_httpx_client):
        """Fallback to finding.url when endpoint is absent."""
        mock_httpx_client.get.return_value = _Awaitable(MagicMock(text="<script>alert(1)</script>"))

        finding = {"type": "xss", "url": "https://example.com", "evidence": {"payload": "<script>alert(1)</script>"}}
        result = await verify_finding(finding)

        assert result["verification"]["verified"] is True

    async def test_uses_top_level_payload_when_evidence_missing(self, mock_httpx_client):
        """Fallback to finding.payload when evidence.payload is absent."""
        mock_httpx_client.get.side_effect = [
            _Awaitable(MagicMock(text="SQL error")),
            _Awaitable(MagicMock(text="normal")),
        ]

        finding = {"type": "sqli", "endpoint": "https://example.com", "payload": "' OR 1=1--"}
        result = await verify_finding(finding)

        assert result["verification"]["confidence"] == "high"
