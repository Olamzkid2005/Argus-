"""
Hypothesis Engine — generates and updates testable hypotheses from findings.

This is a plain service class — NOT an AbstractTool.
Hypotheses travel through EngagementState and Postgres, not the finding stream.
Call generate() directly from the orchestrator.

Design:
- Deterministic (no LLM) in Phase 1 — confidence scoring is rule-based
- The _initial_confidence() method is overridable for future LLM-based scoring
- _TYPE_TO_FAMILY and _VERIFICATION_TOOL_MAP are imported from models/finding_types.py
"""

from __future__ import annotations

import logging
from datetime import datetime
from tool_core._compat import utc
from uuid import uuid4

from models.finding_types import TYPE_TO_FAMILY, VERIFICATION_TOOL_MAP

logger = logging.getLogger(__name__)


class HypothesisEngine:
    """Generate ranked hypotheses and verification steps from a set of findings.

    This is a plain service class — NOT an AbstractTool.
    Hypotheses travel through EngagementState and Postgres, not the finding stream.
    Call ``generate()`` directly from the orchestrator.
    """

    def generate(self, findings: list[dict], engagement_id: str) -> list[dict]:
        """Generate hypotheses from pre-ranked findings.

        Caller is responsible for passing a severity-ranked, capped list.
        See ``FindingRepository.get_top_findings_for_hypothesis()``.

        Returns an empty list on any failure — the orchestrator degrades
        gracefully without hypotheses rather than crashing the engagement.
        """
        from feature_flags import is_enabled as _ff_enabled

        if not _ff_enabled("HYPOTHESIS_ENGINE", default=False):
            return []

        try:
            hypotheses = self._generate_inner(findings, engagement_id)
            self._emit_hypothesis_summary(hypotheses, engagement_id)
            return hypotheses
        except Exception as e:
            logger.exception(
                "HypothesisEngine.generate() failed — returning empty list",
                extra={"engagement_id": engagement_id, "error": str(e)},
            )
            return []

    def _generate_inner(self, findings: list[dict], engagement_id: str) -> list[dict]:
        """Core generation logic — deterministic, rule-based."""
        from config.constants import HYPOTHESIS_MAX_OUTPUT

        hypotheses = []
        groups = _group_findings_for_hypotheses(findings, min_group_size=2)

        for group in groups:
            confidence = self._initial_confidence(group)
            description = self._describe_group(group, confidence)
            suggested_tools = self._suggest_tools_from_group(group)
            verification_steps = self._build_verification_steps(
                group, suggested_tools)

            now = datetime.now(utc).isoformat()
            hypotheses.append({
                "id": str(uuid4()),
                "engagement_id": engagement_id,
                "description": description,
                "root_cause_key": group["root_cause_key"],
                "source_finding_id": None,
                "confidence": confidence,
                "status": "UNVERIFIED",
                "verification_steps": verification_steps,
                "finding_ids": group["finding_ids"],
                "supporting_finding_ids": [],
                "refuting_finding_ids": [],
                "suggested_tools": suggested_tools,
                "created_at": now,
                "updated_at": now,
            })

        # Single-finding hypotheses — only for HIGH/CRITICAL findings that
        # map to a verification tool the agent wouldn't otherwise run AND
        # haven't been verified yet.
        for f in findings:
            f_type = f.get("type", "")
            if not f_type:
                continue
            family = TYPE_TO_FAMILY.get(f_type.upper(), f_type.upper())
            if family not in VERIFICATION_TOOL_MAP:
                continue  # no tool to drive -> no hypothesis needed
            if f.get("severity") not in ("CRITICAL", "HIGH"):
                continue
            if f.get("verification_result") is not None:
                continue  # verification already ran, nothing to drive
            hypotheses.append(self._single_finding_hypothesis(f, engagement_id))

        hypotheses.sort(key=lambda h: h["confidence"], reverse=True)
        return hypotheses[:HYPOTHESIS_MAX_OUTPUT]

    def _emit_hypothesis_summary(self, hypotheses: list[dict],
                                  engagement_id: str) -> None:
        """Log summary after generation — single source of truth for count."""
        confirmed = sum(1 for h in hypotheses
                        if h.get("status") == "CONFIRMED")
        unverified = sum(1 for h in hypotheses
                         if h.get("status") == "UNVERIFIED")
        avg_conf = (sum(h.get("confidence", 0) for h in hypotheses)
                    / len(hypotheses)) if hypotheses else 0.0
        logger.info(
            "HYPOTHESIS_SUMMARY: engagement=%s total=%d unverified=%d "
            "confirmed=%d avg_confidence=%.2f",
            engagement_id, len(hypotheses), unverified, confirmed,
            round(avg_conf, 2),
        )
        # Metrics — best-effort, never crash
        try:
            from metrics import increment_counter
            increment_counter("hypothesis.generated", len(hypotheses),
                              tags={"engagement_id": engagement_id})
        except Exception:
            pass

    def _single_finding_hypothesis(self, f: dict,
                                   engagement_id: str) -> dict:
        """Create a hypothesis for a single HIGH/CRITICAL finding."""
        f_type = f.get("type", "")
        family = TYPE_TO_FAMILY.get(f_type.upper(), f_type.upper())
        tools = VERIFICATION_TOOL_MAP.get(family, ["verification_agent"])
        confidence = min(1.0, f.get("confidence", 0.5) * 1.2)
        now = datetime.now(utc).isoformat()

        return {
            "id": str(uuid4()),
            "engagement_id": engagement_id,
            "description": (
                f"High-severity {family} finding at {f.get('endpoint', 'unknown')} "
                f"requires verification ({confidence:.0%} confidence)."
            ),
            "root_cause_key": None,
            "source_finding_id": f.get("id"),
            "confidence": confidence,
            "status": "UNVERIFIED",
            "verification_steps": [
                {
                    "description": f"Run {tool} to verify {family} at "
                                   f"{f.get('endpoint', 'unknown')}",
                    "tool": tool,
                    "arguments": {"finding_id": f.get("id")},
                    "expected": "findings_count > 0",
                }
                for tool in tools
            ],
            "finding_ids": [f.get("id")] if f.get("id") else [],
            "supporting_finding_ids": [],
            "refuting_finding_ids": [],
            "suggested_tools": tools,
            "created_at": now,
            "updated_at": now,
        }

    def _describe_group(self, group: dict, confidence: float) -> str:
        """Build a human-readable description for a grouped hypothesis."""
        category = group.get("category", "type_host")
        count = group.get("finding_count", 0)
        host = group.get("affected_endpoints", ["unknown"])[0]
        cwe = group.get("common_cwe")
        params = group.get("common_parameters", [])

        if category == "cwe" and cwe:
            return (f"Findings with CWE-{cwe} cluster on {host}, "
                    f"indicating a common vulnerable component "
                    f"({confidence:.0%} confidence).")
        if category == "shared_parameter" and params:
            return (f"Vulnerability on parameter '{params[0]}' across "
                    f"{count} endpoints, suggesting a shared unparameterized "
                    f"query pattern ({confidence:.0%} confidence).")
        if category == "shared_endpoint":
            return (f"Multiple vulnerability types on {host} endpoints, "
                    f"suggesting systemic security issues "
                    f"({confidence:.0%} confidence).")

        # Generic fallback
        return (f"{count} findings of type {group.get('root_cause_key', 'unknown')} "
                f"on {host} ({confidence:.0%} confidence).")

    def _initial_confidence(self, group: dict) -> float:
        """Deterministic confidence based on group strength.

        Override this method in subclasses to plug in LLM-based scoring later.
        """
        max_severity = group.get("max_severity", "INFO")
        count = group.get("finding_count", 0)
        category = group.get("category", "type_host")

        base = {
            "CRITICAL": 0.8, "HIGH": 0.7, "MEDIUM": 0.5,
            "LOW": 0.3, "INFO": 0.2,
        }.get(max_severity, 0.5)

        # Bonus for multi-finding groups (more evidence → higher confidence)
        count_bonus = min(0.15, (count - 2) * 0.05)

        # CWE-keyed groups are stronger than type/host groups
        category_bonus = 0.1 if category == "cwe" else 0.0

        return min(1.0, base + count_bonus + category_bonus)

    def _suggest_tools_from_group(self, group: dict) -> list[str]:
        """Suggest verification tools based on group metadata."""
        common_cwe = group.get("common_cwe")

        # Try CWE-based first
        if common_cwe:
            cwe_to_tools = {
                "89": ["sqlmap", "verification_agent"],   # SQLi
                "79": ["finding_verifier", "verification_agent"],  # XSS
                "918": ["finding_verifier", "verification_agent"],  # SSRF
                "78": ["finding_verifier", "verification_agent"],  # Cmd inj
                "22": ["finding_verifier", "verification_agent"],  # Path trav
                "287": ["dual_auth_scanner", "verification_agent"],  # Auth
                "200": ["verification_agent"],  # Info exposure
            }
            tools = cwe_to_tools.get(common_cwe)
            if tools:
                return tools

        # Fall back to type-based tool mapping
        root_key = group.get("root_cause_key", "").lower()
        for family_key, tools in VERIFICATION_TOOL_MAP.items():
            if family_key.lower() in root_key:
                return tools

        return ["verification_agent"]

    def _build_verification_steps(self, group: dict,
                                  suggested_tools: list[str]) -> list[dict]:
        """Build structured VerificationStep dicts for the hypothesis."""
        steps = []
        for tool in suggested_tools:
            step = {
                "description": (
                    f"Run {tool} to verify "
                    f"{group.get('root_cause_key', 'unknown')}"
                ),
                "tool": tool,
                "arguments": self._default_arguments(tool, group),
                "expected": "findings_count > 0",
            }
            steps.append(step)
        return steps

    def _default_arguments(self, tool: str, group: dict) -> dict:
        """Map tool name to default invocation arguments based on group metadata."""
        args: dict = {}
        endpoints = group.get("affected_endpoints", [])
        if endpoints:
            args["target"] = endpoints[0]

        if tool == "sqlmap" and group.get("common_parameters"):
            args["parameter"] = group["common_parameters"][0]

        if tool == "finding_verifier":
            args["finding_ids"] = group.get("finding_ids", [])

        return args


# ── Module-level helpers ──────────────────────────────────────────────


def _group_findings_for_hypotheses(
    findings: list[dict],
    min_group_size: int = 2,
) -> list[dict]:
    """Group findings into clusters for hypothesis generation.

    Returns a list of group dicts with:
        root_cause_key, category, finding_count, max_severity,
        affected_endpoints, finding_ids, common_parameters, common_cwe
    """
    from collections import defaultdict

    if not findings:
        return []

    groups = []

    # 1. Group by CWE (strongest signal)
    cwe_groups = defaultdict(list)
    for f in findings:
        cwe = _extract_cwe(f)
        if cwe:
            cwe_groups[cwe].append(f)

    for cwe, f_list in cwe_groups.items():
        if len(f_list) < min_group_size:
            continue
        groups.append(_build_group_dict(
            root_cause_key=f"cwe:{cwe}",
            category="cwe",
            findings=f_list,
            common_cwe=cwe,
        ))

    # 2. Group by (type, host) — the existing dedup strategy
    type_host_groups = defaultdict(list)
    for f in findings:
        # Skip findings already grouped by CWE
        f_id = f.get("id")
        already_grouped = any(
            f_id in g["finding_ids"] for g in groups
        )
        if already_grouped:
            continue
        f_type = f.get("type", "")
        endpoint = f.get("endpoint", "")
        host = _extract_host(endpoint)
        key = f"type:{f_type}:host:{host}"
        type_host_groups[key].append(f)

    for key, f_list in type_host_groups.items():
        if len(f_list) < min_group_size:
            continue
        groups.append(_build_group_dict(
            root_cause_key=key,
            category="type_host",
            findings=f_list,
        ))

    # 3. Group by shared endpoint (different vuln types on same URL)
    endpoint_groups = defaultdict(list)
    for f in findings:
        f_id = f.get("id")
        already_grouped = any(
            f_id in g["finding_ids"] for g in groups
        )
        if already_grouped:
            continue
        endpoint = f.get("endpoint", "")
        if endpoint:
            endpoint_groups[endpoint].append(f)

    for endpoint, f_list in endpoint_groups.items():
        if len(f_list) < min_group_size:
            continue
        # Only group if there are multiple vulnerability types
        types = {f.get("type") for f in f_list}
        if len(types) < 2:
            continue
        groups.append(_build_group_dict(
            root_cause_key=f"shared_endpoint:{endpoint}",
            category="shared_endpoint",
            findings=f_list,
        ))

    # 4. Group by shared parameter (extracted from evidence)
    param_groups = defaultdict(list)
    for f in findings:
        f_id = f.get("id")
        already_grouped = any(
            f_id in g["finding_ids"] for g in groups
        )
        if already_grouped:
            continue
        params = _extract_parameters(f)
        for param in params:
            param_groups[param].append(f)

    for param, f_list in param_groups.items():
        if len(f_list) < min_group_size:
            continue
        groups.append(_build_group_dict(
            root_cause_key=f"shared_param:{param}",
            category="shared_parameter",
            findings=f_list,
            common_parameters=[param],
        ))

    return groups


def _build_group_dict(
    root_cause_key: str,
    category: str,
    findings: list[dict],
    common_cwe: str | None = None,
    common_parameters: list[str] | None = None,
) -> dict:
    """Build a group metadata dict from a list of findings."""
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2,
                      "LOW": 1, "INFO": 0}
    max_severity = "INFO"
    max_sev_val = -1
    endpoints: list[str] = []
    finding_ids: list[str] = []

    for f in findings:
        sev = f.get("severity", "INFO")
        sev_val = severity_order.get(sev, 0)
        if sev_val > max_sev_val:
            max_sev_val = sev_val
            max_severity = sev
        ep = f.get("endpoint", "")
        if ep and ep not in endpoints:
            endpoints.append(ep)
        fid = f.get("id")
        if fid:
            finding_ids.append(fid)

    return {
        "root_cause_key": root_cause_key,
        "category": category,
        "finding_count": len(findings),
        "max_severity": max_severity,
        "affected_endpoints": endpoints,
        "finding_ids": finding_ids,
        "common_parameters": common_parameters or [],
        "common_cwe": common_cwe,
    }


def _extract_cwe(finding: dict) -> str | None:
    """Extract CWE ID from a finding dict."""
    cwe = finding.get("cwe_id") or finding.get("cwe")
    if cwe:
        # Handle "CWE-89" or "89" formats
        return str(cwe).replace("CWE-", "").replace("cwe-", "")
    evidence = finding.get("evidence", {})
    if isinstance(evidence, dict):
        cwe = evidence.get("cwe") or evidence.get("cwe_id")
        if cwe:
            return str(cwe).replace("CWE-", "").replace("cwe-", "")
    return None


def _extract_host(endpoint: str) -> str:
    """Extract hostname from an endpoint URL."""
    if not endpoint:
        return "unknown"
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    return parsed.netloc or endpoint.split("/")[0]


def _extract_parameters(finding: dict) -> list[str]:
    """Extract parameter names from a finding's evidence dict.

    Looks for keys named 'parameter', 'param', 'input' in evidence.
    """
    evidence = finding.get("evidence", {})
    if not isinstance(evidence, dict):
        return []
    params = []
    for key in ("parameter", "param", "input", "parameters"):
        val = evidence.get(key)
        if isinstance(val, str) and val.strip():
            params.append(val.strip())
        elif isinstance(val, list):
            params.extend(v.strip() for v in val if isinstance(v, str))
    return list(set(params))
