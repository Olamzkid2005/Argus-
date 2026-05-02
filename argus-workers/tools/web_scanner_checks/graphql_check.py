"""
GraphQL introspection endpoint checking.
"""
import json
import logging
from urllib.parse import urljoin

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding, safe_request

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = SSL_TIMEOUT
_DEFAULT_RATE_LIMIT = RATE_LIMIT_DELAY_MS / 1000.0

GRAPHQL_ENDPOINTS = [
    "/graphql",
    "/api/graphql",
    "/v1/graphql",
    "/query",
]

INTROSPECTION_QUERY = {
    "query": "{__schema{kind,fields{name}}}"
}


def run_check(target_url: str, session, findings: list) -> list[dict]:
    for path in GRAPHQL_ENDPOINTS:
        url = urljoin(target_url, path.lstrip("/"))
        resp = safe_request("GET", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT)
        if not resp or resp.status_code not in (200, 400, 405):
            continue
        introspection_resp = safe_request("POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                                          json=INTROSPECTION_QUERY,
                                          headers={"Content-Type": "application/json"})
        if not introspection_resp or introspection_resp.status_code != 200:
            continue
        try:
            data = introspection_resp.json()
            if "__schema" in data.get("data", {}):
                findings.append(make_finding("GRAPHQL_INTROSPECTION_ENABLED", "HIGH", url, {
                    "message": "GraphQL introspection is enabled",
                    "response_preview": json.dumps(data)[:200],
                }, 0.9))
                break
        except json.JSONDecodeError:
            pass
    return findings


class GraphqlCheck:
    def __init__(self):
        self.name = "graphql"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
