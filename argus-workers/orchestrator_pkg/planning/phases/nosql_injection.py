"""Phase: no_sql_injection — _activate_nosql_injection and _nosql_injection_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# NoSQL databases and related technologies for tech_stack matching
_NOSQL_DATABASES: set[str] = {
    # Document stores
    "mongodb", "mongo", "mongoose", "mongos", "mongosh",
    "couchdb", "couchbase", "pouchdb",
    "ravendb", "litedb", "sphinx",
    # Key-value stores
    "redis", "redis-rack", "redis-py",
    "dynamodb", "amazon dynamodb", "aws dynamodb",
    "riak", "etcd", "consul",
    # Wide-column stores
    "cassandra", "datastax", "scylla", "scylladb",
    "apache cassandra", "hbase", "apache hbase",
    # Graph databases
    "neo4j", "neo4j-ogm", "sparql",
    "orientdb", "arangodb", "janusgraph",
    # Search/document engines
    "elasticsearch", "elastic", "opensearch",
    "meilisearch", "algolia", "typesense",
    # Real-time / Firebase
    "firebase", "firestore", "realtime database",
    "supabase", "appwrite", "nhost",
    # Other NoSQL
    "cockroachdb", "rethinkdb", "leveldb",
    "rocksdb", "badgerdb", "boltdb",
    # ORM/ODM abstractions
    "prisma", "typeorm", "sequelize",
    "django mongodb", "flask-pymongo",
}
def _activate_nosql_injection(rc) -> tuple[bool, str]:
    """Activate when NoSQL databases are detected in tech_stack.

    NoSQL injection occurs when user input is embedded in NoSQL query
    operators ($where, $gt, $ne, etc.) without proper sanitization.
    Unlike SQL injection, NoSQL injection can use JSON-structured queries
    and operator injection, making detection more nuanced.

    Activates when:
      - ``has_nosql`` flag is set on ReconContext (forward-compatible)
      - ``nosql_endpoints`` list is populated (forward-compatible)
      - NoSQL database keywords appear in tech_stack
      - API endpoints are present (NoSQL databases often queried via APIs)
      - Parameter-bearing URLs are present (NoSQL injection vector)
    """
    # Forward-compatible: check for dedicated NoSQL attribute
    has_nosql = _get_attr(rc, "has_nosql", False)
    if has_nosql:
        return True, "NoSQL injection signals detected in recon"

    nosql_eps = _get_attr(rc, "nosql_endpoints", [])
    if nosql_eps and len(nosql_eps) > 0:
        return True, f"{len(nosql_eps)} NoSQL endpoint(s) found"

    # Check tech_stack for NoSQL database keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _NOSQL_DATABASES if kw in tech_lower]
        if matched:
            return True, f"NoSQL database detected: {', '.join(matched[:3])}"

    # API endpoints often query NoSQL databases
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — NoSQL databases may be queried via API parameters"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — NoSQL injection testing recommended"

    # Parameter-bearing URLs as NoSQL injection vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential NoSQL injection vector"

    return False, "no NoSQL database or injection signals detected"


def _nosql_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for NoSQL injection vulnerability testing.

    Tests for:
      - MongoDB $where / $gt / $ne operator injection
      - MongoDB JSON query parameter injection
      - CouchDB document query injection
      - Firebase Realtime Database rules injection
      - Elasticsearch query DSL injection
      - Cassandra CQL injection
      - Redis command injection via parameters
      - NoSQL blind injection (boolean-based, time-based)
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="NoSQL injection vulnerability scanning (MongoDB, CouchDB, Elasticsearch)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "nosql,injection,mongodb,couchdb,esql"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="NoSQL operator injection and blind injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "nosql,injection,blind,operator,exposure"],
        ),
    ]
    return tools


# ── Phase: LDAP Injection Testing ─────────────────────────────────────────

# LDAP-related keywords and technologies for tech_stack matching
_LDAP_KEYWORDS: set[str] = {
    "ldap", "ldap injection", "openldap", "389ds",
    "active directory", "ad ds", "ad lds", "ad fs",
    "apache directory", "apacheds", "fedora directory",
    "unboundid", "novell edirectory", "oracle internet directory",
    "sun directory", "openam", "opendj", "pensieve ldap", "ldapjs", "spring-ldap", "spring data ldap",
    "ldaptive", "ldap3", "python-ldap", "ldapauthenticator",
    "django-auth-ldap", "flask-ldap", "php ldap",
}
