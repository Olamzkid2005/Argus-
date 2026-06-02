"""tool_core.parser — Parser and normalizer facades.

Re-exports from ``parsers/`` — the canonical implementations live
in ``parsers/parser.py`` and ``parsers/normalizer.py``.
"""

from tool_core.parser.dispatcher import Parser
from tool_core.parser.normalizer import FindingNormalizer

__all__ = ["Parser", "FindingNormalizer"]
