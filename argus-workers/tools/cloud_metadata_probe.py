"""
Cloud Metadata Probe — probes cloud provider metadata endpoints after SSRF detection.

After an SSRF finding is confirmed, this tool probes cloud instance metadata
services (IMDS) on AWS, GCP, and Azure to extract:

1. IAM role credentials (temporary keys, tokens)
2. Instance identity documents
3. User-data / startup scripts
4. Network configuration and metadata
5. Custom metadata (tags, labels)

Each successfully probed metadata endpoint produces a HIGH-severity finding
with extracted credential material (when available), enabling the attack graph
chain: SSRF → Cloud Metadata → AWS/GCP/Azure Compromise.

Designed as an AbstractTool subclass so it can be dispatched via
run_agent_tool.py → MCP server → TypeScript executor.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

import httpx

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

# ── Cloud metadata endpoints ───────────────────────────────────────────────
# These are well-known metadata service endpoints for each major cloud provider.
# They are ONLY reachable from inside a cloud VM instance. Probing them from
# outside will silently fail (connection timeout / no route to host).

CLOUD_METADATA_ENDPOINTS: dict[str, list[dict]] = {
    "aws": [
        {
            "url": "http://169.254.169.254/latest/meta-data/",
            "description": "AWS IMDSv1 root metadata",
            "headers": {},
            "timeout": 3,
        },
        {
            "url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "description": "AWS IMDSv1 IAM roles list",
            "headers": {},
            "timeout": 3,
        },
        {
            "url": "http://169.254.169.254/latest/user-data",
            "description": "AWS IMDSv1 user-data (startup scripts)",
            "headers": {},
            "timeout": 3,
        },
        {
            "url": "http://169.254.169.254/latest/dynamic/instance-identity/document",
            "description": "AWS IMDSv1 instance identity document",
            "headers": {},
            "timeout": 3,
        },
    ],
    "gcp": [
        {
            "url": "http://metadata.google.internal/computeMetadata/v1/",
            "description": "GCP root metadata",
            "headers": {"Metadata-Flavor": "Google"},
            "timeout": 3,
        },
        {
            "url": "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/",
            "description": "GCP service accounts list",
            "headers": {"Metadata-Flavor": "Google"},
            "timeout": 3,
        },
        {
            "url": "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            "description": "GCP default service account token",
            "headers": {"Metadata-Flavor": "Google"},
            "timeout": 3,
        },
        {
            "url": "http://metadata.google.internal/computeMetadata/v1/instance/attributes/",
            "description": "GCP custom instance attributes",
            "headers": {"Metadata-Flavor": "Google"},
            "timeout": 3,
        },
    ],
    "azure": [
        {
            "url": "http://169.254.169.254/metadata/instance?api-version=2021-02-01",
            "description": "Azure instance metadata (compute + network)",
            "headers": {"Metadata": "true"},
            "timeout": 3,
        },
        {
            "url": "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://management.azure.com/",
            "description": "Azure managed identity token",
            "headers": {"Metadata": "true"},
            "timeout": 3,
        },
    ],
    "alibaba": [
        {
            "url": "http://100.100.100.200/latest/meta-data/",
            "description": "Alibaba Cloud ECS metadata root",
            "headers": {},
            "timeout": 3,
        },
    ],
    "digitalocean": [
        {
            "url": "http://169.254.169.254/metadata/v1.json",
            "description": "DigitalOcean droplet metadata",
            "headers": {},
            "timeout": 3,
        },
    ],
}

# Sensitive metadata paths that indicate credential exposure
SENSITIVE_PATTERNS = [
    "secret",
    "token",
    "password",
    "accesskey",
    "secretkey",
    "sessiontoken",
    "private_key",
    "ssh",
]


class CloudMetadataProbe(AbstractTool):
    """Probes cloud provider metadata endpoints for credential extraction.

    Designed to run AFTER an SSRF finding is confirmed. Attempts to reach
    each cloud provider's well-known metadata service endpoint. When a provider
    is reachable, enumerates IAM roles, extracts credentials, and collects
    instance metadata.

    Reports findings at HIGH severity for any reachable metadata endpoint,
    and CRITICAL severity when actual credentials (IAM keys, tokens) are extracted.
    """

    tool_name = "cloud_metadata_probe"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """Execute the cloud metadata probe.

        Args:
            ctx: ToolContext with target URL and engagement_id.

        Returns:
            UnifiedToolResult with findings for each reachable metadata endpoint.
        """
        engagement_id = ctx.engagement_id
        target = ctx.target

        builder = FindingBuilder(
            source_tool=self.tool_name,
            engagement_id=engagement_id,
        )

        findings: list[dict] = []
        reachable_providers: dict[str, list[dict]] = {}
        extracted_credentials: dict[str, list[dict]] = {}

        for provider, endpoints in CLOUD_METADATA_ENDPOINTS.items():
            provider_results = []
            for ep in endpoints:
                result = self._probe_endpoint(ep)
                # Carry the endpoint description through to the result
                result["description"] = ep["description"]
                if result["reachable"]:
                    provider_results.append(result)
                    logger.info(
                        "Cloud metadata probe: %s - %s REACHABLE",
                        provider,
                        ep["description"],
                    )

                    # Check for sensitive credentials in the response
                    if result.get("data"):
                        sensitive_items = self._extract_sensitive(result["data"])
                        if sensitive_items:
                            if provider not in extracted_credentials:
                                extracted_credentials[provider] = []
                            extracted_credentials[provider].extend(sensitive_items)

            if provider_results:
                reachable_providers[provider] = provider_results

        # If no provider was reachable, return result with info finding
        if not reachable_providers:
            inactive_finding = builder.add(
                finding_type="CLOUD_METADATA_UNREACHABLE",
                severity="INFO",
                endpoint=target,
                evidence={
                    "message": "No cloud metadata endpoints were reachable. "
                    "The target may not be running inside a cloud VM, "
                    "or IMDS may be blocked by network policies.",
                    "probed_endpoints": len([
                        ep
                        for endpoints in CLOUD_METADATA_ENDPOINTS.values()
                        for ep in endpoints
                    ]),
                    "providers_checked": list(CLOUD_METADATA_ENDPOINTS.keys()),
                },
                confidence=0.95,
            )
            findings.append(inactive_finding)

        # Generate findings for each reachable provider
        for provider, results in reachable_providers.items():
            provider.upper()

            # Collect all data from this provider
            all_data = {}
            for r in results:
                if r.get("data"):
                    all_data[r["description"]] = r["data"]

            # High-severity finding: metadata endpoint is reachable
            evidence = {
                "provider": provider,
                "endpoints_reachable": len(results),
                "metadata": {
                    r["description"]: r.get("data_preview", "")
                    for r in results
                },
                "message": (
                    f"Cloud metadata service reachable for {provider}. "
                    f"An SSRF vulnerability can be escalated to cloud credential "
                    f"exfiltration."
                ),
            }

            # Check if we extracted actual credentials
            provider_creds = extracted_credentials.get(provider, [])
            if provider_creds:
                severity = "CRITICAL"
                confidence = 0.95
                finding_type = "CLOUD_CREDENTIAL_EXFILTRATION"
                evidence["credentials_extracted"] = provider_creds
                evidence["message"] = (
                    f"Cloud credentials successfully extracted from {provider} "
                    f"metadata service! IAM keys/tokens can be used for "
                    f"cloud account compromise and lateral movement."
                )
            else:
                severity = "HIGH"
                confidence = 0.85
                finding_type = "CLOUD_METADATA_ACCESSIBLE"

            finding = builder.add(
                finding_type=finding_type,
                severity=severity,
                endpoint=f"metadata://{provider}/",
                evidence=evidence,
                confidence=confidence,
            )
            findings.append(finding)

            # Generate individual findings for extracted IAM roles
            if provider == "aws":
                self._report_aws_iam_roles(results, builder, findings)

            # Log credential findings
            if provider_creds:
                for cred in provider_creds:
                    logger.info(
                        "CLOUD CREDENTIAL EXTRACTED: %s - %s",
                        provider,
                        cred.get("type", "unknown"),
                    )

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target,
            started_at=datetime.now(UTC),
            findings=findings,
            status=ToolStatus.SUCCESS if findings else ToolStatus.SUCCESS_EMPTY,
        )
        result.findings_count = len(findings)
        stdout = json.dumps({
            "providers_reachable": len(reachable_providers),
            "providers": list(reachable_providers.keys()),
            "credentials_extracted": {
                p: len(c) for p, c in extracted_credentials.items()
            },
            "total_findings": len(findings),
        })
        result.stdout = stdout
        return result

    def _probe_endpoint(self, endpoint: dict) -> dict:
        """Probe a single metadata endpoint.

        Args:
            endpoint: Dict with url, description, headers, timeout.

        Returns:
            Dict with reachable status, data, and data_preview.
        """
        url = endpoint["url"]
        headers = endpoint["headers"]
        timeout = endpoint.get("timeout", 3)

        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout),
                follow_redirects=False,
                verify=False,
            ) as client:
                resp = client.get(url, headers=headers)

                if resp.status_code == 200:
                    data = resp.text
                    return {
                        "reachable": True,
                        "url": url,
                        "status_code": resp.status_code,
                        "data": data,
                        "data_preview": data[:500] if data else "(empty)",
                        "headers": dict(resp.headers),
                    }
                elif resp.status_code in (401, 403):
                    # IMDSv2 requires token — try IMDSv2 path
                    if "aws" in url and "token" not in url:
                        return self._try_aws_imdsv2(endpoint)
                    return {
                        "reachable": True,
                        "url": url,
                        "status_code": resp.status_code,
                        "data": f"Access denied (HTTP {resp.status_code}) — "
                        f"may require authentication or IMDSv2 token",
                        "data_preview": "",
                    }
                else:
                    return {
                        "reachable": False,
                        "url": url,
                        "status_code": resp.status_code,
                        "data": None,
                        "data_preview": "",
                    }
        except httpx.ConnectError:
            logger.debug("Cloud metadata endpoint unreachable: %s (connection refused)", url)
            return {"reachable": False, "url": url, "data": None, "data_preview": ""}
        except httpx.TimeoutException:
            logger.debug("Cloud metadata endpoint timeout: %s", url)
            return {"reachable": False, "url": url, "data": None, "data_preview": ""}
        except httpx.RemoteProtocolError:
            logger.debug("Cloud metadata endpoint protocol error: %s", url)
            return {"reachable": False, "url": url, "data": None, "data_preview": ""}
        except OSError as e:
            logger.debug("Cloud metadata endpoint OS error: %s — %s", url, e)
            return {"reachable": False, "url": url, "data": None, "data_preview": ""}
        except Exception as e:
            logger.debug("Cloud metadata endpoint error: %s — %s", url, e)
            return {"reachable": False, "url": url, "data": None, "data_preview": ""}

    def _try_aws_imdsv2(self, endpoint: dict) -> dict:
        """Try AWS IMDSv2 (requires token)."""
        try:
            # Step 1: Get token
            with httpx.Client(
                timeout=httpx.Timeout(3),
                verify=False,
            ) as client:
                token_resp = client.put(
                    "http://169.254.169.254/latest/api/token",
                    headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
                )
                if token_resp.status_code != 200:
                    return {
                        "reachable": False,
                        "url": endpoint["url"],
                        "data": None,
                        "data_preview": "",
                    }
                token = token_resp.text.strip()

            # Step 2: Use token to access metadata
            with httpx.Client(
                timeout=httpx.Timeout(3),
                verify=False,
            ) as client:
                resp = client.get(
                    endpoint["url"],
                    headers={"X-aws-ec2-metadata-token": token},
                )
                if resp.status_code == 200:
                    return {
                        "reachable": True,
                        "url": endpoint["url"],
                        "status_code": resp.status_code,
                        "data": resp.text,
                        "data_preview": resp.text[:500],
                        "headers": dict(resp.headers),
                        "imdsv2": True,
                    }
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            pass

        return {
            "reachable": False,
            "url": endpoint["url"],
            "data": None,
            "data_preview": "",
        }

    def _extract_sensitive(self, data: str) -> list[dict]:
        """Extract sensitive credential-like values from metadata response.

        Args:
            data: Raw response text from metadata endpoint.

        Returns:
            List of dicts with type and value (truncated) for each sensitive item.
        """
        sensitive_items = []
        try:
            # Try JSON parsing
            parsed = json.loads(data)
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    key_lower = key.lower()
                    if any(p in key_lower for p in SENSITIVE_PATTERNS):
                        if isinstance(value, str) and len(value) > 8:
                            sensitive_items.append({
                                "type": key,
                                "value_preview": value[:20] + "..." if len(value) > 20 else value,
                                "length": len(value),
                            })
        except (json.JSONDecodeError, ValueError):
            # Not JSON — check for key=value patterns or credential strings
            pass

        # Check for AWS-style credential patterns in raw text
        aws_key_pattern = re.compile(r"(AKIA[0-9A-Z]{16})")
        for match in aws_key_pattern.findall(data):
            sensitive_items.append({
                "type": "AWS_ACCESS_KEY",
                "value_preview": match[:20] + "...",
                "length": len(match),
            })

        # Check for session tokens (long base64/base64url strings)
        session_pattern = re.compile(
            r"(?:AKIA[0-9A-Z]{16}\S{100,})"
        )
        for match in session_pattern.findall(data):
            sensitive_items.append({
                "type": "AWS_CREDENTIAL_BLOCK",
                "value_preview": match[:30] + "...",
                "length": len(match),
            })

        return sensitive_items

    def _report_aws_iam_roles(
        self,
        results: list[dict],
        builder: FindingBuilder,
        findings: list[dict],
    ) -> None:
        """Extract and report individual IAM role credentials.

        Args:
            results: Probe results for AWS endpoints.
            builder: FindingBuilder instance.
            findings: Accumulated findings list to append to.
        """
        for result in results:
            if "iam/security-credentials" in result.get("url", ""):
                roles_text = result.get("data", "")
                if not roles_text:
                    continue

                roles = [
                    r.strip() for r in roles_text.split("\n") if r.strip()
                ]
                for role_name in roles:
                    # Probe each role's credentials
                    role_url = (
                        "http://169.254.169.254/latest/meta-data/"
                        f"iam/security-credentials/{role_name}"
                    )
                    role_result = self._probe_endpoint({
                        "url": role_url,
                        "description": f"AWS IAM role: {role_name}",
                        "headers": {},
                        "timeout": 3,
                    })

                    if role_result.get("reachable") and role_result.get("data"):
                        try:
                            creds = json.loads(role_result["data"])
                            finding = builder.add(
                                finding_type="AWS_IAM_ROLE_CREDENTIALS",
                                severity="CRITICAL",
                                endpoint=f"arn:aws:iam::{role_name}",
                                evidence={
                                    "role_name": role_name,
                                    "access_key_id": creds.get(
                                        "AccessKeyId", ""
                                    )[:10] + "...",
                                    "expiration": creds.get("Expiration", ""),
                                    "message": (
                                        f"AWS IAM role '{role_name}' credentials "
                                        f"extracted! Temporary access key, secret key, "
                                        f"and session token can be used for "
                                        f"full cloud account compromise."
                                    ),
                                },
                                confidence=0.98,
                            )
                            findings.append(finding)
                        except (json.JSONDecodeError, ValueError):
                            pass
