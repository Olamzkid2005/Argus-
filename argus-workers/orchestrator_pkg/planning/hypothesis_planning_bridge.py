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
- Tool-task definitions are sourced from the phase modules in
  ``orchestrator_pkg.planning.phases`` to avoid duplication
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ── Phase tool builders ────────────────────────────────────────────────


def _get_phase_tools(phase_name: str, hypothesis: dict) -> list:
    """Get tool tasks for a hypothesis-driven phase activation.

    Looks up the phase in the canonical PHASE_DEFINITIONS registry
    and calls its tools builder function directly. This avoids
    duplicating function name construction logic and handles any
    naming inconsistencies between phase names and tool function
    names in the phase modules.

    Falls back to generating a minimal default tool list if the
    phase is not found in the registry.

    Args:
        phase_name: The phase name (must match PHASE_DEFINITIONS).
        hypothesis: The hypothesis dict (unused for tool building,
                    included for future extensibility).

    Returns:
        List of ToolTask instances.
    """
    from orchestrator_pkg.planning.phases._registry import PHASE_DEFINITIONS
    from orchestrator_pkg.planning.phases._types import ToolTask

    for pd in PHASE_DEFINITIONS:
        if pd.name == phase_name:
            return pd.tools_fn(None)

    # Fallback: minimal generic tool
    logger.debug(
        "No phase definition for '%s' — using minimal fallback tool",
        phase_name,
    )
    return [
        ToolTask(
            tool_name="nuclei",
            description=f"{phase_name} (hypothesis-driven)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical"],
        ),
    ]


# ── Hypothesis-to-Phase Mapping ────────────────────────────────────────

#: Maps hypothesis signals (tool names, CWE IDs, root-cause key prefixes)
#: to the phase name that should be activated in the WorkflowPlan.
#: Phase names MUST match AdaptiveWorkflowPlanner's PHASE_DEFINITIONS.
_HYPOTHESIS_PHASE_MAP: dict[str, str] = {
    # SQL injection signals → input_validation
    "sqlmap": "input_validation",
    "cwe:89": "input_validation",
    "sqli": "input_validation",

    # XSS signals → input_validation
    "dalfox": "input_validation",
    "cwe:79": "input_validation",
    "xss": "input_validation",

    # SSRF signals → ssrf_testing
    "ssrf": "ssrf_testing",
    "cwe:918": "ssrf_testing",

    # Command injection → command_injection (was incorrectly mapped to ssrf_testing)
    "cwe:78": "command_injection",
    "command_injection": "command_injection",

    # Auth signals → auth_testing / session_analysis
    "jwt_tool": "session_analysis",
    "cwe:287": "auth_testing",
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

    # Path traversal → path_traversal (was incorrectly mapped to path_traversal_testing)
    "cwe:22": "path_traversal",
    "path_traversal": "path_traversal",
    "lfi": "path_traversal",

    # XXE signals → xxe_testing
    "cwe:611": "xxe_testing",
    "xxe": "xxe_testing",
    "xml": "xxe_testing",

    # Open redirect → open_redirect (was incorrectly mapped to open_redirect_testing)
    "cwe:601": "open_redirect",
    "open_redirect": "open_redirect",

    # IDOR / access control → access_control
    "cwe:639": "access_control",
    "idor": "access_control",
    "bola": "access_control",
    "privilege_escalation": "access_control",
    "bopla": "access_control",

    # Information disclosure → infrastructure_scan (was incorrectly mapped to infrastructure_testing)
    "cwe:200": "infrastructure_scan",
    "info_disclosure": "infrastructure_scan",
    "exposure": "infrastructure_scan",

    # CORS → cors_origin_testing (was incorrectly mapped to cors_testing)
    "cwe:942": "cors_origin_testing",
    "cors": "cors_origin_testing",
    "wildcard_cors": "cors_origin_testing",

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

    # File upload → file_upload_scan (was incorrectly mapped to file_upload_testing)
    "file_upload": "file_upload_scan",
    "cwe:434": "file_upload_scan",

    # NoSQL injection → no_sql_injection (new)
    "cwe:943": "no_sql_injection",
    "nosql": "no_sql_injection",
    "mongodb": "no_sql_injection",

    # LDAP injection → ldap_injection (new)
    "cwe:90": "ldap_injection",
    "ldap": "ldap_injection",

    # Cloud metadata → cloud_metadata_probe (new)
    "imds": "cloud_metadata_probe",
    "cloud_metadata": "cloud_metadata_probe",
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
        confidence = hyp.get("confidence") or 0.0
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
                        root_key = hyp.get("root_cause_key", "unknown") or "unknown"
                        p.activation_reason += (
                            f" [hypothesis: {root_key}"
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

    Sources tool tasks from the corresponding phase module in
    ``planning/phases/`` to avoid duplicating tool-task definitions.

    Args:
        plan: WorkflowPlan to modify.
        phase_name: Name of the phase to activate (must match PHASE_DEFINITIONS).
        hypothesis: The hypothesis dict that triggered this activation.

    Raises:
        ValueError: If phase_name is not recognized (no matching phase module).
    """
    from orchestrator_pkg.planning.adaptive_planner import (
        TestingPhase,
    )

    confidence = hypothesis.get("confidence", 0.5)
    root_key = hypothesis.get("root_cause_key", "unknown")

    # Get tools from the phase module — no more duplicating tool definitions here!
    tools = _get_phase_tools(phase_name, hypothesis)

    if not tools:
        raise ValueError(f"No tools available for hypothesis-driven phase: {phase_name}")

    phase = TestingPhase(
        name=phase_name,
        description=f"{phase_name} (hypothesis-driven)",
        activation_reason=(
            f"hypothesis-driven: {root_key} @ {confidence:.0%} confidence"
        ),
        order=200,  # Place near end so signal-driven phases run first
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
