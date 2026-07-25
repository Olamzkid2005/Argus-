"""
Hypothesis-Planning Bridge — maps HypothesisEngine output to phase activation.

This module connects two previously independent subsystems:

    HypothesisEngine.generate(findings)  ──►  [hypotheses with suggested_tools]
                                                    │
                                                    ▼
    AdaptiveWorkflowPlanner.build_plan()  ◄──  [activated phases]

When the HypothesisEngine detects a pattern (e.g., 3 findings clustered
on CWE-79 suggesting XSS, or a HIGH-severity SQLi finding needing
verification), the bridge activates the relevant testing phases in the
WorkflowPlan so the autonomous run actually acts on the insight.

Design
------
- Deterministic, no LLM dependency
- Hypothesis → phase mapping is rule-based using tool names, CWE IDs,
  and root-cause keys
- Non-destructive: only activates phases, never deactivates
- Graceful degradation: empty hypotheses = no-op
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Hypothesis-to-Phase Mapping ────────────────────────────────────────

#: Maps hypothesis signals (tool names, CWE IDs, root-cause key prefixes)
#: to the phase name that should be activated in the WorkflowPlan.
#: Phase names must match AdaptiveWorkflowPlanner's PHASE_DEFINITIONS.
_HYPOTHESIS_PHASE_MAP: dict[str, str] = {
    # SQL injection signals → input_validation (deep injection testing)
    "sqlmap": "input_validation",
    "cwe:89": "input_validation",
    "sqli": "input_validation",

    # XSS signals → input_validation (deep XSS testing)
    "dalfox": "input_validation",
    "cwe:79": "input_validation",
    "xss": "input_validation",

    # SSRF signals → ssrf_testing
    "ssrf": "ssrf_testing",
    "cwe:918": "ssrf_testing",

    # Command injection → ssrf_testing (overlaps with OOB testing)
    "cwe:78": "ssrf_testing",
    "command_injection": "ssrf_testing",

    # Auth signals → auth_testing
    "jwt_tool": "session_analysis",
    "cwe:287": "auth_testing",
    "dual_auth_scanner": "auth_testing",
    "jwt": "session_analysis",
    "credential": "auth_testing",

    # Deserialization signals → deserialization_testing
    "cwe:502": "deserialization_testing",
    "deserialization": "deserialization_testing",
    "pickle": "deserialization_testing",
    "jackson": "deserialization_testing",

    # Template injection → template_injection
    "cwe:94": "template_injection",
    "ssti": "template_injection",
    "template_injection": "template_injection",

    # Path traversal → path_traversal_testing
    "cwe:22": "path_traversal_testing",
    "path_traversal": "path_traversal_testing",
    "lfi": "path_traversal_testing",

    # XXE signals → xxe_testing
    "cwe:611": "xxe_testing",
    "xxe": "xxe_testing",
    "xml": "xxe_testing",

    # Open redirect → open_redirect_testing
    "cwe:601": "open_redirect_testing",
    "open_redirect": "open_redirect_testing",

    # IDOR / access control → access_control
    "cwe:639": "access_control",
    "idor": "access_control",
    "bola": "access_control",
    "privilege_escalation": "access_control",
    "bopla": "access_control",

    # Information disclosure → infrastructure_testing
    "cwe:200": "infrastructure_testing",
    "info_disclosure": "infrastructure_testing",
    "exposure": "infrastructure_testing",

    # CORS → cors_testing
    "cwe:942": "cors_testing",
    "cors": "cors_testing",
    "wildcard_cors": "cors_testing",

    # CSRF → csrf_testing
    "cwe:352": "csrf_testing",
    "csrf": "csrf_testing",

    # Rate limiting → rate_limit_testing
    "rate_limit": "rate_limit_testing",

    # WebSocket → websocket_testing
    "websocket": "websocket_testing",
    "cswsh": "websocket_testing",

    # GraphQL → graphql_introspection
    "graphql": "graphql_introspection",
    "introspection": "graphql_introspection",

    # API weakness → api_scan
    "api_key": "api_scan",
    "jwt_alg_none": "api_scan",
    "jwt_hmac": "api_scan",
    "openapi": "api_scan",
    "swagger": "api_scan",

    # File upload → file_upload_testing
    "file_upload": "file_upload_testing",
    "cwe:434": "file_upload_testing",
}


def _match_hypothesis_to_phases(hypothesis: dict) -> list[str]:
    """Map a single hypothesis to zero or more phase names.

    Checks:
      1. hypothesis['suggested_tools'] — tool names from the map
      2. hypothesis['root_cause_key'] — CWE or type key
      3. hypothesis['description'] — fallback keyword scan

    Returns:
        List of phase names to activate (may be empty).
    """
    phases: set[str] = set()

    # 1. Check suggested_tools
    for tool in hypothesis.get("suggested_tools", []):
        tool_lower = tool.lower().strip()
        if tool_lower in _HYPOTHESIS_PHASE_MAP:
            phases.add(_HYPOTHESIS_PHASE_MAP[tool_lower])

    # 2. Check root_cause_key (e.g., "cwe:89", "type:sqli:host:example.com")
    root_key = (hypothesis.get("root_cause_key") or "").lower()
    for search_key, phase in _HYPOTHESIS_PHASE_MAP.items():
        if search_key in root_key:
            phases.add(phase)

    # 3. Check description for keywords
    desc = (hypothesis.get("description") or "").lower()
    for search_key, phase in _HYPOTHESIS_PHASE_MAP.items():
        if search_key in desc:
            phases.add(phase)

    return list(phases)


def update_plan_from_hypotheses(plan, hypotheses: list[dict]) -> None:
    """Integrate hypotheses into a WorkflowPlan by activating phases.

    For each hypothesis with confidence >= 0.5 and non-empty
    suggested_tools, maps to relevant phases and activates them if
    not already present in the plan.

    Mutates the plan in-place. Safe to call with empty hypotheses.

    Args:
        plan: A WorkflowPlan instance with .phases list and
              .skipped_phases, .activated_phases attributes.
        hypotheses: List of hypothesis dicts from HypothesisEngine.
    """
    if not hypotheses or not plan:
        return

    activated_count = 0
    skipped_count = 0

    for hyp in hypotheses:
        confidence = hyp.get("confidence", 0.0)
        if confidence < 0.5:
            skipped_count += 1
            continue

        phase_names = _match_hypothesis_to_phases(hyp)
        if not phase_names:
            skipped_count += 1
            continue

        already_active = {p.name for p in plan.phases}

        for phase_name in phase_names:
            if phase_name in already_active:
                # Phase is already active — annotate it as hypothesis-driven
                for p in plan.phases:
                    if p.name == phase_name and "hypothesis" not in p.activation_reason:
                        p.activation_reason += (
                            f" [hypothesis: {hyp.get('root_cause_key', 'unknown')}"
                            f" @ {confidence:.0%}]"
                        )
                continue

            # Phase is not active — activate it
            try:
                _activate_phase(plan, phase_name, hyp)
                plan.activated_phases += 1
                plan.total_phases += 1
                activated_count += 1
                logger.info(
                    "Hypothesis activated phase '%s': confidence=%.2f, "
                    "root=%s, desc=%s",
                    phase_name,
                    confidence,
                    hyp.get("root_cause_key", "unknown"),
                    hyp.get("description", "")[:80],
                )
            except ValueError:
                # Unknown phase name — skip gracefully
                logger.debug(
                    "Hypothesis mapped to unknown phase '%s' — skipping",
                    phase_name,
                )
                skipped_count += 1

    if activated_count > 0 or skipped_count > 0:
        logger.info(
            "Hypothesis-plan integration: %d phase(s) activated, "
            "%d hypothesis(es) skipped",
            activated_count,
            skipped_count,
        )


def _activate_phase(plan, phase_name: str, hypothesis: dict) -> None:
    """Activate a phase in the plan by adding a TestingPhase entry.

    Uses standard tool tasks appropriate for the phase type.

    Args:
        plan: WorkflowPlan to modify.
        phase_name: Name of the phase to activate.
        hypothesis: The hypothesis dict that triggered this activation.

    Raises:
        ValueError: If phase_name is not recognized.
    """
    from orchestrator_pkg.planning.adaptive_planner import (
        ToolTask,
        TestingPhase,
    )

    confidence = hypothesis.get("confidence", 0.5)
    root_key = hypothesis.get("root_cause_key", "unknown")

    # Build tool tasks and description based on phase type
    if phase_name == "input_validation":
        tools = [
            ToolTask(
                tool_name="dalfox",
                description="XSS scanning on input parameters (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["url", "{target}", "--json"],
            ),
            ToolTask(
                tool_name="nuclei",
                description="Injection vulnerability scanning (hypothesis-driven)",
                priority=20,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "injection,sqli,lfi,ssrf,ssti"],
            ),
        ]
        description = "Deep input validation testing (hypothesis-driven)"

    elif phase_name == "ssrf_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="SSRF scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "ssrf,blind-oob,oast,http-injection"],
            ),
        ]
        description = "SSRF vulnerability testing (hypothesis-driven)"

    elif phase_name == "auth_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Auth vulnerability scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "auth,login,jwt,oauth,session"],
            ),
        ]
        description = "Authentication testing (hypothesis-driven)"

    elif phase_name == "session_analysis":
        tools = [
            ToolTask(
                tool_name="jwt_tool",
                description="JWT token analysis (hypothesis-driven)",
                priority=10,
                timeout=120,
                args_template=["{target}", "-C", "-d"],
            ),
        ]
        description = "Session token analysis (hypothesis-driven)"

    elif phase_name == "access_control":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="IDOR/ACL scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "idor,privesc,acl,exposure"],
            ),
        ]
        description = "Access control testing (hypothesis-driven)"

    elif phase_name == "deserialization_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Deserialization scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "deserialization,rce,oob,injection"],
            ),
        ]
        description = "Deserialization vulnerability testing (hypothesis-driven)"

    elif phase_name == "template_injection":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="SSTI scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "ssti,template-injection,injection"],
            ),
        ]
        description = "Template injection testing (hypothesis-driven)"

    elif phase_name == "path_traversal_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Path traversal scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "lfi,path-traversal,disclosure"],
            ),
        ]
        description = "Path traversal testing (hypothesis-driven)"

    elif phase_name == "xxe_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="XXE scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "xxe,xml,oob,exposure,disclosure"],
            ),
        ]
        description = "XXE vulnerability testing (hypothesis-driven)"

    elif phase_name == "open_redirect_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Open redirect scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "redirect,open-redirect,oast,exposure"],
            ),
        ]
        description = "Open redirect testing (hypothesis-driven)"

    elif phase_name == "cors_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="CORS scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "cors,headers,misconfig,exposure"],
            ),
        ]
        description = "CORS testing (hypothesis-driven)"

    elif phase_name == "csrf_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="CSRF scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "csrf,samesite,cookie,exposure,bypass"],
            ),
        ]
        description = "CSRF testing (hypothesis-driven)"

    elif phase_name == "rate_limit_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Rate limit testing (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "rate-limit,bruteforce,excessive"],
            ),
        ]
        description = "Rate limit testing (hypothesis-driven)"

    elif phase_name == "websocket_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="WebSocket security scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "websocket,ws,origin,cswsh,hijack"],
            ),
        ]
        description = "WebSocket testing (hypothesis-driven)"

    elif phase_name == "graphql_introspection":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="GraphQL introspection scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "graphql,introspection,schema,playground"],
            ),
        ]
        description = "GraphQL introspection testing (hypothesis-driven)"

    elif phase_name == "api_scan":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="API vulnerability scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "api,graphql,swagger,openapi,rest"],
            ),
        ]
        description = "API security testing (hypothesis-driven)"

    elif phase_name == "file_upload_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="File upload scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "file-upload,upload"],
            ),
        ]
        description = "File upload testing (hypothesis-driven)"

    elif phase_name == "infrastructure_testing":
        tools = [
            ToolTask(
                tool_name="nuclei",
                description="Infrastructure scanning (hypothesis-driven)",
                priority=10,
                timeout=300,
                args_template=["-u", "{target}", "-jsonl", "-silent",
                               "-severity", "medium,high,critical",
                               "-tags", "network,misconfig,exposure"],
            ),
        ]
        description = "Infrastructure testing (hypothesis-driven)"

    else:
        raise ValueError(f"Unknown hypothesis-driven phase: {phase_name}")

    phase = TestingPhase(
        name=phase_name,
        description=description,
        activation_reason=(
            f"hypothesis-driven: {root_key} @ {confidence:.0%} confidence"
        ),
        # Place near the end of execution order so signal-driven phases run first
        order=200,
        tools=tools,
    )
    plan.phases.append(phase)


# ── Integration helper ─────────────────────────────────────────────────


def apply_hypothesis_engine(
    plan,
    findings: list[dict],
    engagement_id: str = "",
) -> list[dict]:
    """Run HypothesisEngine on findings and integrate results into the plan.

    One-call convenience for the orchestrator: generates hypotheses from
    findings, then activates relevant phases in the plan.

    Args:
        plan: WorkflowPlan instance to update.
        findings: List of finding dicts (from the assessment).
        engagement_id: Optional engagement UUID for logging.

    Returns:
        The list of generated hypotheses (for logging/metrics).
    """
    try:
        from tools.hypothesis_engine import HypothesisEngine
    except ImportError:
        logger.warning("HypothesisEngine not available — skipping hypothesis integration")
        return []

    engine = HypothesisEngine()
    hypotheses = engine.generate(findings, engagement_id)

    if hypotheses:
        update_plan_from_hypotheses(plan, hypotheses)
        logger.info(
            "Hypothesis engine: %d hypothesis(es) generated, integrated into plan",
            len(hypotheses),
        )

    return hypotheses
