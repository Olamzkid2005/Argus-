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

        This avoids loading all findings into memory at once,
        which is useful for large tool outputs.

        Args:
            raw_output: Raw tool output string

        Yields:
            Finding dictionaries one at a time
        """
        # Default implementation delegates to parse()
        # Subclasses can override for true streaming
        yield from self.parse(raw_output)


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
