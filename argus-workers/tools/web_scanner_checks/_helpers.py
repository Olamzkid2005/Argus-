import base64
import json
import logging
import time

import requests
import urllib3
from requests.exceptions import ConnectionError, RequestException, Timeout

logger = logging.getLogger(__name__)


def safe_request(
    method: str,
    url: str,
    session: requests.Session,
    timeout: int,
    rate_limit: float,
    **kwargs,
) -> requests.Response | None:
    try:
        kwargs.setdefault("timeout", timeout)
        kwargs.setdefault("allow_redirects", True)
        kwargs.setdefault("verify", True)
        resp = session.request(method, url, **kwargs)
        time.sleep(rate_limit)
        return resp
    except (
        TimeoutError,
        RequestException,
        Timeout,
        ConnectionError,
        urllib3.exceptions.SSLError,
    ) as e:
        logger.debug(f"Request failed: {e}")
        return None


def make_finding(
    finding_type: str,
    severity: str,
    endpoint: str,
    evidence: dict,
    confidence: float = 0.8,
) -> dict:
    try:
        from utils.sanitization import sanitize_evidence

        sanitized = sanitize_evidence(evidence)
    except ImportError:
        sanitized = evidence
    return {
        "type": finding_type,
        "severity": severity,
        "endpoint": endpoint,
        "evidence": sanitized,
        "confidence": confidence,
    }


def detect_framework(response) -> str:
    if not response:
        return "unknown"
    headers = {k.lower(): v for k, v in response.headers.items()}
    body = response.text[:2000].lower() if response.text else ""
    powered_by = str(headers.get("x-powered-by", "")).lower()
    if "django" in body or "csrfmiddlewaretoken" in body:
        return "Django"
    if powered_by:
        if "express" in powered_by:
            return "Express"
        if "asp.net" in powered_by:
            return "ASP.NET"
        if "php" in powered_by:
            return "PHP"
        if "rails" in powered_by or "ruby" in powered_by:
            return "Rails"
    server = str(headers.get("server", "")).lower()
    if "nginx" in server:
        return "nginx"
    if "apache" in server:
        return "Apache"
    if "iis" in server or "microsoft-iis" in server:
        return "IIS"
    if "laravel" in body or "livewire" in body:
        return "Laravel"
    if "spring" in body or "javax.faces" in body:
        return "Spring"
    if "react" in body or "reactroot" in body:
        return "React"
    if "vue" in body or "vuejs" in body or "vueroot" in body:
        return "Vue"
    if "angular" in body or "ng-" in body:
        return "Angular"
    if "next" in body or "__next" in body or "nextjs" in body:
        return "Next.js"
    if "nuxt" in body:
        return "Nuxt"
    if "wordpress" in body or "wp-" in body or "wp-content" in body:
        return "WordPress"
    if "drupal" in body:
        return "Drupal"
    if "joomla" in body:
        return "Joomla"
    if "shopify" in body:
        return "Shopify"
    if "magento" in body:
        return "Magento"
    return "unknown"


def test_jwt_alg_none(
    jwt_token: str,
    target_url: str,
    request_func,
    auth_headers: list[str] | None = None,
) -> dict | None:
    """Test JWT for 'alg:none' vulnerability.

    Takes a JWT token, modifies its header to use 'none' algorithm,
    and tests if the server accepts it via the provided request function.

    Args:
        jwt_token: The original JWT token string.
        target_url: The URL to test against.
        request_func: A callable (url, headers) -> Response | None.
        auth_headers: List of auth header names to try.

    Returns:
        A finding dict if vulnerable, None otherwise.
    """
    parts = jwt_token.split(".")
    if len(parts) != 3:
        return None
    try:
        json.loads(base64.urlsafe_b64decode(parts[0] + "==").decode("utf-8"))
    except Exception:
        return None

    none_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    none_jwt = f"{none_header}.{parts[1]}."

    if auth_headers is None:
        auth_headers = ["Authorization", "X-Access-Token", "Token"]

    for auth_header in auth_headers:
        resp = request_func(target_url, {auth_header: f"Bearer {none_jwt}"})
        if resp is not None and resp.status_code == 200:
            return {
                "type": "JWT_ALGORITHM_CONFUSION",
                "severity": "HIGH",
                "endpoint": target_url,
                "evidence": {
                    "original_jwt": jwt_token[:20] + "...",
                    "test_algorithm": "none",
                    "auth_header": auth_header,
                    "message": "Server accepted JWT with alg:none",
                },
                "confidence": 0.7,
            }
    return None
