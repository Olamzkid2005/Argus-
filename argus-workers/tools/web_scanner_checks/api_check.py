"""
API security checks: mass assignment, OpenAPI discovery, JWT algorithm confusion.
"""
import base64
import json
import logging
import re
from urllib.parse import urljoin

from config.constants import LLM_MAX_GENERATED_PAYLOADS, RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

MASS_ASSIGN_PAYLOADS = [
    '{"role":"admin"}',
    '{"is_admin":true}',
    '{"admin":1}',
    '{"privilege":"superuser"}',
    '{"verified":true}',
]

OPENAPI_PATHS = [
    "/.well-known/openapi",
    "/api-docs",
    "/swagger.json",
    "/openapi.json",
    "/api/swagger.json",
    "/api/openapi.json",
]

JWT_PATTERN = r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'


def run_check(target_url: str, session, findings: list) -> list[dict]:
    return ApiCheck().check(target_url, session, findings)
def _check_mass_assignment(target_url, session, findings):
    api_paths = ["/api/v1/users", "/api/users", "/api/v1/accounts", "/api/accounts"]
    for path in api_paths:
        url = urljoin(target_url, path.lstrip("/"))
        for payload in MASS_ASSIGN_PAYLOADS:
            try:
                resp = safe_request("POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                    json=json.loads(payload),
                                    headers={"Content-Type": "application/json"})
                if resp and resp.status_code in (200, 201):
                    try:
                        data = resp.json()
                        data_str = json.dumps(data).lower()
                        if any(x in data_str for x in ["admin", "role", "privilege", "is_admin"]):
                            findings.append(make_finding("MASS_ASSIGNMENT", "HIGH", url, {
                                "payload": payload,
                                "response_preview": json.dumps(data)[:200],
                            }, 0.6))
                    except (json.JSONDecodeError, ValueError):
                        pass
            except Exception:
                logger.debug(f"Mass assignment request failed for {url}")


def _check_openapi_discovery(target_url, session, findings):
    for path in OPENAPI_PATHS:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code != 200:
            continue
        content_type = resp.headers.get("Content-Type", "")
        if "json" not in content_type:
            continue
        try:
            spec = resp.json()
            if "openapi" in spec or "swagger" in spec or "paths" in spec:
                endpoints = list(spec.get("paths", {}).keys())[:10]
                findings.append(make_finding("OPENAPI_SPEC_EXPOSED", "MEDIUM", url, {
                    "spec_type": "openapi" if "openapi" in spec else "swagger",
                    "endpoints_exposed": endpoints,
                    "spec_preview": json.dumps(spec)[:200],
                }, 0.9))
                break
        except json.JSONDecodeError:
            pass


def _check_jwt_algorithm_confusion(target_url, session, findings):
    resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
    if not resp:
        return

    jwts = re.findall(JWT_PATTERN, resp.text)
    js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', resp.text)
    for js_url in js_urls[:5]:
        if not js_url.startswith("http"):
            js_url = urljoin(target_url, js_url)
        js_resp = safe_request("GET", js_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if js_resp and js_resp.status_code == 200:
            jwts.extend(re.findall(JWT_PATTERN, js_resp.text))

    jwts = list(set(jwts))[:3]
    for jwt_token in jwts:
        parts = jwt_token.split(".")
        if len(parts) != 3:
            continue
        try:
            json.loads(base64.urlsafe_b64decode(parts[0] + "==").decode("utf-8"))
        except Exception:
            continue
        none_header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).decode().rstrip("=")
        none_jwt = f"{none_header}.{parts[1]}."
        for auth_header in ["Authorization", "X-Access-Token", "Token"]:
            test_resp = safe_request("GET", target_url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                     headers={auth_header: f"Bearer {none_jwt}"})
            if test_resp and test_resp.status_code == 200:
                findings.append(make_finding("JWT_ALGORITHM_CONFUSION", "HIGH", target_url, {
                    "original_jwt": jwt_token[:20] + "...",
                    "test_algorithm": "none",
                    "auth_header": auth_header,
                    "message": "Server accepted JWT with alg:none",
                }, 0.7))
                return


class ApiCheck:
    def __init__(self):
        self.name = "api"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
