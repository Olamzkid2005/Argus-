"""Phase: graphql_introspection — _activate_graphql_introspection and _graphql_introspection_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




def _activate_graphql_introspection(rc) -> tuple[bool, str]:
    """Activate when GraphQL endpoints or signals are detected in recon.

    GraphQL introspection queries can expose the entire schema, including
    hidden fields, deprecated fields, and internal types. Activates when:
      - ``has_graphql`` flag is set on ReconContext (forward-compatible)
      - ``graphql_endpoints`` list is populated
      - GraphQL-related keywords appear in tech_stack
      - API endpoints are present (GraphQL is an API technology)
    """
    # Forward-compatible: check for dedicated GraphQL attribute
    has_gql = _get_attr(rc, "has_graphql", False)
    if has_gql:
        return True, "GraphQL endpoints detected in recon"

    gql_endpoints = _get_attr(rc, "graphql_endpoints", [])
    if gql_endpoints and len(gql_endpoints) > 0:
        return True, f"{len(gql_endpoints)} GraphQL endpoint(s) found"

    # Check tech_stack for GraphQL-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        gql_keywords = {"graphql", "gql", "apollo", "relay", "hasura",
                        "graphiql", "graphql-playground", "graphene",
                        "gqlgen", "graphql-ruby", "graphql-php",
                        "graphql-java", "typegraphql", "nest.js graphql"}
        matched = [kw for kw in gql_keywords if kw in tech_lower]
        if matched:
            return True, f"GraphQL-relevant tech detected: {', '.join(matched)}"

    # API endpoints may include GraphQL
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — GraphQL endpoints may be present"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — GraphQL testing recommended"

    return False, "no GraphQL signals detected"


def _graphql_introspection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for GraphQL introspection and schema probing.

    Tests for:
      - Introspection query enabled (schema exposure)
      - Schema field discovery (hidden/deprecated fields)
      - GraphQL injection via query parameters
      - GraphQL playground/graphiql exposure
      - Auth bypass via introspection
      - Batching attacks on GraphQL endpoints
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="GraphQL introspection query detection and schema probing",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "graphql,introspection,schema,playground"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="GraphQL injection and auth bypass scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "graphql,injection,exposure,api"],
        ),
    ]


# ── Phase: API Security Testing ────────────────────────────────────────
