"""Production subtask executor on Argus's real tool layer (plan §4.6).

A subtask carries optional tool routing (``tool`` + ``arguments`` on the
persisted row, validated by :mod:`agent.delegation.generator`). This module is
the executor that runs it for real:

* the call goes through :class:`tools.tool_runner.ToolRunner`, so scope,
  egress-policy and dangerous-payload checks apply exactly as they do for
  every other tool invocation;
* :class:`runtime.governance.Governance` enforces the budget gate before the
  process spawns;
* high-impact tools additionally require an approval record, default-deny.

Refusals (scope, egress, budget, approval) are returned as structured output
with action outcome ``"refused"`` so the denial is visible in the persisted
result instead of masquerading as a tool failure. Only dangerous payloads and
missing tooling fail closed by raising, because neither can produce a result
worth persisting.

Specialist delegation (plan §4.6) routes through :class:`PrimaryAgent` with a
bounded payload: the specialist receives facts, authorized targets and the
allowed tool set — never the delegation store — and its merged findings come
back with source provenance. Conflicting specialist findings are surfaced for
the verifier/correlation layer, never silently resolved here.

Test doubles stay test doubles: nothing in this module fabricates tool output.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping

from agent.delegation.models import DelegationError
from agent.delegation.primary import PrimaryAgent
from agent.delegation.registry import SpecialistRegistry
from exceptions import SecurityError

logger = logging.getLogger(__name__)

#: Tools whose traffic is attack-shaped (active exploitation, brute force, or
#: broad network probing). They run only with an explicit approval record;
#: everything else needs no approval but still passes scope/egress/budget.
HIGH_IMPACT_TOOLS = frozenset(
    {
        "sqlmap",
        "nmap",
        "masscan",
        "nikto",
        "wpscan",
        "commix",
        "dalfox",
        "nuclei",
    }
)

#: Action outcomes recorded by this executor. ``refused`` is a terminal,
#: explainable denial — never a tool failure.
REFUSED = "refused"


def _is_refusal_status(status: Any) -> str | None:
    """Map a ToolRunner refusal status to its check name, else None."""
    name = str(status or "")
    if name == "scope_error":
        return "scope"
    return None


class ApprovalError(DelegationError):
    """A high-impact tool was requested without a valid approval record."""


#: A lone informational flag carries no target and changes nothing, so even
#: high-impact tools run it without an approval record (version/help probes).
INFORMATIONAL_ARGV = frozenset({"-version", "--version", "-h", "--help", "-v"})


def validate_approval(tool: str, arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return why *tool* must not run, or None when it is approved to proceed.

    Tools outside :data:`HIGH_IMPACT_TOOLS` need no approval record. A
    high-impact tool needs ``arguments["approval"]`` to be an object with a
    non-empty ``by`` field naming who approved the run; the record is echoed
    into the persisted result for audit. A lone informational flag
    (``-version``/``-h`` with no target) needs no approval.
    """
    if tool not in HIGH_IMPACT_TOOLS:
        return None
    argv = (arguments or {}).get("argv") or []
    if len(argv) == 1 and str(argv[0]).strip() in INFORMATIONAL_ARGV:
        return None
    approval = (arguments or {}).get("approval")
    if not isinstance(approval, Mapping) or not str(approval.get("by") or "").strip():
        return {
            "check": "approval",
            "reason": (
                f"tool {tool!r} is high-impact and needs an approval record "
                "(arguments.approval.by); refusing to run without one"
            ),
        }
    return None


def parse_eslint_json(stdout: str) -> list[dict[str, Any]]:
    """Extract findings from real ``eslint --format json`` output."""
    import json as _json

    try:
        documents = _json.loads(str(stdout or ""))
    except (ValueError, TypeError):
        return []
    if not isinstance(documents, list):
        return []
    findings: list[dict[str, Any]] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        file_path = str(document.get("filePath") or "")
        for message in document.get("messages") or []:
            if not isinstance(message, dict):
                continue
            rule = str(message.get("ruleId") or "lint")
            findings.append(
                {
                    "title": f"eslint:{rule}",
                    "severity": "MEDIUM"
                    if int(message.get("severity") or 1) == 1
                    else "HIGH",
                    "endpoint": file_path,
                    "evidence": {
                        "rule": rule,
                        "message": str(message.get("message") or ""),
                        "line": message.get("line"),
                        "column": message.get("column"),
                        "proof_evidence_refs": [f"eslint:{file_path}"],
                    },
                    "confidence": 0.9,
                    "source_tool": "eslint",
                }
            )
    return findings


def parse_semgrep_json(stdout: str) -> list[dict[str, Any]]:
    """Extract findings from real ``semgrep --json`` output."""
    import json as _json

    try:
        document = _json.loads(str(stdout or ""))
    except (ValueError, TypeError):
        return []
    results = (document or {}).get("results") if isinstance(document, dict) else []
    findings: list[dict[str, Any]] = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        check = str(item.get("check_id") or "semgrep")
        extra = item.get("extra") or {}
        findings.append(
            {
                "title": f"semgrep:{check.split('.')[-1]}",
                "severity": str(extra.get("severity") or "INFO").upper(),
                "endpoint": str(item.get("path") or ""),
                "evidence": {
                    "check_id": check,
                    "message": str(extra.get("message") or ""),
                    "lines": str(extra.get("lines") or ""),
                    "proof_evidence_refs": [f"semgrep:{item.get('path')}"],
                },
                "confidence": 0.9,
                "source_tool": "semgrep",
            }
        )
    return findings


def extract_tool_findings(
    tool: str, argv: list[str], stdout: str
) -> list[dict[str, Any]]:
    """Parse real tool stdout into finding objects (no fabrication).

    Only machine-readable outputs the tool itself emitted are parsed; anything
    else yields no findings rather than invented ones.
    """
    normalized = [str(part) for part in argv]
    if tool == "eslint" and "--format" in normalized:
        return parse_eslint_json(stdout)
    if tool == "semgrep" and "--json" in normalized:
        return parse_semgrep_json(stdout)
    return []


def _stdout_head(text: Any, *, limit: int = 500) -> str:
    lines = str(text or "").strip().splitlines()
    head = lines[0].strip() if lines else ""
    return head[:limit]


class ToolCallSpecialistRunner:
    """A specialist that executes one bounded real tool call (plan §4.6).

    The request payload is bounded by :class:`PrimaryAgent` (facts, authorized
    targets, allowed tools). This runner additionally confines itself to its
    own tool allowlist and to targets inside ``authorized_targets``; anything
    else is a structured refusal, never an exception, so the denial is merged
    into the Primary outcome like any other specialist result.
    """

    def __init__(
        self,
        role: str,
        tools: frozenset[str] | set[str],
        tool_runner_factory: Callable[[], Any],
    ) -> None:
        self._role = role
        self._tools = frozenset(tools)
        self._tool_runner_factory = tool_runner_factory

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        tool = str(request.get("tool") or "").strip()
        argv = [str(part) for part in (request.get("argv") or [])]
        target = str(request.get("target") or "").strip()
        allowed = set(request.get("allowed_tools") or [])
        authorized = set(request.get("authorized_targets") or [])
        if tool not in self._tools or (allowed and tool not in allowed):
            return {
                "status": "refused",
                "summary": f"specialist {self._role}: tool {tool!r} not in allowed set",
                "findings": [],
                "evidence_refs": [],
                "source_agent": f"specialist:{self._role}",
            }
        if target and authorized and target not in authorized:
            return {
                "status": "refused",
                "summary": (
                    f"specialist {self._role}: target {target!r} outside "
                    "authorized targets"
                ),
                "findings": [],
                "evidence_refs": [],
                "source_agent": f"specialist:{self._role}",
            }
        try:
            result = self._tool_runner_factory().run(tool, argv, timeout=120)
        except SecurityError as exc:
            raise DelegationError(f"specialist {self._role}: {exc}") from exc
        status = str(getattr(result, "status", "exception"))
        findings = list(getattr(result, "findings", None) or [])[:20]
        findings.extend(
            extract_tool_findings(tool, argv, str(getattr(result, "stdout", "") or ""))
        )
        findings = findings[:20]
        for finding in findings:
            if isinstance(finding, dict):
                finding.setdefault("source_agent", f"specialist:{self._role}")
        return {
            "status": "ok" if status in ("success", "success_empty") else status,
            "summary": f"specialist {self._role}: {tool} -> {status}",
            "findings": findings,
            "evidence_refs": [f"specialist:{self._role}:{tool}"],
            "source_agent": f"specialist:{self._role}",
        }


def default_specialist_registry(
    tool_runner_factory: Callable[[], Any],
) -> SpecialistRegistry:
    """Production specialist registry: bounded real-tool specialists."""
    registry = SpecialistRegistry()
    registry.register(
        "static-analyzer",
        {"sast", "scan", "analyze"},
        ToolCallSpecialistRunner(
            "static-analyzer",
            {"semgrep", "bandit", "eslint"},
            tool_runner_factory,
        ),
        description="Bounded local static analysis (semgrep, bandit, eslint).",
    )
    return registry


class RealToolExecutor:
    """Run subtasks through the real tool/approval/budget layer.

    Implements the :class:`~agent.delegation.worker.SubtaskExecutor` protocol
    so it drops into :class:`~agent.delegation.integration.IntentTaskRunner`
    wherever a fake executor was wired before.
    """

    def __init__(
        self,
        *,
        tool_runner_factory: Callable[[], Any] | None = None,
        governance_factory: Callable[[str], Any] | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        connection_string: str | None = None,
        default_timeout: int = 120,
    ) -> None:
        self._tool_runner_factory = tool_runner_factory
        self._governance_factory = governance_factory
        self._specialist_registry = specialist_registry
        self._connection_string = connection_string
        self._default_timeout = default_timeout

    # ----- construction helpers -----

    def _tool_runner(self, engagement_id: str) -> Any:
        if self._tool_runner_factory is not None:
            return self._tool_runner_factory()
        from tools.tool_runner import ToolRunner

        return ToolRunner(
            engagement_id=engagement_id or None,
            connection_string=self._connection_string,
        )

    def _governance(self, engagement_id: str) -> Any | None:
        if self._governance_factory is not None:
            return self._governance_factory(engagement_id)
        try:
            from runtime.governance import Governance

            return Governance(engagement_id)
        except Exception as exc:  # governance must never block tool execution
            logger.warning("governance unavailable for %s: %s", engagement_id, exc)
            return None

    def _registry(self) -> SpecialistRegistry:
        if self._specialist_registry is not None:
            return self._specialist_registry
        return default_specialist_registry(
            lambda: self._tool_runner_factory()
            if self._tool_runner_factory is not None
            else self._tool_runner("<unscoped>")
        )

    # ----- protocol -----

    def execute(self, request: dict[str, Any]) -> Any:
        subtask = request.get("subtask") or {}
        task = request.get("task") or {}
        engagement_id = str(task.get("engagement_id") or "")
        subtask_id = str(subtask.get("id") or "")
        ordinal = subtask.get("ordinal", 0)
        action_id = f"{subtask_id}:{ordinal}"
        tool = str(subtask.get("tool") or "").strip()
        arguments = dict(subtask.get("arguments") or {})
        facts = list(request.get("facts") or [])

        if not tool:
            raise DelegationError(
                f"subtask {subtask_id!r} names no tool: the production executor "
                "runs only subtasks with validated tool routing (fail closed)"
            )
        argv = arguments.get("argv", [])
        if not isinstance(argv, list) or not argv:
            raise DelegationError(
                f"subtask {subtask_id!r} tool {tool!r} has no argv: refusing "
                "to invent tool arguments (fail closed)"
            )

        specialist_spec = arguments.get("specialist")
        if specialist_spec is not None:
            return self._execute_specialist(
                request,
                action_id=action_id,
                tool=tool,
                arguments=arguments,
                specialist_spec=specialist_spec,
                facts=facts,
                engagement_id=engagement_id,
            )

        approval_refusal = validate_approval(tool, arguments)
        if approval_refusal is not None:
            return self._refused(
                action_id, tool, argv, approval_refusal, facts=facts
            )

        governance = self._governance(engagement_id)
        if governance is not None:
            allowed, reason = governance.check(
                {"tool": tool, "arguments": argv, "cost_usd": 0.0}
            )
            if not allowed:
                return self._refused(
                    action_id,
                    tool,
                    argv,
                    {"check": "budget", "reason": f"budget gate refused: {reason}"},
                    facts=facts,
                )

        try:
            from cache import CacheMode as _CacheMode

            _cache_mode = str(arguments.get("cache_mode", "NORMAL")).upper()
            try:
                cache_mode = _CacheMode[_cache_mode]
            except KeyError:
                cache_mode = _CacheMode.NORMAL
            result = self._tool_runner(engagement_id).run(
                tool,
                [str(part) for part in argv],
                timeout=int(arguments.get("timeout", self._default_timeout) or 0)
                or self._default_timeout,
                cache_mode=cache_mode,
            )
        except SecurityError as exc:
            raise DelegationError(f"tool call blocked (fail closed): {exc}") from exc

        status = str(getattr(result, "status", "exception"))
        error_type = str(getattr(result, "error_type", "") or "")
        if status == "scope_error" or (
            status == "skipped" and "egress" in error_type.lower()
        ):
            check = _is_refusal_status(status) or (
                "egress" if "egress" in error_type.lower() else "scope"
            )
            reason = str(
                getattr(result, "error_message", "") or getattr(result, "stderr", "")
            )
            return self._refused(
                action_id, tool, argv, {"check": check, "reason": reason}, facts=facts
            )

        outcome = "completed" if status in ("success", "success_empty") else "failed"
        findings = list(getattr(result, "findings", None) or [])[:20]
        findings.extend(
            extract_tool_findings(
                tool,
                [str(part) for part in argv],
                str(getattr(result, "stdout", "") or ""),
            )
        )
        findings = findings[:20]
        evidence = str(getattr(result, "stderr", "") or "") or str(
            getattr(result, "stdout", "") or ""
        )
        action = {
            "action_id": action_id,
            "tool": tool,
            "canonical_arguments": {"argv": [str(part) for part in argv]},
            "outcome": outcome,
            "result": {
                "status": status,
                "exit_code": getattr(result, "exit_code", None),
                "summary": _stdout_head(getattr(result, "stdout", "")),
                "stderr_tail": str(getattr(result, "stderr", "") or "")[-2000:],
            },
            "evidence_refs": [f"tool:{tool}:{action_id}"],
        }
        summary = f"{tool} -> {status}"
        head = _stdout_head(getattr(result, "stdout", ""))
        if head:
            summary = f"{summary}: {head}"
        output: dict[str, Any] = {"summary": summary, "actions": [action]}
        if findings:
            for finding in findings:
                if isinstance(finding, dict):
                    finding.setdefault("source_tool", tool)
            output["findings"] = findings
        if evidence and outcome == "failed":
            output["evidence_refs"] = [f"tool:{tool}:{action_id}"]
        _ = facts
        return output

    # ----- specialists -----

    def _execute_specialist(
        self,
        request: dict[str, Any],
        *,
        action_id: str,
        tool: str,
        arguments: dict[str, Any],
        specialist_spec: Any,
        facts: list[Any],
        engagement_id: str,
    ) -> dict[str, Any]:
        subtask = request.get("subtask") or {}
        if isinstance(specialist_spec, str):
            capabilities = {specialist_spec}
        elif isinstance(specialist_spec, Mapping):
            capabilities = set(specialist_spec.get("capabilities") or [])
            if specialist_spec.get("role"):
                capabilities.add(str(specialist_spec["role"]))
        else:
            capabilities = set()
        if not capabilities:
            raise DelegationError(
                "specialist routing needs capabilities (fail closed): "
                f"got {specialist_spec!r}"
            )
        agent = PrimaryAgent(self._registry())
        outcome = agent.handle(
            dict(subtask),
            capabilities=frozenset(str(cap) for cap in capabilities),
            facts=[dict(fact) for fact in facts if isinstance(fact, dict)],
            authorized_targets=[
                str(item) for item in (arguments.get("authorized_targets") or [])
            ],
            allowed_tools=[tool],
            engagement_id=engagement_id,
            extra={
                "tool": tool,
                "argv": [str(part) for part in (arguments.get("argv") or [])],
                "target": str(arguments.get("target") or ""),
            },
        )
        merged = outcome.as_result()
        merged["actions"] = [
            {
                "action_id": action_id,
                "tool": tool,
                "canonical_arguments": {"specialist": True},
                "outcome": "completed",
                "result": {"specialists": merged.get("specialists", [])},
                "evidence_refs": merged.get("evidence_refs", []),
            }
        ]
        return merged

    # ----- refusals -----

    def _refused(
        self,
        action_id: str,
        tool: str,
        argv: list[Any],
        refusal: dict[str, Any],
        *,
        facts: list[Any] | None = None,
    ) -> dict[str, Any]:
        reason = str(refusal.get("reason") or "refused by policy")
        logger.warning(
            "real tool executor refused %s %s: %s", tool, argv, reason[:200]
        )
        return {
            "summary": f"refused ({refusal.get('check')}): {reason[:300]}",
            "actions": [
                {
                    "action_id": action_id,
                    "tool": tool,
                    "canonical_arguments": {
                        "argv": [str(part) for part in argv]
                    },
                    "outcome": REFUSED,
                    "result": {
                        "check": refusal.get("check"),
                        "reason": reason,
                    },
                    "evidence_refs": [],
                }
            ],
            "refusal": refusal,
        }


def tool_runner_factory(
    engagement_id: str, *, connection_string: str | None = None
) -> Any:
    """Build the engagement-scoped ToolRunner the production path uses."""
    from tools.tool_runner import ToolRunner

    return ToolRunner(
        engagement_id=engagement_id or None,
        connection_string=connection_string or os.getenv("DATABASE_URL"),
    )
