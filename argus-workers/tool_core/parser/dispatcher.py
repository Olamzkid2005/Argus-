"""Dispatcher — routes raw tool output to the appropriate parser.

Combines parsers from TWO systems:
  1. The native tool_core/parser/parsers/ (module-level parse() functions)
  2. The full parsers/parsers/ registry (BaseParser subclasses, ~30 tools)

System A (7 manual + generic fallback) is checked first for speed.
System B (auto-discovered ~30 parsers) is consulted when System A
has no match, ensuring the MCP bridge path benefits from the same
rich parsing the orchestrator path uses.
"""

import logging
from typing import Any

from .normalizer import normalize_confidence, normalize_severity
from .parsers import generic, gitleaks, nikto, nmap, nuclei, semgrep, sqlmap, whatweb
from .types import NormalizedFinding

logger = logging.getLogger(__name__)


def _confidence_to_int(value: Any) -> int:
    """Map a System B confidence (usually a 0-1 float) onto the 1-5 scale."""
    if isinstance(value, bool):
        return 3
    if isinstance(value, (int, float)):
        scaled = value * 5 if 0 <= value <= 1 else value
        return max(1, min(5, round(scaled)))
    return normalize_confidence(str(value))


def _to_normalized(finding: dict, tool_name: str) -> NormalizedFinding:
    """Convert a System B (BaseParser) finding dict into a NormalizedFinding.

    System B parsers return plain dicts while System A returns
    NormalizedFinding objects. The MCP server's result builder reads
    ``finding.__dict__``, so handing it a dict turns every System B parser's
    findings into a tool failure ("'dict' object has no attribute '__dict__'")
    — which silently cost the worker the ~30 tools that only have a System B
    parser (httpx, katana, naabu, gau, dalfox, trivy, bandit, ...).
    """
    severity = finding.get("severity", "medium")
    confidence = finding.get("confidence", "medium")

    evidence = finding.get("evidence")
    if evidence is None:
        evidence_list: list[dict] = []
    elif isinstance(evidence, list):
        evidence_list = [
            item if isinstance(item, dict) else {"content": item} for item in evidence
        ]
    elif isinstance(evidence, dict):
        evidence_list = [evidence]
    else:
        evidence_list = [{"content": evidence}]

    endpoint = finding.get("endpoint") or finding.get("url") or ""
    description = str(finding.get("description") or "")
    if endpoint and endpoint not in description:
        description = f"{endpoint}: {description}".strip(": ")

    return NormalizedFinding(
        title=str(finding.get("title") or finding.get("type") or "Finding"),
        severity=severity
        if isinstance(severity, int) and not isinstance(severity, bool)
        else normalize_severity(str(severity)),
        confidence=_confidence_to_int(confidence)
        if isinstance(confidence, (int, float))
        else normalize_confidence(str(confidence)),
        description=description,
        tool=str(finding.get("tool") or tool_name),
        cve=finding.get("cve"),
        cwe=finding.get("cwe"),
        owasp=finding.get("owasp"),
        remediation=finding.get("remediation"),
        evidence=evidence_list,
        subtype=finding.get("subtype") or finding.get("type"),
    )

# ── System A: native module-level parsers ──
_PARSERS = {
    "nuclei": nuclei.parse,
    "nmap": nmap.parse,
    "sqlmap": sqlmap.parse,
    "semgrep": semgrep.parse,
    "gitleaks": gitleaks.parse,
    "whatweb": whatweb.parse,
    "nikto": nikto.parse,
}

# ── System B: BaseParser class registry (lazy-loaded) ──
_EXTRA_PARSERS: dict[str, Any] | None = None


def _ensure_extra_parsers() -> dict[str, Any]:
    """Lazy-load parsers from parsers/parsers/_parser_registry."""
    global _EXTRA_PARSERS
    if _EXTRA_PARSERS is not None:
        return _EXTRA_PARSERS
    try:
        from parsers.parsers import _parser_registry

        # Instantiate each registered class so we can call .parse() on it.
        _EXTRA_PARSERS = {
            tool_name: parser_cls()
            for tool_name, parser_cls in _parser_registry.items()
            if tool_name not in _PARSERS  # don't shadow System A parsers
        }
        if _EXTRA_PARSERS:
            names = sorted(_EXTRA_PARSERS.keys())
            logger.debug(
                "Dispatcher enriched with %d parsers from parsers/parsers/: %s",
                len(names),
                ", ".join(names),
            )
    except ImportError:
        logger.debug(
            "parsers.parsers._parser_registry not available — falling back to System A only"
        )
        _EXTRA_PARSERS = {}
    except Exception as exc:
        logger.warning(
            "Failed to load extra parsers from parsers/parsers/: %s", exc
        )
        _EXTRA_PARSERS = {}
    return _EXTRA_PARSERS


def dispatch(
    tool_name: str,
    output: str,
    *,
    allow_generic: bool = True,
) -> list[NormalizedFinding]:
    """Route raw tool output to the parser for that tool.

    Args:
        tool_name: Name of the tool that produced the output.
        output: Raw stdout (or stderr) to parse.
        allow_generic: When False, skip the generic heuristic parser. Callers
            use this to ask "did this tool's *own* parser produce anything?"
            — the generic parser manufactures a RAW_OUTPUT finding for almost
            any text, so it cannot answer that question.
    """
    # 1. Try System A (native module-level parsers)
    parser = _PARSERS.get(tool_name)
    if parser:
        try:
            return parser(output)
        except Exception as exc:
            logger.warning("Parser '%s' failed: %s", tool_name, exc)

    # 2. Try System B (BaseParser class parsers)
    extra = _ensure_extra_parsers()
    instance = extra.get(tool_name)
    if instance is not None:
        try:
            return [_to_normalized(f, tool_name) for f in instance.parse(output)]
        except Exception as exc:
            logger.warning(
                "System B parser '%s' failed: %s — falling back to generic",
                tool_name,
                exc,
            )

    # 3. Fall back to generic heuristic parser. Callers that need to know
    #    whether the tool's own parser matched can opt out (see allow_generic).
    if not allow_generic:
        return []
    return generic.parse(output)


def has_parser(tool_name: str) -> bool:
    if tool_name in _PARSERS:
        return True
    extra = _ensure_extra_parsers()
    return tool_name in extra
