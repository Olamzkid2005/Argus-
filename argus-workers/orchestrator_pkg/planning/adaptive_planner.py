"""
AdaptiveWorkflowPlanner — dynamically generates an ordered testing plan from recon signals.

Design
------

Instead of running a fixed sequence of phases (recon → scan → analyze → report),
the planner examines ReconContext signals and produces a **WorkflowPlan** with
ordered TestingPhases. Each phase activates only when its preconditions are met:

    has_login_page=True  ──►  auth_testing phase
    +                            │
    auth_endpoints found ────────┤
                                 ▼
                          session_analysis phase
                                 │
                                 ▼
                          access_control phase

The planner is **signal-driven, not tool-driven**: phases define *what to test*
(authentication, authorization, API security, etc.), not *which binary to run*.
Tool selection within each phase is a separate concern.

Integration
-----------

The orchestrator calls the planner after recon completes (ReconContext is available).
The resulting WorkflowPlan:
  1. Guides the LLM agent's tool selection (agent receives phase descriptions)
  2. Configures the deterministic safety-net (skips irrelevant phases, focuses on active ones)
  3. Provides observability (logs which phases were activated and why)

Extending
---------

Add new phases by appending to PHASE_DEFINITIONS. Each definition requires:
  - A descriptive name
  - An activation function (receives ReconContext → bool)
  - An ordered list of tool tasks with priority, timeout, and args template
  - An optional list of follow-up phases to trigger if results are found
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

# Convenience type alias for ReconContext-like objects
_ReconCtx = Any
_ActivationResult = tuple[bool, str]

logger = logging.getLogger(__name__)


# ── Data Structures ────────────────────────────────────────────────────


@dataclass
class ToolTask:
    """A single tool execution within a testing phase.

    Attributes:
        tool_name: Name of the tool to run (must be registered in tool_definitions).
        description: Human-readable purpose of this tool execution.
        priority: Execution order within the phase (lower = earlier). Default 100.
        timeout: Max execution time in seconds. Default 180.
        args_template: Tool argument list with placeholder strings like ``{target}``,
                       ``{targets}``, ``{engagement_id}`` that get resolved at runtime.
        required: If True, phase failure marks this task as critical. Default False.
    """

    tool_name: str
    description: str = ""
    priority: int = 100
    timeout: int = 180
    args_template: list[str] = field(default_factory=list)
    required: bool = False


@dataclass
class TestingPhase:
    """A logical testing objective, e.g. "authentication testing".

    Attributes:
        name: Short unique identifier (e.g. ``auth_testing``).
        description: Human-readable phase description.
        activation_reason: Why this phase was activated (populated at plan time).
        order: Execution sequence across all phases (lower = earlier).
        tools: Ordered list of ToolTask instances to execute.
        triggers: Phase names to consider activating if this phase produces findings.
        depends_on: Phase names that should execute before this one.
    """

    name: str
    description: str = ""
    activation_reason: str = ""
    order: int = 100
    tools: list[ToolTask] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class WorkflowPlan:
    """An ordered testing plan generated from ReconContext signals.

    Attributes:
        phases: Ordered list of TestingPhase instances to execute.
        summary: One-line description of the plan.
        target_url: The target being tested.
        total_phases: Number of phases in the plan.
        activated_phases: Number of phases that were activated (vs. skipped).
        skipped_phases: Phase names that were evaluated but not activated, with reasons.
    """

    phases: list[TestingPhase] = field(default_factory=list)
    summary: str = ""
    target_url: str = ""
    total_phases: int = 0
    activated_phases: int = 0
    skipped_phases: list[dict[str, str]] = field(default_factory=list)


# ── Phase Definitions ──────────────────────────────────────────────────


def _has_min_recon(recon_context) -> bool:
    """Check if ReconContext is non-None and has basic data."""
    return recon_context is not None


def _get_tech_stack(recon_context) -> list[str]:
    """Safely extract tech_stack from ReconContext."""
    if recon_context and hasattr(recon_context, "tech_stack"):
        return recon_context.tech_stack or []
    return []


def _get_attr(recon_context, name: str, default=None):
    """Safely get an attribute from ReconContext."""
    if recon_context and hasattr(recon_context, name):
        return getattr(recon_context, name, default)
    return default


# ── Phase: Tech Deep Scan ──────────────────────────────────────────────


def _activate_tech_deep_scan(rc) -> tuple[bool, str]:
    """Activate when a specific tech stack is detected.

    Triggers deeper scanning for known CMS, frameworks, and servers.
    """
    tech = _get_tech_stack(rc)
    if not tech:
        return False, "no tech_stack detected"
    # Only activate for tech stacks with dedicated scanning tools
    recognized = {"wordpress", "drupal", "joomla", "apache", "nginx", "iis",
                  "php", "python", "node.js", "react", "vue", "angular",
                  "django", "flask", "express", "spring", "rails"}
    matched = [t for t in tech if t.lower() in recognized]
    if not matched:
        return False, f"no recognized technologies in stack: {tech[:5]}"
    return True, f"detected: {', '.join(matched[:5])}"


def _tech_deep_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks based on the specific tech stack detected."""
    tools: list[ToolTask] = []
    tech = _get_tech_stack(recon_context)
    tech_lower = [t.lower() for t in tech]

    # WordPress
    if any("wordpress" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="WordPress-specific vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "wordpress"],
        ))

    # Apache
    if any("apache" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="Apache-specific vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "apache"],
        ))
        if any("tomcat" in t for t in tech_lower):
            tools.append(ToolTask(
                tool_name="nuclei",
                description="Apache Tomcat vulnerability scanning",
                priority=25,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "tomcat"],
            ))

    # Nginx
    if any("nginx" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="Nginx-specific vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "nginx"],
        ))

    # JS frameworks (React, Vue, Angular) → browser scanner hint
    js_frameworks = {"react", "vue", "angular", "node.js"}
    if any(fw in tech_lower for fw in js_frameworks):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="JavaScript framework vulnerability scanning",
            priority=30,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "js,tech"],
        ))

    # PHP
    if any("php" in t for t in tech_lower):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="PHP-specific vulnerability scanning",
            priority=40,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "php,php-fpm,lfi,disclosure"],
        ))

    # Generic tech template scan
    tools.append(ToolTask(
        tool_name="nuclei",
        description="Generic technology fingerprinting and CVE scanning",
        priority=100,
        timeout=300,
        args_template=["-u", "{target}", "-jsonl", "-silent",
                       "-severity", "medium,high,critical",
                       "-tags", "tech,cve,exposure"],
    ))

    return tools


# ── Phase: Authentication Testing ──────────────────────────────────────


def _activate_auth_testing(rc) -> tuple[bool, str]:
    """Activate when a login page or auth endpoints are present."""
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    if has_login:
        return True, "login page detected"
    if auth_eps and len(auth_eps) > 0:
        return True, f"{len(auth_eps)} auth endpoint(s) found"
    return False, "no login page or auth endpoints detected"


def _auth_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for authentication testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Authentication vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "auth,login,jwt,oauth,session"],
        ),
    ]
    # JWT-specific testing if JWT keywords found
    tech = _get_tech_stack(recon_context)
    if any("jwt" in t.lower() for t in tech):
        tools.append(ToolTask(
            tool_name="jwt_tool",
            description="JWT token analysis",
            priority=20,
            timeout=120,
            args_template=["{target}", "-C", "-d"],
        ))
    # Default login testing
    tools.append(ToolTask(
        tool_name="nuclei",
        description="Default credential and brute-force testing",
        priority=30,
        timeout=300,
        args_template=["-u", "{target}", "-jsonl", "-silent",
                       "-severity", "medium,high,critical",
                       "-tags", "default-login,bruteforce"],
    ))
    return tools


# ── Phase: Session Analysis ────────────────────────────────────────────


def _activate_session_analysis(rc) -> tuple[bool, str]:
    """Activate when auth exists and session mechanisms are worth testing.

    Follows auth_testing — if the target has login or JWT, session tokens
    are worth analyzing.
    """
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_api = _get_attr(rc, "has_api", False)
    if has_login or (auth_eps and len(auth_eps) > 0):
        return True, "auth present — session tokens should be analyzed"
    if has_api:
        return True, "API present — session/token mechanisms may exist"
    return False, "no auth context detected"


def _session_analysis_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for session token analysis."""
    return [
        ToolTask(
            tool_name="jwt_tool",
            description="JWT token analysis and manipulation",
            priority=10,
            timeout=120,
            args_template=["{target}", "-C", "-d"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Session-related vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "session,cookie,csrf"],
        ),
    ]


# ── Phase: Access Control Testing ──────────────────────────────────────


def _activate_access_control(rc) -> tuple[bool, str]:
    """Activate when there are authenticated endpoints or parameter-bearing URLs.

    This tests for IDOR, privilege escalation, and broken access control.
    """
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    has_api = _get_attr(rc, "has_api", False)
    reasons = []
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")
    if has_api:
        reasons.append("API detected")
    if reasons:
        return True, "; ".join(reasons)
    return False, "no authenticated or parameterized endpoints detected"


def _access_control_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for access control testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="IDOR and broken access control scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "idor,privesc,acl,exposure"],
        ),
    ]
    param_urls = _get_attr(recon_context, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        tools.append(ToolTask(
            tool_name="arjun",
            description="Parameter discovery on IDOR-prone endpoints",
            priority=20,
            timeout=180,
            args_template=["-u", "{target}", "-m", "GET", "-t", "20"],
        ))
    return tools# ── Phase: GraphQL Introspection ────────────────────────────────────────


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

def _activate_api_scan(rc) -> tuple[bool, str]:
    """Activate when API endpoints are detected."""
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API flag detected in recon"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) discovered"
    return False, "no API endpoints detected"


def _api_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for deep API security testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="API vulnerability scanning (REST, GraphQL)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "api,graphql,swagger,openapi,rest"],
        ),
        ToolTask(
            tool_name="arjun",
            description="API parameter discovery",
            priority=20,
            timeout=180,
            args_template=["-u", "{target}", "-m", "GET", "-t", "20"],
        ),
    ]
    # XSS scanning on API endpoints
    tools.append(ToolTask(
        tool_name="dalfox",
        description="XSS scanning on API parameters",
        priority=30,
        timeout=300,
        args_template=["url", "{target}", "--json"],
    ))
    return tools


# ── Phase: Input Validation Testing ────────────────────────────────────


def _activate_input_validation(rc) -> tuple[bool, str]:
    """Activate when parameter-bearing URLs are present.

    Tests for XSS, SQLi, SSTI, and other injection vulnerabilities
    on discovered parameters.
    """
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) found"
    return False, "no parameter-bearing URLs detected"


def _input_validation_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for input validation and injection testing."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="dalfox",
            description="XSS scanning on input parameters",
            priority=10,
            timeout=300,
            args_template=["url", "{target}", "--json"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Injection vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "injection,sqli,lfi,ssrf,ssti"],
        ),
    ]
    return tools# ── Phase: SSRF Testing ────────────────────────────────────────────────


def _activate_ssrf_testing(rc) -> tuple[bool, str]:
    """Activate when SSRF-prone patterns are detected in recon.

    Server-Side Request Forgery (SSRF) allows an attacker to make the
    server send requests to internal or external resources. Activates when:
      - ``has_ssrf`` flag is set on ReconContext (forward-compatible)
      - ``ssrf_signals`` list is populated
      - Parameter-bearing URLs are present (SSRF often uses URL params)
      - File upload detected (SSRF via uploaded file URLs)
      - Tech stack includes HTTP client libraries (curl, guzzle, requests)
    """
    # Forward-compatible: check for dedicated SSRF attribute
    has_ssrf = _get_attr(rc, "has_ssrf", False)
    if has_ssrf:
        return True, "SSRF signals detected in recon"

    ssrf_signals = _get_attr(rc, "ssrf_signals", [])
    if ssrf_signals and len(ssrf_signals) > 0:
        return True, f"{len(ssrf_signals)} SSRF indicator(s) found"

    # Check tech_stack for SSRF-prone technologies
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        ssrf_keywords = {"ssrf", "curl", "guzzle", "requests", "httpx",
                         "file_get_contents", "allow_url_fopen",
                         "fetch", "axios", "httpclient", "webclient"}
        matched = [kw for kw in ssrf_keywords if kw in tech_lower]
        if matched:
            return True, f"SSRF-relevant tech detected: {', '.join(matched)}"

    # Parameter-bearing URLs are a common SSRF vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — SSRF vector potential"

    # File upload can involve SSRF via URL-based file sources
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload present — SSRF via URL-based file sources"

    return False, "no SSRF signals detected"


def _ssrf_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for SSRF vulnerability testing.

    Tests for:
      - Blind SSRF via parameter injection
      - Timeout-based SSRF detection
      - Cloud metadata endpoint probing via SSRF
      - Internal network scanning via SSRF
      - URL-based file inclusion SSRF
      - DNS-based SSRF out-of-band detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="SSRF vulnerability scanning (blind, time-based, OOB)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssrf,blind-oob,oast,http-injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Internal network probing via SSRF (metadata, internal services)",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssrf,internal,metadata,network"],
        ),
    ]
    return tools


# ── Phase: Infrastructure Testing ──────────────────────────────────────

def _activate_infrastructure(rc) -> tuple[bool, str]:
    """Activate when open ports or web servers are detected beyond standard web ports."""
    ports = _get_attr(rc, "open_ports", [])
    if not ports:
        return False, "no open ports data"
    # Check for non-standard ports (beyond 80, 443, 8080)
    standard = {80, 443, 8080, 8443}
    non_standard = [p for p in ports if p.get("port", 0) not in standard] if ports else []
    if non_standard:
        return True, f"{len(non_standard)} non-standard port(s) detected"
    return True, f"{len(ports)} open port(s) — running infrastructure checks"


def _infrastructure_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for infrastructure scanning."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Infrastructure and network vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "network,misconfig,exposure"],
        ),
    ]
    # TLS testing if HTTPS
    target = _get_attr(recon_context, "target_url", "")
    if target and target.startswith("https"):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="TLS/SSL vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssl,tls,ssl-tls"],
        ))
    return tools


# ── Phase: File Upload Testing ─────────────────────────────────────────


def _activate_file_upload(rc) -> tuple[bool, str]:
    """Activate when file upload functionality is detected."""
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload functionality detected"
    return False, "no file upload detected"


def _file_upload_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for file upload abuse testing."""
    return [
        ToolTask(
            tool_name="nuclei",
            description="File upload vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "file-upload,upload"],
        ),
    ]


# ── Phase: CORS Origin Testing ────────────────────────────────────────────


def _activate_cors_testing(rc) -> tuple[bool, str]:
    """Activate when CORS-related signals are detected in recon.

    CORS (Cross-Origin Resource Sharing) misconfigurations can allow
    unauthorized cross-origin data access. Activates when:
      - ``has_cors`` flag is set on ReconContext (forward-compatible)
      - CORS header keywords appear in tech_stack
      - API endpoints are present (CORS is primarily an API concern)
    """
    # Forward-compatible: check for dedicated CORS attribute
    has_cors = _get_attr(rc, "has_cors", False)
    if has_cors:
        return True, "CORS headers detected in recon"

    cors_headers = _get_attr(rc, "cors_headers", [])
    if cors_headers and len(cors_headers) > 0:
        return True, f"{len(cors_headers)} CORS header(s) found"

    # Check tech_stack for CORS-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        cors_keywords = {"cors", "access-control", "rest", "restful",
                         "graphql", "api gateway", "openapi"}
        matched = [kw for kw in cors_keywords if kw in tech_lower]
        if matched:
            return True, f"CORS-relevant tech detected: {', '.join(matched)}"

    # API endpoints often involve CORS
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — CORS configuration should be verified"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — CORS misconfig likely"

    return False, "no CORS signals detected"


def _cors_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for CORS origin testing.

    Tests for:
      - Wildcard origin credentials misconfiguration
      - Reflected origin reflection (trusted origins list bypass)
      - Preflight request validation weaknesses
      - CORS-header injection via null/arbitrary origins
      - Cross-origin data leakage via ACAO + ACC headers
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="CORS misconfiguration scanning (wildcard, origin reflection, preflight)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cors,headers,misconfig,exposure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cross-origin data leakage and CORS bypass scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cors,origin,access-control,leak"],
        ),
    ]


# ── Phase: Rate Limit Testing ────────────────────────────────────────────


def _activate_rate_limit_testing(rc) -> tuple[bool, str]:
    """Activate when rate-limit-able endpoints are detected.

    Rate limiting is a critical defense against brute-force attacks,
    credential stuffing, and API abuse. Activates when:
      - Auth endpoints exist (login, password reset, MFA)
      - API endpoints are present
      - Login page detected
    """
    has_login = _get_attr(rc, "has_login_page", False)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])

    reasons = []
    if has_login:
        reasons.append("login page detected")
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_api:
        reasons.append("API present")
    if api_eps and len(api_eps) > 0:
        reasons.append(f"{len(api_eps)} API endpoint(s)")

    if reasons:
        return True, "; ".join(reasons)
    return False, "no rate-limit-able endpoints detected"


def _rate_limit_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for rate limit testing.

    Probes for:
      - Login endpoint rate limiting (brute-force protection)
      - Password reset rate limiting
      - API endpoint rate limiting
      - Registration/MFA endpoint rate limiting
      - IP-based vs user-based rate limiting detection
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="Rate limit and brute-force protection scanning (login, password reset)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "rate-limit,bruteforce,excessive"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="API rate limiting and abuse detection",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "api,rate,limit,abuse,exhaustion"],
        ),
    ]


# ── Phase: WebSocket Testing ────────────────────────────────────────────


def _activate_websocket_testing(rc) -> tuple[bool, str]:
    """Activate when WebSocket endpoints or signals are detected in recon.

    WebSocket connections bypass standard HTTP security controls
    (CORS, CSRF tokens, same-origin policy) and require dedicated
    testing for:
      - Origin validation bypass
      - Authentication weaknesses
      - Message injection (SQLi, NoSQLi, command injection)
      - Rate limiting absence
      - Cross-site WebSocket hijacking (CSWSH)

    Activates when:
      - ``has_websocket`` flag is set on ReconContext (forward-compatible)
      - ``websocket_endpoints`` list is populated
      - WebSocket-related keywords appear in tech_stack
      - API endpoints are present (WS often accompanies REST APIs)
    """
    # Forward-compatible: check for dedicated WebSocket attribute
    has_ws = _get_attr(rc, "has_websocket", False)
    if has_ws:
        return True, "WebSocket endpoints detected in recon"

    ws_endpoints = _get_attr(rc, "websocket_endpoints", [])
    if ws_endpoints and len(ws_endpoints) > 0:
        return True, f"{len(ws_endpoints)} WebSocket endpoint(s) found"

    # Check tech_stack for WebSocket-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        ws_keywords = {"websocket", "socket.io", "socketio", "socket-io",
                       "ws://", "wss://", "signalr", "actioncable",
                       "laravel-websockets", "django channels", "flask-socketio"}
        matched = [kw for kw in ws_keywords if kw in tech_lower]
        if matched:
            return True, f"WebSocket-relevant tech detected: {', '.join(matched)}"

    # API endpoints often accompany WebSocket connections
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — WebSocket connections may be present"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — WebSocket testing recommended"

    return False, "no WebSocket signals detected"


def _websocket_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for WebSocket security testing.

    Tests for:
      - Origin validation bypass (CSWSH)
      - Authentication weaknesses on WS upgrade
      - Message-level injection (SQLi, NoSQLi, command injection)
      - Rate limiting absence on WS messages
      - Sensitive data exposure via WS
      - WebSocket URL discovery via page crawling
    """
    return [
        ToolTask(
            tool_name="nuclei",
            description="WebSocket origin validation and CSWSH scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "websocket,ws,origin,cswsh,hijack"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="WebSocket authentication and injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "websocket,auth,injection,exposure"],
        ),
    ]


# ── Phase: Cloud Metadata Probe ────────────────────────────────────────────

# Cloud provider keywords for matching against tech_stack
_CLOUD_PROVIDERS: dict[str, set[str]] = {
    "AWS": {"aws", "amazon web services", "amazon", "ec2", "s3", "lambda",
             "cloudfront", "route53", "elb", "ecs", "eks", "rds"},
    "GCP": {"gcp", "google cloud", "google cloud platform", "gke",
             "cloud run", "app engine", "bigquery", "cloud storage"},
    "Azure": {"azure", "microsoft azure", "azure vm", "azure functions",
               "azure storage", "aks", "azure ad"},
}


def _activate_cloud_metadata(rc) -> tuple[bool, str]:
    """Activate when tech_stack suggests cloud infrastructure.

    Cloud-provisioned targets often expose metadata services
    (IMDS, GCP metadata, Azure IMDS) that can leak credentials
    or instance metadata via SSRF or misconfiguration.
    """
    tech = _get_tech_stack(rc)
    if not tech:
        return False, "no tech_stack detected"

    tech_lower = " ".join(t.lower() for t in tech)

    matched_providers: list[str] = []
    for provider, keywords in _CLOUD_PROVIDERS.items():
        if any(kw in tech_lower for kw in keywords):
            matched_providers.append(provider)

    if not matched_providers:
        return False, "no cloud provider keywords in tech stack"

    return True, f"cloud infrastructure detected: {', '.join(matched_providers)}"


def _cloud_metadata_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for cloud metadata probing.

    Probes for:
      - AWS IMDS (169.254.169.254/latest/meta-data/)
      - GCP metadata endpoint (metadata.google.internal)
      - Azure IMDS (169.254.169.254/metadata/instance)
      - Cloud storage bucket discovery (S3, GCS, Azure Blob)
      - Cloud credential exposure via nuclei templates
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Cloud metadata service probing (IMDS, GCP, Azure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cloud,metadata,imds,ssrf"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cloud storage bucket discovery and misconfiguration",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "s3,bucket,storage,cloud-storage"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Cloud credential and key exposure scanning",
            priority=30,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "keys,credentials,tokens,secrets"],
        ),
    ]
    return tools


# ── Phase Registry ─────────────────────────────────────────────────────


@dataclass
class _PhaseDefinition:
    """Internal phase definition linking activation logic to tool builders.

    Attributes:
        name: Phase identifier.
        description: Human-readable description.
        order: Global execution order (lower = earlier).
        activate_fn: Callable(ReconContext) → (bool, reason_string).
        tools_fn: Callable(ReconContext) → list[ToolTask].
        triggers: Phase names to flag for follow-up.
        depends_on: Phase names that must execute first.
    """
    name: str
    description: str
    order: int
    activate_fn: Callable[[_ReconCtx], _ActivationResult]
    tools_fn: Callable[[_ReconCtx], list[ToolTask]]
    triggers: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


PHASE_DEFINITIONS: list[_PhaseDefinition] = [
    _PhaseDefinition(
        name="tech_deep_scan",
        description="Technology-specific deep scanning (CMS, frameworks, servers)",
        order=10,
        activate_fn=_activate_tech_deep_scan,
        tools_fn=_tech_deep_scan_tools,
        triggers=["auth_testing", "api_scan"],
    ),
    _PhaseDefinition(
        name="auth_testing",
        description="Authentication mechanism analysis (login, JWT, OAuth)",
        order=20,
        activate_fn=_activate_auth_testing,
        tools_fn=_auth_testing_tools,
        triggers=["session_analysis", "access_control"],
        depends_on=["tech_deep_scan"],
    ),
    _PhaseDefinition(
        name="session_analysis",
        description="Session token and cookie analysis (JWT, CSRF)",
        order=30,
        activate_fn=_activate_session_analysis,
        tools_fn=_session_analysis_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="access_control",
        description="Authorization and privilege testing (IDOR, privesc)",
        order=40,
        activate_fn=_activate_access_control,
        tools_fn=_access_control_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="graphql_introspection",
        description="GraphQL introspection and schema exposure testing (introspection query, schema dump, playground)",
        order=48,
        activate_fn=_activate_graphql_introspection,
        tools_fn=_graphql_introspection_tools,
        triggers=["access_control", "input_validation"],
    ),
    _PhaseDefinition(
        name="api_scan",
        description="Deep API security testing (REST, GraphQL)",
        order=50,
        activate_fn=_activate_api_scan,
        tools_fn=_api_scan_tools,
        triggers=["access_control", "input_validation", "cors_origin_testing", "websocket_testing", "graphql_introspection"],
    ),
    _PhaseDefinition(
        name="websocket_testing",
        description="WebSocket security testing (origin validation, auth bypass, injection, CSWSH)",
        order=52,
        activate_fn=_activate_websocket_testing,
        tools_fn=_websocket_testing_tools,
        depends_on=["api_scan"],
        triggers=["access_control", "input_validation"],
    ),
    _PhaseDefinition(
        name="cors_origin_testing",
        description="CORS origin misconfiguration testing (wildcard, origin reflection, preflight bypass)",
        order=55,
        activate_fn=_activate_cors_testing,
        tools_fn=_cors_testing_tools,
        depends_on=["api_scan"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="rate_limit_testing",
        description="Rate limiting and brute-force protection analysis (login, API, password reset)",
        order=45,
        activate_fn=_activate_rate_limit_testing,
        tools_fn=_rate_limit_testing_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="input_validation",
        description="Input validation and injection testing (XSS, SQLi, SSTI)",
        order=60,
        activate_fn=_activate_input_validation,
        tools_fn=_input_validation_tools,
        triggers=["ssrf_testing"],
    ),
    _PhaseDefinition(
        name="ssrf_testing",
        description="Server-Side Request Forgery testing (blind, time-based, OOB, internal metadata)",
        order=65,
        activate_fn=_activate_ssrf_testing,
        tools_fn=_ssrf_testing_tools,
        depends_on=["input_validation"],
        triggers=["cloud_metadata_probe"],
    ),
    _PhaseDefinition(
        name="infrastructure_scan",
        description="Infrastructure and service fingerprinting (ports, TLS)",
        order=70,
        activate_fn=_activate_infrastructure,
        tools_fn=_infrastructure_tools,
    ),
    _PhaseDefinition(
        name="cloud_metadata_probe",
        description="Cloud metadata service probing (IMDS, cloud storage misconfig)",
        order=75,
        activate_fn=_activate_cloud_metadata,
        tools_fn=_cloud_metadata_tools,
        depends_on=["infrastructure_scan"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="file_upload_scan",
        description="File upload abuse testing (unrestricted upload, path traversal)",
        order=80,
        activate_fn=_activate_file_upload,
        tools_fn=_file_upload_tools,
    ),
]


# ── Planner ────────────────────────────────────────────────────────────


class AdaptiveWorkflowPlanner:
    """Generates an ordered, signal-driven testing plan from ReconContext.

    The planner evaluates each phase definition against the recon signals,
    resolves inter-phase dependencies, and produces a WorkflowPlan with
    phases ordered for logical execution.

    Usage::

        planner = AdaptiveWorkflowPlanner()
        plan = planner.build_plan(recon_context, engagement_id="eng-123")
        for phase in plan.phases:
            print(f"{phase.activation_reason}")
            for task in phase.tools:
                print(f"  → {task.tool_name}")
    """

    def __init__(self, phase_definitions: list[_PhaseDefinition] | None = None):
        """Initialize the planner with an optional custom phase registry.

        Args:
            phase_definitions: Custom phase definitions. Defaults to PHASE_DEFINITIONS.
        """
        self.phase_defs = phase_definitions or PHASE_DEFINITIONS
        self._last_recon_context: Any = {}  # Updated to actual context on build_plan()

    def build_plan(
        self,
        recon_context: Any,
        engagement_id: str = "",
    ) -> WorkflowPlan:
        """Build a WorkflowPlan from ReconContext signals.

        Evaluates each phase definition, activates those whose preconditions
        are met, resolves inter-phase dependencies, and returns an ordered plan.

        Args:
            recon_context: ReconContext instance from the recon phase.
            engagement_id: Optional engagement ID for logging.

        Returns:
            WorkflowPlan with ordered, activated phases.
        """
        target_url = _get_attr(recon_context, "target_url", "")

        if not _has_min_recon(recon_context):
            logger.info(
                "[AdaptivePlanner] No recon context — returning empty plan "
                "(engagement=%s)",
                engagement_id,
            )
            return WorkflowPlan(
                summary="No recon context available — skipping adaptive planning",
                target_url=target_url,
            )

        self._last_recon_context = recon_context

        # ── Step 1: Evaluate all phase definitions ──
        activated: list[TestingPhase] = []
        skipped: list[dict[str, str]] = []
        all_names: set[str] = {p.name for p in self.phase_defs}

        for phase_def in self.phase_defs:
            should_activate, reason = phase_def.activate_fn(recon_context)
            if should_activate:
                tools = phase_def.tools_fn(recon_context)
                # Resolve triggers — only keep triggers that are valid phase names
                valid_triggers = [t for t in phase_def.triggers if t in all_names]
                # Resolve depends_on — only keep valid phase names
                valid_deps = [d for d in phase_def.depends_on if d in all_names]
                phase = TestingPhase(
                    name=phase_def.name,
                    description=phase_def.description,
                    activation_reason=reason,
                    order=phase_def.order,
                    tools=tools,
                    triggers=valid_triggers,
                    depends_on=valid_deps,
                )
                activated.append(phase)
                logger.info(
                    "[AdaptivePlanner] Activated phase '%s' (%s) — %s "
                    "(engagement=%s)",
                    phase_def.name,
                    phase_def.description,
                    reason,
                    engagement_id,
                )
            else:
                skipped.append({"phase": phase_def.name, "reason": reason})
                logger.debug(
                    "[AdaptivePlanner] Skipped phase '%s': %s (engagement=%s)",
                    phase_def.name,
                    reason,
                    engagement_id,
                )

        # ── Step 2: Resolve depends_on — reorder so dependencies come first ──
        ordered = self._order_phases(activated)

        # ── Step 3: Build summary ──
        total_phases = len(self.phase_defs)
        activated_names = [p.name for p in ordered]
        summary_parts = [f"phases: {', '.join(activated_names)}"] if ordered else ["no phases activated"]

        plan = WorkflowPlan(
            phases=ordered,
            summary="; ".join(summary_parts),
            target_url=target_url,
            total_phases=total_phases,
            activated_phases=len(ordered),
            skipped_phases=skipped,
        )

        logger.info(
            "[AdaptivePlanner] Plan complete: %d/%d phases activated "
            "(engagement=%s, target=%s)",
            len(ordered),
            total_phases,
            engagement_id,
            target_url,
        )
        return plan

    @staticmethod
    def _order_phases(phases: list[TestingPhase]) -> list[TestingPhase]:
        """Order phases respecting dependencies, using a simple topological sort.

        Args:
            phases: List of activated phases (potentially unsorted).

        Returns:
            Phases ordered so that dependencies come before dependents,
            and phases with lower order numbers come first within the same
            dependency level.
        """
        if not phases:
            return []

        # Build dependency graph
        phase_map = {p.name: p for p in phases}
        name_set = set(phase_map.keys())

        # Topological sort (Kahn's algorithm)
        in_degree: dict[str, int] = {p.name: 0 for p in phases}
        dependents: dict[str, list[str]] = {p.name: [] for p in phases}

        for p in phases:
            for dep in p.depends_on:
                if dep in name_set:
                    in_degree[p.name] = in_degree.get(p.name, 0) + 1
                    if dep not in dependents:
                        dependents[dep] = []
                    dependents[dep].append(p.name)

        # Start with phases that have no unmet dependencies, sorted by order
        ready = sorted(
            [p for p in phases if in_degree.get(p.name, 0) == 0],
            key=lambda p: p.order,
        )

        ordered: list[TestingPhase] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for dep_name in dependents.get(current.name, []):
                in_degree[dep_name] -= 1
                if in_degree[dep_name] == 0:
                    dep_phase = phase_map.get(dep_name)
                    if dep_phase:
                        # Insert in sorted position by order
                        ready.append(dep_phase)
                        ready.sort(key=lambda p: p.order)

        # Add any remaining phases that weren't ordered (cycles or missing deps)
        remaining = [p for p in phases if p not in ordered]
        ordered.extend(sorted(remaining, key=lambda p: p.order))

        return ordered

    def format_plan_for_agent(self, plan: WorkflowPlan) -> str:
        """Format the plan as a compact text block for LLM agent consumption.

        The formatted plan is injected into the agent's system prompt so the
        LLM knows which testing phases are recommended and why.

        Args:
            plan: The WorkflowPlan to format.

        Returns:
            Compact multi-line string suitable for inclusion in an LLM prompt.
        """
        if not plan or not plan.phases:
            return ""

        lines = [
            "=== ADAPTIVE TESTING PLAN ===",
            f"Target: {plan.target_url}",
            f"Phases: {plan.activated_phases}/{plan.total_phases} activated",
            "",
        ]
        for i, phase in enumerate(plan.phases, 1):
            lines.append(f"  Phase {i}: {phase.name}")
            lines.append(f"    {phase.description}")
            lines.append(f"    Reason: {phase.activation_reason}")
            for task in phase.tools:
                lines.append(f"    Tool: {task.tool_name} — {task.description}")
            if phase.triggers:
                lines.append(f"    Follow-up: {', '.join(phase.triggers)}")
            lines.append("")
        lines.append("=== END TESTING PLAN ===")
        return "\n".join(lines)

    @staticmethod
    def resolve_tool_args(
        task: ToolTask,
        target: str,
        engagement_id: str = "",
    ) -> list[str]:
        """Resolve placeholder strings in a ToolTask's args_template.

        Supported placeholders:
          - ``{target}`` — the target URL
          - ``{targets}`` — comma-separated targets (same as target for single-target)
          - ``{engagement_id}`` — the engagement UUID

        Args:
            task: The ToolTask whose args_template to resolve.
            target: The target URL to substitute.
            engagement_id: The engagement ID to substitute.

        Returns:
            Resolved argument list ready for tool execution.
        """
        return [
            arg.replace("{target}", target)
               .replace("{targets}", target)
               .replace("{engagement_id}", engagement_id)
            for arg in task.args_template
        ]

    def update_plan_from_results(
        self,
        plan: WorkflowPlan,
        completed_phase_name: str,
        findings: list[dict],
    ) -> WorkflowPlan:
        """Update a plan based on findings from a completed phase.

        If a completed phase produced findings, its ``triggers`` phases are
        activated (added to the plan if not already there) with their tools
        populated from the original phase definitions. This enables dynamic
        phase chaining based on actual results rather than just initial
        recon signals.

        Args:
            plan: The current WorkflowPlan to update.
            completed_phase_name: Name of the phase that just completed.
            findings: Findings produced by the completed phase.

        Returns:
            Updated WorkflowPlan with any newly triggered phases added.
        """
        if not findings:
            return plan  # No results -> no trigger activation

        completed = next(
            (p for p in plan.phases if p.name == completed_phase_name),
            None,
        )
        if not completed or not completed.triggers:
            return plan

        # Build lookup from original phase definitions for tool generation
        def_map = {p.name: p for p in self.phase_defs}
        existing_names = {p.name for p in plan.phases}
        new_phases: list[TestingPhase] = []

        # Create properly populated triggered phases
        for trigger_name in completed.triggers:
            if trigger_name not in existing_names:
                phase_def = def_map.get(trigger_name)
                if phase_def is None:
                    logger.warning(
                        "[AdaptivePlanner] Trigger '%s' not found in phase definitions",
                        trigger_name,
                    )
                    continue

                # Call tools_fn with the original recon_context stored on plan
                tools = phase_def.tools_fn(self._last_recon_context) if self._last_recon_context else []

                triggered = TestingPhase(
                    name=trigger_name,
                    description=f"Follow-up from {completed_phase_name} (triggered by findings)",
                    activation_reason=f"triggered by findings in '{completed_phase_name}'",
                    order=completed.order + 5,
                    tools=tools,
                    depends_on=[completed_phase_name],
                )
                new_phases.append(triggered)
                logger.info(
                    "[AdaptivePlanner] Dynamic trigger: phase '%s' activated "
                    "by findings from '%s' (%d tools)",
                    trigger_name,
                    completed_phase_name,
                    len(tools),
                )

        if new_phases:
            plan.phases.extend(new_phases)
            plan.activated_phases = len(plan.phases)
            plan.phases = self._order_phases(plan.phases)
            plan.summary += f"; triggered: {', '.join(p.name for p in new_phases)}"

        return plan

    @staticmethod
    def deduplicate_tools(plan: WorkflowPlan) -> WorkflowPlan:
        """Deduplicate tool+tag combinations across phases within a plan.

        If two phases both recommend running the same tool with overlapping
        nuclei tags, merge them to avoid redundant execution.

        Args:
            plan: The WorkflowPlan to deduplicate.

        Returns:
            Plan with duplicate tool+target combinations removed.
            The highest-priority occurrence is kept.
        """
        if not plan.phases:
            return plan

        seen_tasks: dict[str, ToolTask] = {}  # key = "tool_name:tags_string"
        deduped_phases: list[TestingPhase] = []

        for phase in plan.phases:
            deduped_tools: list[ToolTask] = []
            for task in phase.tools:
                # Build a dedup key: tool_name + canonical args
                tags_arg = next(
                    (task.args_template[i + 1]
                     for i, a in enumerate(task.args_template)
                     if a == "-tags" and i + 1 < len(task.args_template)),
                    "",
                )
                dedup_key = f"{task.tool_name}:{tags_arg}"

                if dedup_key not in seen_tasks:
                    seen_tasks[dedup_key] = task
                    deduped_tools.append(task)
            phase.tools = deduped_tools
            deduped_phases.append(phase)

        plan.phases = deduped_phases
        return plan

    def get_plan_summary(self, plan: WorkflowPlan) -> dict:
        """Return a JSON-serializable summary of the plan for metrics/observability.

        Args:
            plan: The WorkflowPlan to summarize.

        Returns:
            Dict with plan metadata.
        """
        return {
            "target_url": plan.target_url,
            "total_phases": plan.total_phases,
            "activated_phases": plan.activated_phases,
            "phases": [
                {
                    "name": p.name,
                    "order": p.order,
                    "reason": p.activation_reason,
                    "tools": [t.tool_name for t in p.tools],
                    "triggers": p.triggers,
                }
                for p in plan.phases
            ],
            "skipped": plan.skipped_phases,
            "summary": plan.summary,
        }
