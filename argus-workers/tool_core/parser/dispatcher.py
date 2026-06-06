"""Dispatcher — routes raw tool output to the appropriate parser."""
import logging

from .parsers import nuclei, nmap, sqlmap, semgrep, gitleaks, whatweb, nikto, generic
from .types import NormalizedFinding

logger = logging.getLogger(__name__)

_PARSERS = {
    "nuclei": nuclei.parse,
    "nmap": nmap.parse,
    "sqlmap": sqlmap.parse,
    "semgrep": semgrep.parse,
    "gitleaks": gitleaks.parse,
    "whatweb": whatweb.parse,
    "nikto": nikto.parse,
}


def dispatch(tool_name: str, output: str) -> list[NormalizedFinding]:
    parser = _PARSERS.get(tool_name)
    if parser:
        try:
            return parser(output)
        except Exception as exc:
            logger.warning("Parser '%s' failed: %s", tool_name, exc)
    return generic.parse(output)


def has_parser(tool_name: str) -> bool:
    return tool_name in _PARSERS
