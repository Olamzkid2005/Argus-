"""
GraphQL introspection endpoint checking.
"""
import logging

from config.constants import RATE_LIMIT_DELAY_MS, SSL_TIMEOUT

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
    def __init__(self):
        self.name = "graphql"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        return run_check(target_url, session, findings)
