import logging
from abc import ABC, abstractmethod
from collections.abc import Generator

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Raised when parsing fails"""

    pass


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
        for finding in findings:
            yield finding
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
