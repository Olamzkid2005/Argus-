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

from .parsers import generic, gitleaks, nikto, nmap, nuclei, semgrep, sqlmap, whatweb
from .types import NormalizedFinding

logger = logging.getLogger(__name__)

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


def dispatch(tool_name: str, output: str) -> list[NormalizedFinding]:
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
            return instance.parse(output)
        except Exception as exc:
            logger.warning(
                "System B parser '%s' failed: %s — falling back to generic",
                tool_name,
                exc,
            )

    # 3. Fall back to generic heuristic parser
    return generic.parse(output)


def has_parser(tool_name: str) -> bool:
    if tool_name in _PARSERS:
        return True
    extra = _ensure_extra_parsers()
    return tool_name in extra
