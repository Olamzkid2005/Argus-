import logging
from abc import ABC, abstractmethod
from collections.abc import Generator

from exceptions import ParserError as ParserError  # re-exported by parsers/__init__

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """Base class for tool output parsers"""

    @abstractmethod
    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse tool output into structured findings

        Args:
            raw_output: Raw tool output string

        Returns:
            List of finding dictionaries
        """
        pass

    def parse_stream(self, raw_output: str) -> Generator[dict, None, None]:
        """
        Parse tool output as a generator, yielding one finding at a time.

        Override this in subclasses for true streaming behavior.
        The default implementation loads all findings then yields them,
        which defeats streaming — subclasses should parse line-by-line.

        Args:
            raw_output: Raw tool output string

        Yields:
            Finding dictionaries one at a time
        """
        # Default: parse all and yield from (not true streaming — override in subclass)
        findings = self.parse(raw_output)
        yield from findings
        # Free memory after yielding all findings
        del findings


def _safe_get(data, *keys, default=None):
    """
    Safely traverse a nested dict, returning *default* if any key is
    missing OR if an intermediate value is None (JSON null).
    Unlike nested dict.get() chains, this handles JSON null correctly.
    """
    current = data
    for key in keys:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default

def structured_findings(raw_output: str) -> list[dict] | None:
    """Findings that a tool already emitted as structured JSON.

    The Argus recon shims replace binaries that cannot be installed here and
    report results as ``[{title, type, severity, description, endpoint, tool}]``.
    A parser written for the upstream tool's plain-text output would otherwise
    turn that whole array into one garbled finding, so every parser offers the
    structured form first.
    """
    import json

    try:
        data = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and isinstance(data.get("findings"), list):
        data = data["findings"]
    if not isinstance(data, list):
        return None
    items = [
        item
        for item in data
        if isinstance(item, dict) and (item.get("title") or item.get("description"))
    ]
    return items or None
