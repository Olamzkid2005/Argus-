"""
GraphQL introspection endpoint checking.
"""
import json
import logging
from urllib.parse import urljoin

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

from ._helpers import make_finding

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
    return GraphqlCheck().check(target_url, session, findings)


class GraphqlCheck:
    """Check for exposed GraphQL introspection endpoints."""

    def __init__(self):
        self.name = "graphql"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        from ._helpers import safe_request as _safe

        for path in GRAPHQL_ENDPOINTS:
            url = urljoin(target_url.rstrip("/") + "/", path.lstrip("/"))
            resp = _safe("POST", url, session, _DEFAULT_TIMEOUT, _DEFAULT_RATE_LIMIT,
                         json=INTROSPECTION_QUERY,
                         headers={"Content-Type": "application/json"})
            if resp is None:
                continue
            if resp.status_code not in (200, 400):
                continue
            try:
                data = resp.json()
                if "data" in data and data["data"].get("__schema"):
                    schema = data["data"]["__schema"]
                    findings.append(make_finding("GRAPHQL_INTROSPECTION_EXPOSED", "HIGH", url, {
                        "query_type": schema.get("queryType", {}).get("name", "unknown"),
                        "mutation_type": schema.get("mutationType", {}).get("name", "unknown"),
                        "fields_count": len(schema.get("fields", [])),
                    }, 0.95))
                    break
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return findings
