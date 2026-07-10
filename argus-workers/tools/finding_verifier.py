"""
Finding verification layer for high-volume false positive sources.

Verifies findings by re-testing with independent methods. Gated behind
ARGUS_FF_FINDING_VERIFICATION feature flag.
"""

import ipaddress
import logging
import urllib.parse
from urllib.parse import urlparse

import httpx

from feature_flags import is_enabled
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

# M-v4-05: Known cloud metadata and internal hostnames to block for SSRF prevention.
_BLOCKED_METADATA_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "[::1]",
    "::1",
    "169.254.169.254",  # AWS/GCP/Azure metadata
    "metadata.google.internal",  # GCP
    "metadata",  # GCP short name
    "instance-data",  # AWS short name
    "instance-data.us-east-1.compute.internal",  # AWS regional
    "100.100.100.200",  # Alibaba Cloud
}


def _validate_verification_url(endpoint: str) -> str:
    """Validate and sanitize a finding endpoint URL for SSRF prevention.

    Raises ValueError if the endpoint targets internal/private/cloud-metadata
    hosts or uses a blocked protocol. Prevents finding verifier SSRF (M-v4-05).

    Args:
        endpoint: The finding endpoint URL to validate.

    Returns:
        The validated endpoint URL.

    Raises:
        ValueError: If the endpoint is invalid or blocked.
    """
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid or missing hostname in endpoint: {endpoint}")

    # Block non-HTTP protocols (file://, gopher://, etc.)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked protocol '{parsed.scheme}' in endpoint: {endpoint}")

    hostname = parsed.hostname or ""
    try:
        # Check if hostname is an IP literal
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            raise ValueError(f"Blocked internal IP: {hostname}")
        return endpoint
    except ValueError as ve:
        # Re-raise our own ValueError (blocked IP), suppress ip_address parsing errors
        if "Blocked internal IP" in str(ve):
            raise
        # Not an IP literal — check hostname against blocklist
        pass

    if hostname.lower() in _BLOCKED_METADATA_HOSTNAMES:
        raise ValueError(f"Blocked metadata/internal hostname: {hostname}")

    return endpoint


# Common SQL error markers for differential analysis
SQL_ERROR_MARKERS = [
    "sql",
    "mysql",
    "postgresql",
    "oracle",
    "sqlite",
    "syntax error",
    "unclosed quotation",
    "odbc",
    "driver",
    "db2",
    "microsoft ole db",
]

# Common XSS reflection patterns
XSS_TEST_PAYLOADS = [
    "<script>alert(1)</script>",
    '"><script>alert(1)</script>',
    "'><script>alert(1)</script>",
]


async def verify_sqli(
    endpoint: str,
    payload: str,
    benign_variant: str | None = None,
    engagement_id: str = "",
) -> dict:
    """
    Verify SQL injection by differential response analysis.

    Compares response to a benign variant of the payload. If the benign
    variant doesn't trigger SQL error markers but the original does, the
    finding is likely a true positive.
    """
    slog = ScanLogger("finding_verifier", engagement_id=engagement_id)
    result = {"verified": False, "confidence": "low", "reason": None}

    slog.tool_start("verify_sqli", [endpoint[:60]])

    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        slog.info("SQLi verification disabled (feature flag off)")
        return result

    # M-v4-05: Validate endpoint URL to prevent SSRF from malicious finding data
    try:
        _validate_verification_url(endpoint)
    except ValueError as e:
        slog.warn("SQLi verification blocked: %s", e)
        result["reason"] = f"Blocked: {e}"
        return result

    try:
        async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
            # Test with the original payload
            # httpx merges params with any existing query string in the URL,
            # so we always pass params regardless of whether ? is present.
            try:
                original_resp = await client.get(endpoint, params={"q": payload})
                original_text = original_resp.text.lower()
            except Exception:
                original_resp = await client.post(endpoint, data={"input": payload})
                original_text = original_resp.text.lower()

            # Test with benign variant
            benign = benign_variant or payload.replace("'", "").replace(
                '"', ""
            ).replace(";", "")
            try:
                benign_resp = await client.get(endpoint, params={"q": benign})
                benign_text = benign_resp.text.lower()
            except Exception:
                benign_resp = await client.post(endpoint, data={"input": benign})
                benign_text = benign_resp.text.lower()

            # Differential analysis
            original_markers = [m for m in SQL_ERROR_MARKERS if m in original_text]
            benign_markers = [m for m in SQL_ERROR_MARKERS if m in benign_text]

            if original_markers and not benign_markers:
                result["verified"] = True
                result["confidence"] = "high"
                result["reason"] = (
                    f"SQL error markers in original only: {original_markers}"
                )
                slog.info("SQLi verified (high conf): markers in original only")
            elif original_markers and benign_markers:
                result["confidence"] = "medium"
                result["reason"] = (
                    f"SQL markers in both: original={original_markers}, benign={benign_markers}"
                )
                slog.info("SQLi potential (medium conf): markers in both")
            elif not original_markers and not benign_markers:
                result["verified"] = True  # Could be blind/boolean-based
                result["confidence"] = "low"
                result["reason"] = (
                    "No SQL markers in either response — could be blind SQLi"
                )
                slog.info("SQLi potential (low conf): blind possible")
            else:
                result["reason"] = (
                    "Benign triggered markers but original didn't (likely FP)"
                )
                slog.info("SQLi likely false positive")
    except Exception as e:
        slog.warn("SQLi verification error: %s", e)
        logger.warning("SQLi verification failed for %s: %s", endpoint, e)
        result["reason"] = f"Verification error: {e}"

    slog.info(
        f"verification result: verified={result['verified']}, confidence={result['confidence']}"
    )
    slog.tool_complete("verify_sqli")
    return result


async def verify_xss(
    endpoint: str, payload: str, param: str | None = None, engagement_id: str = ""
) -> dict:
    """
    Verify XSS by checking if payload is reflected in response.

    Note: This catches reflected XSS. DOM-based XSS requires browser
    instrumentation and won't be detected here.
    """
    slog = ScanLogger("finding_verifier", engagement_id=engagement_id)
    result = {"verified": False, "confidence": "low", "reason": None}

    slog.tool_start("verify_xss", [endpoint[:60]])

    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        slog.info("XSS verification disabled (feature flag off)")
        return result

    # M-v4-05: Validate endpoint URL to prevent SSRF from malicious finding data
    try:
        _validate_verification_url(endpoint)
    except ValueError as e:
        slog.warn("XSS verification blocked: %s", e)
        result["reason"] = f"Blocked: {e}"
        return result

    try:
        async with httpx.AsyncClient(
            timeout=15.0, verify=True, follow_redirects=True
        ) as client:
            test_param = param or "q"

            # Test each payload
            for test_payload in [payload] + XSS_TEST_PAYLOADS:
                encoded_payload = urllib.parse.quote(test_payload)
                if "?" in endpoint:
                    test_url = f"{endpoint}&{test_param}={encoded_payload}"
                else:
                    test_url = f"{endpoint}?{test_param}={encoded_payload}"

                try:
                    resp = await client.get(test_url)
                    text = resp.text

                    # Check if payload is reflected
                    if test_payload in text:
                        result["verified"] = True
                        result["confidence"] = "high"
                        result["reason"] = (
                            f"Payload '{test_payload[:20]}...' reflected in response"
                        )
                        slog.info("XSS verified (high conf): payload reflected")
                        break
                    # Check for partial reflection (URL-encoded, etc.)
                    encoded = urllib.parse.quote(test_payload)
                    if encoded in text:
                        result["verified"] = True
                        result["confidence"] = "medium"
                        result["reason"] = (
                            f"Payload reflected (URL-encoded): '{encoded[:20]}...'"
                        )
                        slog.info("XSS verified (medium conf): URL-encoded reflection")
                        break
                except Exception:
                    continue

            if not result["verified"]:
                result["reason"] = "No payload reflection detected in response"
                slog.info("XSS not verified: no reflection detected")
    except Exception as e:
        slog.warn("XSS verification error: %s", e)
        logger.warning("XSS verification failed for %s: %s", endpoint, e)
        result["reason"] = f"Verification error: {e}"

    slog.info(
        f"verification result: verified={result['verified']}, confidence={result['confidence']}"
    )
    slog.tool_complete("verify_xss")
    return result


async def verify_open_redirect(endpoint: str, engagement_id: str = "") -> dict:
    """
    Verify open redirect by following the redirect chain.

    Checks if the final destination is an external domain.
    """
    slog = ScanLogger("finding_verifier", engagement_id=engagement_id)
    result = {"verified": False, "confidence": "low", "reason": None}

    slog.tool_start("verify_open_redirect", [endpoint[:60]])

    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        slog.info("Open redirect verification disabled (feature flag off)")
        return result

    # M-v4-05: Validate endpoint URL to prevent SSRF from malicious finding data
    try:
        _validate_verification_url(endpoint)
    except ValueError as e:
        slog.warn("Open redirect verification blocked: %s", e)
        result["reason"] = f"Blocked: {e}"
        return result

    try:
        async with httpx.AsyncClient(
            timeout=15.0, verify=True, follow_redirects=True
        ) as client:
            resp = await client.get(endpoint)

            if resp.history:
                original_domain = urlparse(str(resp.history[0].url)).netloc
                final_domain = urlparse(str(resp.url)).netloc

                if final_domain and final_domain != original_domain:
                    result["verified"] = True
                    result["confidence"] = "high"
                    result["reason"] = (
                        f"Redirects from {original_domain} to external {final_domain}"
                    )
                    result["redirect_chain"] = [str(h.url) for h in resp.history] + [
                        str(resp.url)
                    ]
                    slog.info(
                        "Open redirect verified: %s -> %s",
                        original_domain,
                        final_domain,
                    )
                else:
                    result["reason"] = f"Redirects to same domain ({final_domain})"
                    slog.info("Same-domain redirect: %s", final_domain)
            else:
                result["reason"] = f"No redirect detected (status: {resp.status_code})"
                slog.info("No redirect detected")
    except httpx.HTTPError as e:
        slog.warn("Open redirect HTTP error: %s", e)
        logger.warning("Open redirect verification failed for %s: %s", endpoint, e)
        result["reason"] = f"HTTP error: {e}"
    except Exception as e:
        slog.warn("Open redirect verification error: %s", e)
        logger.warning("Open redirect verification error: %s", e)
        result["reason"] = f"Verification error: {e}"

    slog.info(
        f"verification result: verified={result['verified']}, confidence={result['confidence']}"
    )
    slog.tool_complete("verify_open_redirect")
    return result


# Registry mapping finding types to verifiers
VERIFIERS = {
    "sql-injection": verify_sqli,
    "sqli": verify_sqli,
    "xss": verify_xss,
    "cross-site-scripting": verify_xss,
    "open-redirect": verify_open_redirect,
    "open_redirect": verify_open_redirect,
}


async def verify_finding(finding: dict, engagement_id: str = "") -> dict:
    """
    Verify a finding using the appropriate verifier based on finding type.

    Returns the finding with verification metadata added.
    """
    import functools

    finding_type = (
        (finding.get("type") or "").lower().replace(" ", "-").replace("_", "-")
    )
    verifier = VERIFIERS.get(finding_type)

    if not verifier:
        finding["verification"] = {
            "verified": None,
            "reason": "No verifier for this finding type",
        }
        return finding

    from typing import Any, cast, Callable

    endpoint = finding.get("endpoint") or finding.get("url") or ""
    payload = finding.get("evidence", {}).get("payload") or finding.get("payload") or ""

    verifier_fn = cast(Callable[..., Any], verifier)
    bound_verifier = functools.partial(verifier_fn, engagement_id=engagement_id)
    # Open redirect verifier does not accept payload (only endpoint + engagement_id)
    if finding_type in ("open-redirect", "open_redirect"):
        result = await bound_verifier(endpoint)
    else:
        result = await bound_verifier(endpoint, payload)
    finding["verification"] = result

    return finding
