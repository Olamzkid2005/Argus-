"""
Finding verification layer for high-volume false positive sources.

Verifies findings by re-testing with independent methods. Gated behind
ARGUS_FF_FINDING_VERIFICATION feature flag.
"""
import logging
import httpx
from urllib.parse import urlparse, urljoin
from feature_flags import is_enabled

logger = logging.getLogger(__name__)

# Common SQL error markers for differential analysis
SQL_ERROR_MARKERS = [
    "sql", "mysql", "postgresql", "oracle", "sqlite",
    "syntax error", "unclosed quotation", "odbc",
    "driver", "db2", "microsoft ole db",
]

# Common XSS reflection patterns
XSS_TEST_PAYLOADS = [
    "<script>alert(1)</script>",
    "\"><script>alert(1)</script>",
    "'><script>alert(1)</script>",
]


async def verify_sqli(endpoint: str, payload: str, benign_variant: str | None = None) -> dict:
    """
    Verify SQL injection by differential response analysis.
    
    Compares response to a benign variant of the payload. If the benign
    variant doesn't trigger SQL error markers but the original does, the
    finding is likely a true positive.
    """
    result = {"verified": False, "confidence": "low", "reason": None}
    
    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        return result
    
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            # Test with the original payload
            try:
                original_resp = await client.get(endpoint, params={"q": payload} if "?" not in endpoint else None)
                original_text = original_resp.text.lower()
            except Exception:
                original_resp = await client.post(endpoint, data={"input": payload})
                original_text = original_resp.text.lower()
            
            # Test with benign variant
            benign = benign_variant or payload.replace("'", "").replace('"', "").replace(";", "")
            try:
                benign_resp = await client.get(endpoint, params={"q": benign} if "?" not in endpoint else None)
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
                result["reason"] = f"SQL error markers in original only: {original_markers}"
            elif original_markers and benign_markers:
                result["confidence"] = "medium"
                result["reason"] = f"SQL markers in both: original={original_markers}, benign={benign_markers}"
            elif not original_markers and not benign_markers:
                result["verified"] = True  # Could be blind/boolean-based
                result["confidence"] = "low"
                result["reason"] = "No SQL markers in either response — could be blind SQLi"
            else:
                result["reason"] = "Benign triggered markers but original didn't (likely FP)"
    except Exception as e:
        logger.warning(f"SQLi verification failed for {endpoint}: {e}")
        result["reason"] = f"Verification error: {e}"
    
    return result


async def verify_xss(endpoint: str, payload: str, param: str | None = None) -> dict:
    """
    Verify XSS by checking if payload is reflected in response.
    
    Note: This catches reflected XSS. DOM-based XSS requires browser
    instrumentation and won't be detected here.
    """
    result = {"verified": False, "confidence": "low", "reason": None}
    
    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        return result
    
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            test_param = param or "q"
            
            # Test each payload
            for test_payload in [payload] + XSS_TEST_PAYLOADS:
                if "?" in endpoint:
                    test_url = f"{endpoint}&{test_param}={test_payload}"
                else:
                    test_url = f"{endpoint}?{test_param}={test_payload}"
                
                try:
                    resp = await client.get(test_url)
                    text = resp.text
                    
                    # Check if payload is reflected
                    if test_payload in text:
                        result["verified"] = True
                        result["confidence"] = "high"
                        result["reason"] = f"Payload '{test_payload[:20]}...' reflected in response"
                        break
                    # Check for partial reflection (URL-encoded, etc.)
                    import urllib.parse
                    encoded = urllib.parse.quote(test_payload)
                    if encoded in text:
                        result["verified"] = True
                        result["confidence"] = "medium"
                        result["reason"] = f"Payload reflected (URL-encoded): '{encoded[:20]}...'"
                        break
                except Exception:
                    continue
            
            if not result["verified"]:
                result["reason"] = "No payload reflection detected in response"
    except Exception as e:
        logger.warning(f"XSS verification failed for {endpoint}: {e}")
        result["reason"] = f"Verification error: {e}"
    
    return result


async def verify_open_redirect(endpoint: str) -> dict:
    """
    Verify open redirect by following the redirect chain.
    
    Checks if the final destination is an external domain.
    """
    result = {"verified": False, "confidence": "low", "reason": None}
    
    if not is_enabled("FINDING_VERIFICATION"):
        result["reason"] = "Verification disabled (feature flag off)"
        return result
    
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(endpoint)
            
            if resp.history:
                original_domain = urlparse(str(resp.history[0].url)).netloc
                final_domain = urlparse(str(resp.url)).netloc
                
                if final_domain and final_domain != original_domain:
                    result["verified"] = True
                    result["confidence"] = "high"
                    result["reason"] = f"Redirects from {original_domain} to external {final_domain}"
                    result["redirect_chain"] = [str(h.url) for h in resp.history] + [str(resp.url)]
                else:
                    result["reason"] = f"Redirects to same domain ({final_domain})"
            else:
                result["reason"] = "No redirect detected (status: {resp.status_code})"
    except httpx.HTTPError as e:
        logger.warning(f"Open redirect verification failed for {endpoint}: {e}")
        result["reason"] = f"HTTP error: {e}"
    except Exception as e:
        logger.warning(f"Open redirect verification error: {e}")
        result["reason"] = f"Verification error: {e}"
    
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


async def verify_finding(finding: dict) -> dict:
    """
    Verify a finding using the appropriate verifier based on finding type.
    
    Returns the finding with verification metadata added.
    """
    finding_type = (finding.get("type") or "").lower().replace(" ", "-")
    verifier = VERIFIERS.get(finding_type)
    
    if not verifier:
        finding["verification"] = {"verified": None, "reason": "No verifier for this finding type"}
        return finding
    
    endpoint = finding.get("endpoint") or finding.get("url") or ""
    payload = finding.get("evidence", {}).get("payload") or finding.get("payload") or ""
    
    result = await verifier(endpoint, payload)
    finding["verification"] = result
    
    return finding
