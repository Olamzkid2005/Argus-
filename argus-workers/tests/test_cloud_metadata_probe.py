"""
Tests for tools.cloud_metadata_probe — Category: function

Tests the CloudMetadataProbe tool's ability to:
- Probe all major cloud provider metadata endpoints
- Extract IAM credentials and tokens
- Handle unreachable metadata endpoints gracefully
- Generate correct findings with appropriate severity
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tool_core.base import ToolContext
from tools.cloud_metadata_probe import CLOUD_METADATA_ENDPOINTS, CloudMetadataProbe


class MockResponse:
    """Minimal mock for httpx.Response."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self._text = text
        self.headers = headers or {}

    @property
    def text(self) -> str:
        return self._text


@pytest.fixture
def probe() -> CloudMetadataProbe:
    """Create a CloudMetadataProbe instance for testing."""
    return CloudMetadataProbe()


@pytest.fixture
def ctx() -> ToolContext:
    """Create a ToolContext for testing."""
    return ToolContext(
        target="https://example.com",
        engagement_id="test-eng-001",
        tech_stack=["python", "aws"],
    )


class TestCloudMetadataProbe:
    """Tests for the CloudMetadataProbe tool."""

    def test_tool_name(self, probe: CloudMetadataProbe):
        """Tool name is set correctly."""
        assert probe.tool_name == "cloud_metadata_probe"

    def test_execute_no_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """When no metadata endpoints are reachable, returns INFO finding and SUCCESS_EMPTY status."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            # All endpoints return connection refused
            mock_instance.get.side_effect = ConnectionRefusedError(
                "Connection refused"
            )

            result = probe.execute(ctx)

        assert result.status.is_ok
        assert len(result.findings) == 1
        assert result.findings[0]["type"] == "CLOUD_METADATA_UNREACHABLE"
        assert result.findings[0]["severity"] == "INFO"
        assert result.findings[0]["confidence"] == 0.95

    def test_execute_all_http_errors(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """All endpoint errors (timeout, OSError, etc.) are handled gracefully."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            # Mix of different error types
            side_effects = []
            for _ in range(
                sum(len(eps) for eps in CLOUD_METADATA_ENDPOINTS.values())
            ):
                import httpx

                side_effects.append(
                    httpx.ConnectError("Connection refused")
                )
            mock_instance.get.side_effect = side_effects

            result = probe.execute(ctx)

        assert result.status.is_ok
        assert len(result.findings) == 1
        assert result.findings[0]["type"] == "CLOUD_METADATA_UNREACHABLE"

    def test_aws_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """AWS metadata endpoint reachable generates HIGH finding."""
        aws_endpoints = CLOUD_METADATA_ENDPOINTS["aws"]

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                for ep in aws_endpoints:
                    if url == ep["url"]:
                        return MockResponse(
                            status_code=200,
                            text="ami-id: ami-12345\ninstance-type: t3.medium",
                            headers={"Content-Type": "text/plain"},
                        )
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        assert len(result.findings) >= 1

        # Should have HIGH finding for AWS metadata accessible
        aws_findings = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(aws_findings) >= 1
        assert aws_findings[0]["severity"] == "HIGH"
        assert aws_findings[0]["confidence"] == 0.85

    def test_aws_iam_role_credentials(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """AWS IAM role credential extraction generates CRITICAL finding."""
        CLOUD_METADATA_ENDPOINTS["aws"]

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            call_count = 0

            def get_side_effect(url, headers=None, **kwargs):
                nonlocal call_count
                # First call: root metadata (success)
                if call_count == 0:
                    call_count += 1
                    return MockResponse(
                        status_code=200,
                        text="ami-id: ami-12345",
                    )
                # Second call: IAM roles list (returns a role name)
                if call_count == 1:
                    call_count += 1
                    return MockResponse(
                        status_code=200,
                        text="MyTestRole",
                    )
                # Third call: IAM role credentials (returns credential JSON with AKIA key)
                if call_count == 2:
                    call_count += 1
                    return MockResponse(
                        status_code=200,
                        text=json.dumps({
                            "Code": "Success",
                            "LastUpdated": "2024-01-01T00:00:00Z",
                            "Type": "AWS-HMAC",
                            "AccessKeyId": "AKIA1234567890123456",
                            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
                            "Token": "IQoJb3JpZ2luX2VjEJD/...longsessiontoken...",
                            "Expiration": "2024-12-31T23:59:59Z",
                        }),
                    )
                call_count += 1
                return MockResponse(status_code=200, text="instance-data")

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        assert len(result.findings) >= 2

        # Should have CRITICAL finding for AWS IAM credentials
        cred_findings = [
            f
            for f in result.findings
            if f["type"] in ("CLOUD_CREDENTIAL_EXFILTRATION", "AWS_IAM_ROLE_CREDENTIALS")
        ]
        assert len(cred_findings) >= 1
        for f in cred_findings:
            assert f["severity"] == "CRITICAL"

        # Evidence should contain credential data
        for f in cred_findings:
            evidence = f.get("evidence", {})
            if "credentials_extracted" in evidence:
                assert len(evidence["credentials_extracted"]) > 0

    def test_aws_imdsv2_fallback_direct(
        self, probe: CloudMetadataProbe
    ):
        """_try_aws_imdsv2 correctly fetches token and retries with it."""
        endpoint = {
            "url": "http://169.254.169.254/latest/meta-data/",
            "description": "AWS IMDSv1 root metadata",
            "headers": {},
            "timeout": 3,
        }

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            # IMDSv2 token PUT succeeds
            mock_instance.put.return_value = MockResponse(
                status_code=200,
                text="AQAEAFb3JpZ2luX2VjEJD/...token...",
            )
            # IMDSv2 GET (with token in headers) succeeds
            mock_instance.get.return_value = MockResponse(
                status_code=200,
                text="ami-id: ami-12345",
            )

            result = probe._try_aws_imdsv2(endpoint)

        assert result["reachable"] is True
        assert result["imdsv2"] is True
        assert result["status_code"] == 200
        assert "ami-id" in result.get("data", "")
        # Verify PUT was called to get token
        mock_instance.put.assert_called_once_with(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
        )

    def test_aws_imdsv2_put_fails(
        self, probe: CloudMetadataProbe
    ):
        """_try_aws_imdsv2 returns unreachable when token PUT fails."""
        endpoint = {
            "url": "http://169.254.169.254/latest/meta-data/",
            "description": "AWS IMDSv1 root metadata",
            "headers": {},
            "timeout": 3,
        }

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            # IMDSv2 token PUT fails
            mock_instance.put.return_value = MockResponse(
                status_code=404, text="Not Found"
            )

            result = probe._try_aws_imdsv2(endpoint)

        assert result["reachable"] is False

    def test_aws_imdsv2_get_fails(
        self, probe: CloudMetadataProbe
    ):
        """_try_aws_imdsv2 returns unreachable when GET after token fails."""
        endpoint = {
            "url": "http://169.254.169.254/latest/meta-data/",
            "description": "AWS IMDSv1 root metadata",
            "headers": {},
            "timeout": 3,
        }

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            # IMDSv2 token PUT succeeds
            mock_instance.put.return_value = MockResponse(
                status_code=200,
                text="AQAEAFb3JpZ2luX2VjEJD/...token...",
            )
            # IMDSv2 GET (with token) fails
            mock_instance.get.return_value = MockResponse(
                status_code=403, text="Forbidden"
            )

            result = probe._try_aws_imdsv2(endpoint)

        assert result["reachable"] is False

    def test_gcp_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """GCP metadata endpoint reachable generates HIGH finding."""
        gcp_endpoints = CLOUD_METADATA_ENDPOINTS["gcp"]

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                for ep in gcp_endpoints:
                    if url == ep["url"]:
                        # Verify Metadata-Flavor header is set
                        assert headers and headers.get("Metadata-Flavor") == "Google"
                        return MockResponse(
                            status_code=200,
                            text="instance-id: 12345\nzone: us-central1-a",
                            headers=headers or {},
                        )
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        gcp_findings = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(gcp_findings) >= 1
        assert "gcp" in gcp_findings[0]["evidence"].get("provider", "").lower()

    def test_azure_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """Azure metadata endpoint reachable generates HIGH finding."""
        azure_endpoints = CLOUD_METADATA_ENDPOINTS["azure"]

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                for ep in azure_endpoints:
                    if url == ep["url"]:
                        # Verify Metadata header is set
                        assert headers and headers.get("Metadata") == "true"
                        return MockResponse(
                            status_code=200,
                            text=json.dumps({
                                "compute": {
                                    "azEnvironment": "AzurePublicCloud",
                                    "location": "eastus",
                                    "vmId": "vm-12345",
                                }
                            }),
                            headers=headers or {},
                        )
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        azure_findings = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(azure_findings) >= 1
        assert "azure" in azure_findings[0]["evidence"].get("provider", "").lower()

    def test_alibaba_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """Alibaba Cloud metadata endpoint reachable generates HIGH finding."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                if "100.100.100.200" in url:
                    return MockResponse(status_code=200, text="region: cn-hangzhou")
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        alibaba_findings = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(alibaba_findings) >= 1
        assert "alibaba" in alibaba_findings[0]["evidence"].get("provider", "").lower()

    def test_multiple_providers_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """Multiple reachable providers generate separate findings."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                # Return 200 only for AWS-specific and GCP-specific endpoints
                # AWS: 169.254.169.254 with /latest/ path (NOT Alibaba's 100.100.100.200)
                # GCP: metadata.google.internal
                # Azure also uses 169.254.169.254 but with /metadata/ path — return 404
                if "metadata.google.internal" in url:
                    return MockResponse(status_code=200, text="instance-data")
                if "169.254.169.254" in url and (
                    "/latest/meta-data/" in url or "/latest/user-data" in url
                ):
                    return MockResponse(status_code=200, text="instance-data")
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        accessible = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(accessible) == 2  # AWS and GCP

        providers = {f["evidence"].get("provider", "").lower() for f in accessible}
        assert "aws" in providers
        assert "gcp" in providers

    def test_digitalocean_metadata_reachable(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """DigitalOcean metadata endpoint reachable generates HIGH finding."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            def get_side_effect(url, headers=None, **kwargs):
                if "metadata/v1.json" in url:
                    return MockResponse(
                        status_code=200,
                        text=json.dumps({
                            "droplet_id": 12345,
                            "region": "nyc3",
                        }),
                    )
                return MockResponse(status_code=404)

            mock_instance.get.side_effect = get_side_effect

            result = probe.execute(ctx)

        assert result.status.is_ok
        do_findings = [f for f in result.findings if f["type"] == "CLOUD_METADATA_ACCESSIBLE"]
        assert len(do_findings) >= 1

    def test_execute_output_format(
        self, probe: CloudMetadataProbe, ctx: ToolContext
    ):
        """Execute result output is valid JSON with expected structure."""
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            # No endpoints reachable
            mock_instance.get.side_effect = ConnectionRefusedError("refused")

            result = probe.execute(ctx)

        stdout = result.stdout
        assert stdout is not None
        parsed = json.loads(stdout)
        assert "providers_reachable" in parsed
        assert "providers" in parsed
        assert "credentials_extracted" in parsed
        assert "total_findings" in parsed
        assert parsed["providers_reachable"] == 0
        assert parsed["total_findings"] == 1

    def test_extract_sensitive_with_aws_key(
        self, probe: CloudMetadataProbe
    ):
        """_extract_sensitive detects AWS access keys in raw text."""
        data = json.dumps({
            "Code": "Success",
            "AccessKeyId": "AKIA1234567890123456",
            "SecretAccessKey": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
        })
        items = probe._extract_sensitive(data)
        assert len(items) > 0
        types = {i["type"] for i in items}
        assert "AWS_ACCESS_KEY" in types

    def test_extract_sensitive_no_match(
        self, probe: CloudMetadataProbe
    ):
        """_extract_sensitive returns empty list for non-sensitive data."""
        data = json.dumps({"ami-id": "ami-12345", "instance-type": "t3.medium"})
        items = probe._extract_sensitive(data)
        assert len(items) == 0

    def test_probe_endpoint_connection_refused(
        self, probe: CloudMetadataProbe
    ):
        """_probe_endpoint handles connection refused."""
        ep = {"url": "http://169.254.169.254/latest/meta-data/", "headers": {}, "timeout": 3}

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_instance.get.side_effect = ConnectionRefusedError("refused")

            result = probe._probe_endpoint(ep)
            assert not result["reachable"]

    def test_probe_endpoint_connection_timeout(
        self, probe: CloudMetadataProbe
    ):
        """_probe_endpoint handles timeout."""
        import httpx

        ep = {"url": "http://169.254.169.254/latest/meta-data/", "headers": {}, "timeout": 3}

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.TimeoutException("timed out")

            result = probe._probe_endpoint(ep)
            assert not result["reachable"]

    def test_probe_endpoint_http_error(
        self, probe: CloudMetadataProbe
    ):
        """_probe_endpoint handles OS errors."""
        ep = {"url": "http://100.100.100.200/latest/meta-data/", "headers": {}, "timeout": 3}

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_instance.get.side_effect = OSError("No route to host")

            result = probe._probe_endpoint(ep)
            assert not result["reachable"]

    def test_probe_endpoint_success(
        self, probe: CloudMetadataProbe
    ):
        """_probe_endpoint returns reachable with data on HTTP 200."""
        ep = {"url": "http://169.254.169.254/latest/meta-data/", "headers": {}, "timeout": 3}

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse(
                status_code=200,
                text="ami-id: ami-12345",
                headers={"Content-Type": "text/plain"},
            )

            result = probe._probe_endpoint(ep)
            assert result["reachable"]
            assert result["status_code"] == 200
            assert "ami-id" in result.get("data", "")

    def test_probe_endpoint_unauthorized(
        self, probe: CloudMetadataProbe
    ):
        """_probe_endpoint handles 401 by trying IMDSv2 fallback."""
        ep = {
            "url": "http://169.254.169.254/latest/meta-data/",
            "description": "AWS IMDSv1 root metadata",
            "headers": {},
            "timeout": 3,
        }

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_instance

            # First get returns 401 (no IMDSv2), PUT also fails
            mock_instance.get.side_effect = [
                MockResponse(status_code=401, text="Unauthorized"),
            ]
            mock_instance.put.return_value = MockResponse(
                status_code=404, text="Not Found"
            )

            result = probe._probe_endpoint(ep)
            # Attempted IMDSv2 but failed — reachable but not a success
            if result.get("reachable"):
                assert "IMDSv2" in result.get("data", "")
            else:
                assert not result["reachable"]


class TestCloudMetadataEndpointConfig:
    """Tests for the CLOUD_METADATA_ENDPOINTS configuration."""

    def test_all_providers_have_endpoints(self):
        """All expected cloud providers are defined."""
        providers = {"aws", "gcp", "azure", "alibaba", "digitalocean"}
        assert set(CLOUD_METADATA_ENDPOINTS.keys()) == providers

    def test_all_endpoints_have_required_fields(self):
        """Every endpoint has url, description, headers, and timeout."""
        for provider, endpoints in CLOUD_METADATA_ENDPOINTS.items():
            for ep in endpoints:
                assert "url" in ep, f"{provider} endpoint missing url"
                assert "description" in ep, f"{provider} endpoint missing description"
                assert "headers" in ep, f"{provider} endpoint missing headers"
                assert "timeout" in ep, f"{provider} endpoint missing timeout"
                assert isinstance(ep["timeout"], (int, float)), f"{provider} timeout not numeric"

    def test_known_metadata_endpoints(self):
        """Well-known cloud metadata endpoints are present."""
        all_urls = {
            url
            for endpoints in CLOUD_METADATA_ENDPOINTS.values()
            for url in [ep["url"] for ep in endpoints]
        }

        assert "http://169.254.169.254/latest/meta-data/" in all_urls  # AWS
        assert "http://metadata.google.internal/computeMetadata/v1/" in all_urls  # GCP
        assert "http://169.254.169.254/metadata/instance?api-version=2021-02-01" in all_urls  # Azure
        assert "http://100.100.100.200/latest/meta-data/" in all_urls  # Alibaba
        assert "http://169.254.169.254/metadata/v1.json" in all_urls  # DigitalOcean

    def test_aws_endpoints_count(self):
        """AWS has the expected number of endpoints (root, IAM, user-data, identity)."""
        assert len(CLOUD_METADATA_ENDPOINTS["aws"]) == 4

    def test_gcp_endpoints_count(self):
        """GCP has expected endpoints (root, SA list, default token, attributes)."""
        assert len(CLOUD_METADATA_ENDPOINTS["gcp"]) == 4

    def test_azure_endpoints_count(self):
        """Azure has expected endpoints (instance, identity token)."""
        assert len(CLOUD_METADATA_ENDPOINTS["azure"]) == 2
