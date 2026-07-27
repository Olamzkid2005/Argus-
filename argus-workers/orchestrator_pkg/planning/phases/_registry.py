"""Phase registry — centralized PHASE_DEFINITIONS list."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from ._types import ToolTask

_ReconCtx = Any
_ActivationResult = tuple[bool, str]


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


# Import all activation and tools functions from phase modules
from . import (
    tech_deep_scan,
    auth_testing,
    session_analysis,
    access_control,
    csrf_testing,
    graphql_introspection,
    api_scan,
    websocket_testing,
    cors_origin_testing,
    open_redirect,
    rate_limit_testing,
    input_validation,
    xxe_testing,
    template_injection,
    deserialization_testing,
    ldap_injection,
    path_traversal,
    command_injection,
    nosql_injection,
    ssrf_testing,
    infrastructure_scan,
    cloud_metadata_probe,
    file_upload_scan,
)


PHASE_DEFINITIONS: list[_PhaseDefinition] = [
    _PhaseDefinition(
        name="tech_deep_scan",
        description="Technology-specific deep scanning (CMS, frameworks, servers)",
        order=10,
        activate_fn=tech_deep_scan._activate_tech_deep_scan,
        tools_fn=tech_deep_scan._tech_deep_scan_tools,
        triggers=["auth_testing", "api_scan"],
    ),
    _PhaseDefinition(
        name="auth_testing",
        description="Authentication mechanism analysis (login, JWT, OAuth)",
        order=20,
        activate_fn=auth_testing._activate_auth_testing,
        tools_fn=auth_testing._auth_testing_tools,
        triggers=["session_analysis", "access_control"],
        depends_on=["tech_deep_scan"],
    ),
    _PhaseDefinition(
        name="session_analysis",
        description="Session token and cookie analysis (JWT, CSRF)",
        order=30,
        activate_fn=session_analysis._activate_session_analysis,
        tools_fn=session_analysis._session_analysis_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="access_control",
        description="Authorization and privilege testing (IDOR, privesc)",
        order=40,
        activate_fn=access_control._activate_access_control,
        tools_fn=access_control._access_control_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="csrf_testing",
        description="Cross-Site Request Forgery testing (missing tokens, SameSite bypass, referer validation)",
        order=42,
        activate_fn=csrf_testing._activate_csrf_testing,
        tools_fn=csrf_testing._csrf_testing_tools,
        depends_on=["auth_testing", "access_control"],
        triggers=["session_analysis"],
    ),
    _PhaseDefinition(
        name="graphql_introspection",
        description="GraphQL introspection and schema exposure testing (introspection query, schema dump, playground)",
        order=48,
        activate_fn=graphql_introspection._activate_graphql_introspection,
        tools_fn=graphql_introspection._graphql_introspection_tools,
        triggers=["access_control", "input_validation"],
    ),
    _PhaseDefinition(
        name="api_scan",
        description="Deep API security testing (REST, GraphQL)",
        order=50,
        activate_fn=api_scan._activate_api_scan,
        tools_fn=api_scan._api_scan_tools,
        triggers=["access_control", "input_validation", "cors_origin_testing", "websocket_testing", "graphql_introspection"],
    ),
    _PhaseDefinition(
        name="websocket_testing",
        description="WebSocket security testing (origin validation, auth bypass, injection, CSWSH)",
        order=52,
        activate_fn=websocket_testing._activate_websocket_testing,
        tools_fn=websocket_testing._websocket_testing_tools,
        depends_on=["api_scan"],
        triggers=["access_control", "input_validation"],
    ),
    _PhaseDefinition(
        name="cors_origin_testing",
        description="CORS origin misconfiguration testing (wildcard, origin reflection, preflight bypass)",
        order=55,
        activate_fn=cors_origin_testing._activate_cors_origin_testing,
        tools_fn=cors_origin_testing._cors_origin_testing_tools,
        depends_on=["api_scan"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="open_redirect",
        description="Open redirect vulnerability testing (redirect, url, next, goto parameters)",
        order=58,
        activate_fn=open_redirect._activate_open_redirect,
        tools_fn=open_redirect._open_redirect_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="rate_limit_testing",
        description="Rate limiting and brute-force protection analysis (login, API, password reset)",
        order=45,
        activate_fn=rate_limit_testing._activate_rate_limit_testing,
        tools_fn=rate_limit_testing._rate_limit_testing_tools,
        depends_on=["auth_testing"],
    ),
    _PhaseDefinition(
        name="input_validation",
        description="Input validation and injection testing (XSS, SQLi, SSTI)",
        order=60,
        activate_fn=input_validation._activate_input_validation,
        tools_fn=input_validation._input_validation_tools,
        triggers=["ssrf_testing", "template_injection", "open_redirect", "ldap_injection", "xxe_testing", "no_sql_injection", "command_injection", "path_traversal"],
    ),
    _PhaseDefinition(
        name="xxe_testing",
        description="XML External Entity injection testing (file disclosure, SSRF chaining, OOB)",
        order=61,
        activate_fn=xxe_testing._activate_xxe_testing,
        tools_fn=xxe_testing._xxe_testing_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "ssrf_testing"],
    ),
    _PhaseDefinition(
        name="template_injection",
        description="Server-Side Template Injection testing (Jinja2, Twig, Blade, Pug, Velocity, FreeMarker)",
        order=62,
        activate_fn=template_injection._activate_template_injection,
        tools_fn=template_injection._template_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="deserialization_testing",
        description="Insecure deserialization testing (Java, Python, PHP, .NET, Node.js, Ruby)",
        order=63,
        activate_fn=deserialization_testing._activate_deserialization_testing,
        tools_fn=deserialization_testing._deserialization_testing_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "cloud_metadata_probe"],
    ),
    _PhaseDefinition(
        name="ldap_injection",
        description="LDAP injection and directory service testing (filter injection, auth bypass)",
        order=64,
        activate_fn=ldap_injection._activate_ldap_injection,
        tools_fn=ldap_injection._ldap_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="path_traversal",
        description="Path traversal and LFI testing (dot-dot-slash, encoded variants, file disclosure)",
        order=68,
        activate_fn=path_traversal._activate_path_traversal,
        tools_fn=path_traversal._path_traversal_tools,
        depends_on=["input_validation"],
        triggers=["access_control", "file_upload_scan"],
    ),
    _PhaseDefinition(
        name="command_injection",
        description="OS command injection testing (parameter-based, blind, OOB, chaining)",
        order=67,
        activate_fn=command_injection._activate_command_injection,
        tools_fn=command_injection._command_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="no_sql_injection",
        description="NoSQL injection testing (MongoDB, CouchDB, Firebase, Elasticsearch)",
        order=66,
        activate_fn=nosql_injection._activate_nosql_injection,
        tools_fn=nosql_injection._nosql_injection_tools,
        depends_on=["input_validation"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="ssrf_testing",
        description="Server-Side Request Forgery testing (blind, time-based, OOB, internal metadata)",
        order=65,
        activate_fn=ssrf_testing._activate_ssrf_testing,
        tools_fn=ssrf_testing._ssrf_testing_tools,
        depends_on=["input_validation"],
        triggers=["cloud_metadata_probe"],
    ),
    _PhaseDefinition(
        name="infrastructure_scan",
        description="Infrastructure and service fingerprinting (ports, TLS)",
        order=70,
        activate_fn=infrastructure_scan._activate_infrastructure,
        tools_fn=infrastructure_scan._infrastructure_scan_tools,
    ),
    _PhaseDefinition(
        name="cloud_metadata_probe",
        description="Cloud metadata service probing (IMDS, cloud storage misconfig)",
        order=75,
        activate_fn=cloud_metadata_probe._activate_cloud_metadata,
        tools_fn=cloud_metadata_probe._cloud_metadata_tools,
        depends_on=["infrastructure_scan"],
        triggers=["access_control"],
    ),
    _PhaseDefinition(
        name="file_upload_scan",
        description="File upload abuse testing (unrestricted upload, path traversal)",
        order=80,
        activate_fn=file_upload_scan._activate_file_upload,
        tools_fn=file_upload_scan._file_upload_scan_tools,
    ),
]
