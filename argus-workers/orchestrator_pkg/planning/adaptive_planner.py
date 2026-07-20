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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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

    def get_coverage_report(self) -> dict:
        """Return a structured coverage report comparing planned vs executed phases.

        Shows which phases were activated, which were skipped (with reasons),
        and what percentage of the potential attack surface was covered.

        Returns:
            Dict with coverage_gaps (list of skipped phases), activated (list of
            active phases), activated_count, skipped_count, total_phases, and
            coverage_pct (float 0.0-1.0).
        """
        if not self.phases and not self.skipped_phases:
            return {
                "coverage_gaps": [],
                "activated": [],
                "activated_count": 0,
                "skipped_count": 0,
                "total_phases": self.total_phases,
                "coverage_pct": 0.0,
                "summary": self.summary,
            }
        activated_names = [p.name for p in self.phases]
        skipped_info = [
            {"name": s.get("name", "unknown"), "reason": s.get("reason", "")}
            for s in self.skipped_phases
        ]
        evaluable = self.total_phases or (len(self.phases) + len(self.skipped_phases))
        coverage_pct = self.activated_phases / max(evaluable, 1)
        return {
            "coverage_gaps": skipped_info,
            "activated": activated_names,
            "activated_count": self.activated_phases,
            "skipped_count": len(self.skipped_phases),
            "total_phases": evaluable,
            "coverage_pct": round(coverage_pct, 3),
            "summary": self.summary,
        }

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
    return tools# ── Phase: Template Injection (SSTI) Testing ──────────────────────────

# Recognized templating engines and their framework/language associations
_TEMPLATE_ENGINES: set[str] = {
    # Python
    "jinja", "jinja2", "mako", "tornado", "django template",
    # PHP
    "twig", "smarty", "blade", "latte", "plates",
    # JavaScript / TypeScript
    "pug", "jade", "handlebars", "mustache", "ejs",
    "nunjucks", "liquid", "eta", "hogan.js",
    # Ruby
    "erb", "haml", "slim",
    # Java
    "velocity", "freemarker", "thymeleaf", "jsp",
    "apache tiles", "groovy template",
    # Go
    "go template", "html/template",
    # .NET
    "razor", "dotliquid",
}


def _activate_template_injection(rc) -> tuple[bool, str]:
    """Activate when recognized templating engines are detected in tech_stack.

    Server-Side Template Injection (SSTI) occurs when user input is
    embedded in template expressions without proper sanitization.
    Impact ranges from information disclosure to remote code execution
    depending on the template engine.

    Activates when:
      - ``has_template_injection`` flag is set (forward-compatible)
      - ``template_engines`` list is populated (forward-compatible)
      - Known templating engines appear in tech_stack
      - Parameter-bearing URLs are present (SSTI vector)
    """
    # Forward-compatible: check for dedicated SSTI attribute
    has_ssti = _get_attr(rc, "has_template_injection", False)
    if has_ssti:
        return True, "template injection signals detected in recon"

    tpl_engines = _get_attr(rc, "template_engines", [])
    if tpl_engines and len(tpl_engines) > 0:
        return True, f"{len(tpl_engines)} template engine(s) detected: {', '.join(tpl_engines[:3])}"

    # Check tech_stack for known templating engines
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [eng for eng in _TEMPLATE_ENGINES if eng in tech_lower]
        if matched:
            return True, f"templating engine detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs can be SSTI vectors
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential SSTI vector"

    return False, "no templating engines or SSTI signals detected"


def _template_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for server-side template injection testing.

    Tests for SSTI in:
      - Jinja2 / Django (Python) — {{ }} syntax
      - Twig / Smarty / Blade (PHP) — {{ }} / {$ } syntax
      - Pug / Handlebars / EJS (JS) — #{ } / {{ }} syntax
      - Velocity / FreeMarker (Java) — ${{ }} / ${ } syntax
      - ERB / HAML (Ruby) — <%= %> syntax
      - Generic template syntax detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Server-Side Template Injection scanning (multi-engine)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssti,template-injection,injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="SSTI polyglot detection and engine-specific probes",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssti,tech,rce,exposure"],
        ),
    ]
    return tools


# ── Phase: Deserialization Testing ────────────────────────────────────

# Recognized deserialization libraries/frameworks by language
_DESERIALIZATION_LIBS: set[str] = {
    # Python
    "pickle", "yaml", "pyyaml", "ruamel.yaml", "jsonpickle",
    "cPickle", "dill", "cloudpickle", "shelve",
    # Java
    "xstream", "jackson", "fastjson", "jboss", "weblogic",
    "hessian", "kryo", "snakeyaml", "jodd", "json-io",
    "flexjson", "genson", "logback", "jndi",
    # PHP
    "php unserialize", "php serialization", "phpobject",
    # Ruby
    "ruby marshal", "oj.load", "ruby yaml load",
    # .NET
    "binaryformatter", "soapformatter", "losformatter",
    "datacontractserializer", "javascriptserializer",
    "netdatacontractserializer", "jsonnet",
    # Node.js / JavaScript
    "node-serialize", "serialize-javascript", "funcster",
    "node serialize", "javascript serialize",
}


def _activate_deserialization_testing(rc) -> tuple[bool, str]:
    """Activate when insecure deserialization libraries are detected.

    Insecure deserialization can lead to remote code execution (RCE),
    authentication bypass, and privilege escalation. The risk exists
    across all major languages that handle serialized data.

    Activates when:
      - ``has_deserialization`` flag is set (forward-compatible)
      - ``deserialization_libs`` list is populated (forward-compatible)
      - Known deserialization libraries appear in tech_stack
      - API endpoints are present (deserialization is common in APIs)
      - Parameter-bearing URLs are present (deserialization vector)
    """
    # Forward-compatible: check for dedicated deserialization attribute
    has_deser = _get_attr(rc, "has_deserialization", False)
    if has_deser:
        return True, "insecure deserialization signals detected in recon"

    deser_libs = _get_attr(rc, "deserialization_libs", [])
    if deser_libs and len(deser_libs) > 0:
        return True, f"{len(deser_libs)} deserialization library(ies) found: {', '.join(deser_libs[:3])}"

    # Check tech_stack for known deserialization libraries
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [lib for lib in _DESERIALIZATION_LIBS if lib in tech_lower]
        if matched:
            return True, f"deserialization library detected: {', '.join(matched[:3])}"

    # Deserialization is common via API request bodies
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — deserialization attack surface present"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — deserialization testing recommended"

    # Parameter-bearing URLs can carry serialized data
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential deserialization vector"

    return False, "no deserialization signals detected"


def _deserialization_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for insecure deserialization testing.

    Tests for deserialization vulnerabilities in:
      - Java: Jackson, Fastjson, XStream, JNDI injection via log4j
      - Python: Pickle, PyYAML, JSON Pickle
      - PHP: PHP object injection via unserialize()
      - .NET: BinaryFormatter, SoapFormatter, LosFormatter
      - Node.js: node-serialize, serialize-javascript
      - Ruby: Marshal.load, YAML.load
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Insecure deserialization scanning (Java, Python, PHP, .NET)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "deserialization,rce,oob,injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="JNDI injection and log4shell detection (deserialization vector)",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "jndi,log4shell,log4j,rce,oast"],
        ),
    ]
    return tools


# ── Phase: SSRF Testing ────────────────────────────────────────────────

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


# ── Phase: CSRF Testing ───────────────────────────────────────────────────


def _activate_csrf_testing(rc) -> tuple[bool, str]:
    """Activate when form endpoints or session-based auth are detected.

    Cross-Site Request Forgery (CSRF) occurs when an attacker tricks a
    user's browser into executing unwanted actions on an authenticated
    session. Any state-changing operation (POST, PUT, DELETE) without
    anti-CSRF tokens is potentially vulnerable.

    Activates when:
      - ``has_csrf`` flag is set on ReconContext (forward-compatible)
      - ``form_endpoints`` list is populated (forward-compatible)
      - Auth endpoints are present (login, registration, password reset)
      - Login page is detected
      - API endpoints are present (CSRF on APIs)
      - Session-related keywords appear in tech_stack
      - Form submissions detected in crawled paths
    """
    # Forward-compatible: check for dedicated CSRF attribute
    has_csrf = _get_attr(rc, "has_csrf", False)
    if has_csrf:
        return True, "CSRF signals detected in recon"

    form_eps = _get_attr(rc, "form_endpoints", [])
    if form_eps and len(form_eps) > 0:
        return True, f"{len(form_eps)} form endpoint(s) found"

    reasons = []

    # Auth endpoints are CSRF-prone (login, password reset, etc.)
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_login = _get_attr(rc, "has_login_page", False)
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_login:
        reasons.append("login page")

    # API endpoints can be vulnerable to CSRF
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        reasons.append("API detected")
    if api_eps and len(api_eps) > 0:
        reasons.append(f"{len(api_eps)} API endpoint(s)")

    # Check tech_stack for session/auth-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        csrf_keywords = {"csrf", "csrf token", "session", "cookie",
                         "auth token", "jwt", "antiforgery",
                         "antiforgerytoken", "x-csrf-token",
                         "__requestverificationtoken"}
        matched = [kw for kw in csrf_keywords if kw in tech_lower]
        if matched:
            reasons.append(f"security tech: {', '.join(matched[:2])}")

    if reasons:
        return True, "; ".join(reasons[:3])

    return False, "no form endpoints or session-based auth detected"


def _csrf_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for CSRF vulnerability testing.

    Tests for:
      - Missing CSRF tokens on state-changing endpoints (POST, PUT, DELETE)
      - Weak/guessable CSRF token generation
      - CSRF token validation bypass (referer, origin, custom header)
      - CSRF on JSON endpoints (content-type switching)
      - SameSite cookie bypass for CSRF
      - Anti-CSRF token reuse/replay
      - Anti-CSRF token leakage via referer/response headers
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="CSRF vulnerability scanning (missing tokens, weak validation, SameSite bypass)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "csrf,samesite,cookie,exposure,bypass"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="CSRF token analysis and anti-forgery protection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "csrf,bypass,antiforgery,header,referer"],
        ),
    ]
    return tools


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


# ── Phase: Open Redirect Testing ────────────────────────────────────────────

# Redirect parameter patterns commonly found in URL parameters
_REDIRECT_PARAM_PATTERNS: set[str] = {
    "redirect", "redirect_url", "redirect_uri", "redirect_to",
    "url", "uri", "u", "next", "next_url", "return",
    "return_to", "return_url", "return_uri", "goto",
    "dest", "destination", "target", "continue",
    "continue_url", "forward", "forward_url",
    "href", "ref", "referrer", "link", "out",
    "view", "load", "file", "page", "document",
}


def _has_redirect_params(param_urls: list[str]) -> bool:
    """Check if any parameter-bearing URL contains redirect-like parameters.

    Examines query parameters in the URL for known redirect parameter names
    (e.g., ``redirect``, ``url``, ``next``, ``goto``, ``return``). These are
    common sinks for open redirect vulnerabilities.

    Args:
        param_urls: List of parameter-bearing URLs.

    Returns:
        True if at least one redirect parameter pattern is found.
    """
    if not param_urls:
        return False
    from urllib.parse import parse_qs, urlparse
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            if param_names_lower & _REDIRECT_PARAM_PATTERNS:
                param_names_lower & _REDIRECT_PARAM_PATTERNS
                return True
        except Exception:
            continue
    return False


def _count_redirect_params(param_urls: list[str]) -> int:
    """Count how many parameter-bearing URLs have redirect parameters."""
    if not param_urls:
        return 0
    from urllib.parse import parse_qs, urlparse
    count = 0
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            if param_names_lower & _REDIRECT_PARAM_PATTERNS:
                count += 1
        except Exception:
            continue
    return count


def _get_redirect_param_names(param_urls: list[str]) -> list[str]:
    """Get the matched redirect parameter names found in URLs."""
    if not param_urls:
        return []
    from urllib.parse import parse_qs, urlparse
    matched: set[str] = set()
    for url in param_urls:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            param_names_lower = {p.lower() for p in params}
            matched.update(param_names_lower & _REDIRECT_PARAM_PATTERNS)
        except Exception:
            continue
    return sorted(matched)[:5]


def _activate_open_redirect(rc) -> tuple[bool, str]:
    """Activate when parameter-bearing URLs contain redirect patterns.

    Open redirect vulnerabilities allow attackers to redirect users to
    arbitrary external URLs via the target's redirect parameters.
    While often considered low-severity, open redirects are frequently
    chained with phishing campaigns and can bypass URL validation in
    SSO/OAuth flows.

    Activates when:
      - ``has_open_redirect`` flag is set on ReconContext (forward-compatible)
      - ``redirect_endpoints`` list is populated (forward-compatible)
      - Parameter-bearing URLs contain redirect-like parameter names
        (redirect, url, next, goto, return, etc.)
      - Redirect-related keywords appear in tech_stack
    """
    # Forward-compatible: check for dedicated open redirect attribute
    has_oredirect = _get_attr(rc, "has_open_redirect", False)
    if has_oredirect:
        return True, "open redirect signals detected in recon"

    redirect_eps = _get_attr(rc, "redirect_endpoints", [])
    if redirect_eps and len(redirect_eps) > 0:
        return True, f"{len(redirect_eps)} redirect endpoint(s) found"

    # Check tech_stack for redirect-related technologies
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        redirect_keywords = {"redirect", "forward", "rewrite",
                             "mod_rewrite", "url-rewrite", "route-redirect"}
        matched = [kw for kw in redirect_keywords if kw in tech_lower]
        if matched:
            return True, f"redirect-related tech detected: {', '.join(matched)}"

    # Parameter-bearing URLs with redirect parameter names
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and _has_redirect_params(param_urls):
        redirect_count = _count_redirect_params(param_urls)
        matched_params = _get_redirect_param_names(param_urls)
        suffix = f" (params: {', '.join(matched_params)})" if matched_params else ""
        return True, f"{redirect_count} URL(s) with redirect parameters{suffix}"

    return False, "no open redirect signals detected"


def _open_redirect_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for open redirect vulnerability testing.

    Tests for:
      - Open redirect via common parameter names (redirect, url, next, goto)
      - Blind open redirect via multiple parameter injection
      - XSS chaining via redirect (javascript:/data: URIs in redirect params)
      - OAuth/SSO redirect_uri validation bypass
      - Host header injection combined with redirect parameters
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Open redirect vulnerability scanning (common parameters)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "redirect,open-redirect,oast,exposure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Open redirect chaining and parameter injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "redirect,ssrf,oast,url-injection,parameter"],
        ),
    ]
    return tools


# ── Phase: XXE (XML External Entity) Testing ───────────────────────────────

# XML processing libraries and technologies for tech_stack matching
_XML_PROCESSORS: set[str] = {
    # Core C/C++ libraries
    "libxml", "libxml2", "xmlsec",
    # Python
    "lxml", "xml.etree", "xml.dom", "xml.sax", "xml.parsers",
    "defusedxml", "xmltodict", "untangle", "xmlschema",
    # Java
    "javax.xml", "org.w3c.dom", "org.xml.sax",
    "documentbuilder", "documentbuilderfactory",
    "saxparser", "saxparserfactory",
    "xerces", "xalan", "jaxb", "jaxp", "jdom", "dom4j",
    "castor", "xmlbeans",
    # .NET
    "system.xml", "xmltextreader", "xmlreader",
    "xmldocument", "xpathdocument", "linq to xml",
    # PHP
    "simplexml", "domdocument", "xmlwriter",
    "soapclient", "simplexmlelement",
    # Ruby
    "nokogiri", "rexml", "libxml-ruby", "ox",
    # JavaScript / TypeScript
    "xmldom", "xpath", "sax-js", "node-xml",
    "fast-xml-parser", "xml2js",
    # HTTP/SOAP
    "soap", "soapui", "xml-rpc", "wsdl",
    # Frameworks with XML processing
    "spring-web-services", "cxf", "axis",
}


def _activate_xxe_testing(rc) -> tuple[bool, str]:
    """Activate when XML processing libraries are detected in tech_stack.

    XML External Entity (XXE) injection occurs when XML parsers are
    configured to process external entities, allowing attackers to:
    - Read local files (/etc/passwd, config files) via entity references
    - Perform SSRF by referencing internal URLs
    - Denial of Service via Billion Laughs / entity expansion

    Activates when:
      - ``has_xxe`` flag is set on ReconContext (forward-compatible)
      - ``xml_endpoints`` list is populated (forward-compatible)
      - XML processing keywords appear in tech_stack
      - File upload is present (XML file upload vector)
      - API endpoints are present (SOAP/XML APIs)
      - Parameter-bearing URLs are present (XXE injection vector)
    """
    # Forward-compatible: check for dedicated XXE attribute
    has_xxe = _get_attr(rc, "has_xxe", False)
    if has_xxe:
        return True, "XXE signals detected in recon"

    xml_eps = _get_attr(rc, "xml_endpoints", [])
    if xml_eps and len(xml_eps) > 0:
        return True, f"{len(xml_eps)} XML endpoint(s) found"

    # Check tech_stack for XML processing keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _XML_PROCESSORS if kw in tech_lower]
        if matched:
            return True, f"XML processing library detected: {', '.join(matched[:3])}"

    # File upload can include XML files
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        return True, "file upload present — XML file upload is an XXE vector"

    # API endpoints may use XML (SOAP, XML-RPC)
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — XML/SOAP endpoints may be vulnerable to XXE"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — XXE testing recommended"

    # Parameter-bearing URLs as XXE vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential XXE vector"

    return False, "no XML processing or XXE signals detected"


def _xxe_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for XXE vulnerability testing.

    Tests for:
      - Classic XXE (file disclosure via external entities)
      - Blind XXE (out-of-band exfiltration via DTD)
      - XXE via SOAP/XML-RPC endpoints
      - XXE via file upload (SVG, XML, DOCX)
      - XXE with SSRF chaining (internal port scanning)
      - Billion Laughs / entity expansion DoS detection
      - Parameter entity injection
      - XInclude attack detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="XXE vulnerability scanning (classic, blind, OOB, file disclosure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "xxe,xml,oob,exposure,disclosure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="XXE with SSRF chaining and entity injection scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "xxe,ssrf,oast,injection,xinclude"],
        ),
    ]
    return tools


# ── Phase: Path Traversal Testing ─────────────────────────────────────────

# File access functions and path-related keywords by language
_FILE_ACCESS_FUNCTIONS: set[str] = {
    # Python
    "open", "io.open", "os.path", "pathlib",
    "pathlib.path", "pathlib.read_text",
    # PHP
    "file_get_contents", "readfile", "fopen", "fread",
    "file", "include", "require", "include_once",
    "require_once", "file_put_contents", "fwrite",
    "fputs", "file_exists",
    # Java
    "filereader", "fileinputstream", "filechannel",
    "files.readallbytes", "files.readalllines",
    "paths.get", "new file", # .NET
    "file.readalltext", "file.readallbytes",
    "file.readalllines", "filestream",
    "streamreader", "file.openread",
    # Ruby
    "file.read", "file.open", "io.read",
    "pathname", "open-uri",
    # JavaScript / Node.js
    "fs.readfile", "fs.readfilesync",
    "fs.createreadstream", "fs.readdir",
    "fs.readdirsync", "fs.stat",
    # Go
    "os.readfile", "ioutil.readfile",
    "ioutil.readdir", "os.open",
    # Path traversal parameter names (recon signals)
    "page", "path", "dir", "directory",
    "document", "template", "load",
    "read", "show", "view", "display",
}


def _activate_path_traversal(rc) -> tuple[bool, str]:
    """Activate when file access functions are detected in tech_stack.

    Path traversal (directory traversal) allows attackers to access
    files and directories outside the web root by manipulating path
    references in user-controlled input. Common in file retrieval,
    template rendering, and document viewing functionality.

    Activates when:
      - ``has_path_traversal`` flag is set (forward-compatible)
      - ``path_traversal_endpoints`` list is populated (forward-compatible)
      - File access function keywords appear in tech_stack
      - Parameter-bearing URLs have path-traversal-like parameters
        (file, page, path, dir, document, template, include, etc.)
      - File upload is present (traversal via upload paths)
    """
    # Forward-compatible: check for dedicated path traversal attribute
    has_pt = _get_attr(rc, "has_path_traversal", False)
    if has_pt:
        return True, "path traversal signals detected in recon"

    pt_eps = _get_attr(rc, "path_traversal_endpoints", [])
    if pt_eps and len(pt_eps) > 0:
        return True, f"{len(pt_eps)} path traversal endpoint(s) found"

    # Check tech_stack for file access function keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _FILE_ACCESS_FUNCTIONS if kw in tech_lower]
        if matched:
            return True, f"file access function detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs with path traversal parameter names
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    reasons = []
    if param_urls:
        traversal_params = {"file", "page", "path", "dir", "directory",
                           "document", "template", "include", "load",
                           "read", "show", "view", "display",
                           "folder", "root", "base", "href"}
        from urllib.parse import parse_qs, urlparse
        for url in param_urls:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                param_names_lower = {p.lower() for p in params}
                if param_names_lower & traversal_params:
                    matched = param_names_lower & traversal_params
                    reasons.append(f"{len(param_urls)} URL(s) with traversal params")
                    break
            except Exception:
                continue

    # File upload can involve path traversal via upload paths
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        reasons.append("file upload present")

    if reasons:
        return True, "possible path traversal context: " + "; ".join(reasons)

    return False, "no path traversal signals detected"


def _path_traversal_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for path traversal vulnerability testing.

    Tests for:
      - Directory traversal via ../ patterns (../etc/passwd, ..\\windows\\)
      - Path traversal via URL-encoded variants (%2e%2e/, ..\\;/, ....//)
      - Blind path traversal via file existence detection
      - Path traversal via file upload filenames
      - File disclosure via traversal (config files, source code)
      - Local File Inclusion (LFI) via path traversal
      - Remote File Inclusion (RFI) via traversal patterns
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Path traversal and LFI scanning (dot-dot-slash, encoded variants, config disclosure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "lfi,path-traversal,traversal,disclosure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Path traversal via file upload and RFI scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "lfi,rfi,file-inclusion,upload,exposure"],
        ),
    ]
    return tools


# ── Phase: Command Injection Testing ─────────────────────────────────────

# Shell-execution functions and OS command interfaces by language
_CMD_EXECUTION_FUNCTIONS: set[str] = {
    # Python
    "os.system", "subprocess", "os.popen", "pty.spawn",
    "commands.getoutput", "subprocess.popen",
    # PHP
    "exec", "shell_exec", "system", "passthru", "popen",
    "proc_open", "pcntl_exec",
    # Java
    "runtime.exec", "runtime.getruntime.exec",
    "processbuilder", "processbuilder.start",
    # JavaScript / Node.js
    "child_process.exec", "child_process.execsync",
    "child_process.spawn", "child_process.execfile",
    "execSync", "execFileSync", "spawnSync",
    # Ruby
    "io.popen", "open3.popen3", "open3.capture3",
    "kernel.exec", "kernel.system",
    # .NET
    "process.start", "system.diagnostics.process",
    "cmd.exe", "powershell.exe",
    # Go
    "exec.command", "os/exec", "golang exec",
    # Perl
    "perl system", "perl exec", "perl backtick",
    # Shared concepts
    "cmd", "command", "shell", "sh",
    "bash", "powershell", "pwsh",
}


def _activate_command_injection(rc) -> tuple[bool, str]:
    """Activate when shell-execution functions are detected in tech_stack.

    Command injection (also known as OS command injection) allows an
    attacker to execute arbitrary operating system commands via a
    vulnerable application. It is one of the most critical web
    application vulnerabilities (OWASP Top 3) and typically leads
    to full server compromise.

    Activates when:
      - ``has_command_injection`` flag is set (forward-compatible)
      - ``cmd_injection_endpoints`` list is populated (forward-compatible)
      - Shell-execution function keywords appear in tech_stack
      - Parameter-bearing URLs are present (command injection vector)
      - File upload is present (filename-based command injection)
    """
    # Forward-compatible: check for dedicated command injection attribute
    has_cmdi = _get_attr(rc, "has_command_injection", False)
    if has_cmdi:
        return True, "command injection signals detected in recon"

    cmdi_eps = _get_attr(rc, "cmd_injection_endpoints", [])
    if cmdi_eps and len(cmdi_eps) > 0:
        return True, f"{len(cmdi_eps)} command injection endpoint(s) found"

    # Check tech_stack for shell-execution function keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _CMD_EXECUTION_FUNCTIONS if kw in tech_lower]
        if matched:
            return True, f"shell execution function detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs are a common command injection vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    reasons = []
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")

    # File upload can involve command injection via filename processing
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        reasons.append("file upload present")

    if reasons:
        return True, "possible command injection context: " + "; ".join(reasons)

    return False, "no command injection signals detected"


def _command_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for OS command injection vulnerability testing.

    Tests for:
      - Command injection via URL parameters (ping, host, nslookup)
      - Blind command injection (time-based, OOB/DNS)
      - Command injection via HTTP headers (User-Agent, X-Forwarded-For)
      - Command injection via file upload filenames
      - OS command chaining (; | && || `)
      - Blind payload delivery via OOB/out-of-band channels
      - Time-based command injection detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="OS command injection scanning (parameter-based, blind, time-based)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cmd-injection,rce,command,oast,blind"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="OS command injection via headers and chaining techniques",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cmd-injection,oast,time-based,chaining,exposure"],
        ),
    ]
    return tools


# ── Phase: NoSQL Injection Testing ─────────────────────────────────────────

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


def _activate_ldap_injection(rc) -> tuple[bool, str]:
    """Activate when LDAP-related keywords are detected in tech_stack.

    LDAP injection occurs when user input is embedded in LDAP query
    filters without proper sanitization. Impact ranges from authentication
    bypass to information disclosure (querying arbitrary directory entries).
    Common in enterprise applications using Active Directory for auth.

    Activates when:
      - ``has_ldap`` flag is set on ReconContext (forward-compatible)
      - ``ldap_endpoints`` list is populated (forward-compatible)
      - LDAP-related keywords appear in tech_stack
      - Auth endpoints are present (LDAP is frequently used for authentication)
      - Parameter-bearing URLs are present (LDAP injection vector)
    """
    # Forward-compatible: check for dedicated LDAP attribute
    has_ldap = _get_attr(rc, "has_ldap", False)
    if has_ldap:
        return True, "LDAP signals detected in recon"

    ldap_eps = _get_attr(rc, "ldap_endpoints", [])
    if ldap_eps and len(ldap_eps) > 0:
        return True, f"{len(ldap_eps)} LDAP endpoint(s) found"

    # Check tech_stack for LDAP-related keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _LDAP_KEYWORDS if kw in tech_lower]
        if matched:
            return True, f"LDAP technology detected: {', '.join(matched[:3])}"

    # LDAP is commonly used for authentication
    auth_eps = _get_attr(rc, "auth_endpoints", [])
    has_login = _get_attr(rc, "has_login_page", False)
    reasons = []
    if auth_eps and len(auth_eps) > 0:
        reasons.append(f"{len(auth_eps)} auth endpoint(s)")
    if has_login:
        reasons.append("login page")

    # Parameter-bearing URLs can be LDAP injection vectors
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")

    if reasons:
        return True, "possible LDAP context: " + "; ".join(reasons)

    return False, "no LDAP signals detected"


def _ldap_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for LDAP injection vulnerability testing.

    Tests for:
      - LDAP filter injection via login/username parameters
      - Blind LDAP injection via boolean-based inference
      - LDAP search filter manipulation
      - Active Directory-specific LDAP injection patterns
      - Authentication bypass via LDAP filter tampering
      - Information disclosure via crafted LDAP queries
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="LDAP injection vulnerability scanning (filter-based, auth bypass)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ldap,injection,ldapi,auth-bypass"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Active Directory and directory service exposure scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ldap,active-directory,exposure,disclosure"],
        ),
    ]
    return tools


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
        name="csrf_testing",
        description="Cross-Site Request Forgery testing (missing tokens, SameSite bypass, referer validation)",
        order=42,
        activate_fn=_activate_csrf_testing,
        tools_fn=_csrf_testing_tools,
        depends_on=["auth_testing", "access_control"],
        triggers=["session_analysis"],
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
        name="open_redirect",
        description="Open redirect vulnerability testing (redirect, url, next, goto parameters)",
        order=58,
        activate_fn=_activate_open_redirect,
        tools_fn=_open_redirect_tools,
        depends_on=["input_validation"],
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
        triggers=["ssrf_testing", "template_injection", "open_redirect", "ldap_injection", "xxe_testing", "no_sql_injection", "command_injection", "path_traversal"],
    ),
    _PhaseDefinition(
        name="xxe_testing",
        description="XML External Entity injection testing (file disclosure, SSRF chaining, OOB)",
        order=61,
        activate_fn=_activate_xxe_testing,
        tools_fn=_xxe_testing_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "ssrf_testing"],
    ),
    _PhaseDefinition(
        name="template_injection",
        description="Server-Side Template Injection testing (Jinja2, Twig, Blade, Pug, Velocity, FreeMarker)",
        order=62,
        activate_fn=_activate_template_injection,
        tools_fn=_template_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="deserialization_testing",
        description="Insecure deserialization testing (Java, Python, PHP, .NET, Node.js, Ruby)",
        order=63,
        activate_fn=_activate_deserialization_testing,
        tools_fn=_deserialization_testing_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "cloud_metadata_probe"],
    ),
    _PhaseDefinition(
        name="ldap_injection",
        description="LDAP injection and directory service testing (filter injection, auth bypass)",
        order=64,
        activate_fn=_activate_ldap_injection,
        tools_fn=_ldap_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="path_traversal",
        description="Path traversal and LFI testing (dot-dot-slash, encoded variants, file disclosure)",
        order=68,
        activate_fn=_activate_path_traversal,
        tools_fn=_path_traversal_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "file_upload_scan"],
    ),
    _PhaseDefinition(
        name="command_injection",
        description="OS command injection testing (parameter-based, blind, OOB, chaining)",
        order=67,
        activate_fn=_activate_command_injection,
        tools_fn=_command_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="no_sql_injection",
        description="NoSQL injection testing (MongoDB, CouchDB, Firebase, Elasticsearch)",
        order=66,
        activate_fn=_activate_nosql_injection,
        tools_fn=_nosql_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
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

    def should_continue(
        self,
        plan: WorkflowPlan,
        phase_results: list[dict],
        hypotheses: list[dict] | None = None,
        budget_remaining: dict | None = None,
    ) -> bool:
        """Determine whether the assessment should continue to the next phase.

        Called after each phase completes. Returns False if:
        - The current phase produced zero findings (fruitless path)
        - Budget is exhausted (time or phase limit reached)
        - All planned phases have been executed

        Returns True if:
        - There are pending hypothesis-driven phases (hypotheses exist)
        - Budget allows continued execution
        - There are unexecuted phases in the plan

        Args:
            plan: The current WorkflowPlan.
            phase_results: List of phase result dicts from completed phases.
                Each should have: phase, status, findings_count.
            hypotheses: Optional list of active hypotheses with suggested_tools.
            budget_remaining: Optional dict with remaining_budget_seconds and
                remaining_phases.

        Returns:
            True if the assessment should continue, False if it should stop.
        """
        # Check 1: No plan -> cannot continue
        if not plan or not plan.phases:
            return False

        # Check 2: All planned phases already executed
        executed_count = len(phase_results)
        if executed_count >= plan.total_phases:
            return False

        # Check 3: Budget exhaustion
        if budget_remaining:
            remaining_sec = budget_remaining.get("remaining_budget_seconds", None)
            if remaining_sec is not None and remaining_sec <= 0:
                return False
            remaining_phases = budget_remaining.get("remaining_phases", None)
            if remaining_phases is not None and remaining_phases <= 0:
                return False

        # Check 4: Zero-finding detection
        if phase_results:
            last_result = phase_results[-1]
            last_findings = last_result.get("findings_count", 0)

            if last_findings == 0:
                has_pending_hypotheses = bool(hypotheses and len(hypotheses) > 0)
                if not has_pending_hypotheses:
                    return False

            # Last 2 consecutive phases with zero findings = hard stop
            if len(phase_results) >= 2:
                second_last = phase_results[-2]
                if (
                    last_findings == 0
                    and second_last.get("findings_count", 0) == 0
                ):
                    return False

        # Default: continue
        return True

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

    def apply_hypotheses_to_plan(
        self,
        plan: WorkflowPlan,
        hypotheses: list[dict],
    ) -> WorkflowPlan:
        """Mark phases as hypothesis-driven based on predicted vulnerabilities.

        Examines each hypothesis's ``suggested_tools`` to find phases whose
        tool names overlap with hypothesis tools, then appends a note to those
        phases' ``activation_reason``. This makes the plan reflect predicted
        attack vectors in the LLM agent context.

        Currently only updates already-active phases (does not activate
        previously-skipped phases). If deeper hypothesis-to-phase activation
        is needed, extend this method to create new ``TestingPhase`` instances
        from ``self.phase_defs`` for matching skipped phases.

        Args:
            plan: The current WorkflowPlan to update.
            hypotheses: List of hypothesis dicts from HypothesisEngine.
                Each dict should have ``suggested_tools`` (list[str]).

        Returns:
            Updated WorkflowPlan with hypothesis-driven markers on phases.
        """
        if not plan or not hypotheses:
            return plan

        # Build a set of tool names mentioned across all hypotheses
        hypothesis_tools: set[str] = set()
        for h in hypotheses:
            suggested = h.get("suggested_tools", [])
            if isinstance(suggested, list):
                hypothesis_tools.update(suggested)

        if not hypothesis_tools:
            return plan

        # Mark any phase whose tool names overlap with hypothesis tools
        for phase in plan.phases:
            phase_tool_names = {t.tool_name for t in phase.tools}
            if phase_tool_names & hypothesis_tools:
                if not phase.activation_reason.endswith(" (hypothesis-driven)"):
                    phase.activation_reason += " (hypothesis-driven)"

        logger.info(
            "[AdaptivePlanner] apply_hypotheses_to_plan: %d hypothesis tool(s) "
            "matched against %d active phase(s)",
            len(hypothesis_tools),
            len(plan.phases),
        )
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
