"""
Parser registry — imports all available parser classes.

Each parser for a specific tool output format lives in its own file.
The __init__.py auto-discovers available parsers so the registry
doesn't need manual updates when new parsers are added.
"""

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

from parsers.parsers.base import BaseParser, ParserError  # noqa: F401

# Auto-discover all parser modules in this package
_parser_registry: dict[str, type[BaseParser]] = {}

_this_dir = Path(__file__).parent

def _is_parser_module(module) -> bool:
    """Check if module contains a BaseParser subclass (fix 6.1, 11.10)."""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseParser)
            and attr is not BaseParser
        ):
            return True
    return False

for module_info in pkgutil.iter_modules([str(_this_dir)]):
    module_name = module_info.name
    if module_name.startswith("__"):
        continue

    try:
        module = importlib.import_module(f"parsers.parsers.{module_name}")
        # Only register modules that actually contain a parser class (fix 11.10)
        if not _is_parser_module(module):
            logger.debug(f"Skipping module '{module_name}' — no BaseParser subclass found")
            continue
        # Find the parser class in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseParser)
                and attr is not BaseParser
            ):
                _parser_registry[module_name] = attr
                # Make it available at package level
                globals()[attr_name] = attr
    except Exception as e:
        logger.warning(f"Failed to load parser module '{module_name}': {e}")

__all__ = ["BaseParser", "ParserError"] + list(_parser_registry.keys())
