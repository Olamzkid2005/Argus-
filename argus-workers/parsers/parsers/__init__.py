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

from parsers.parsers.base import BaseParser, ParserError, _safe_get  # noqa: F401

# Auto-discover all parser modules in this package
_parser_registry: dict[str, type[BaseParser]] = {}

_this_dir = Path(__file__).parent
_skip_modules = {"__init__", "base"}

for module_info in pkgutil.iter_modules([str(_this_dir)]):
    module_name = module_info.name
    if module_name in _skip_modules:
        continue

    try:
        module = importlib.import_module(f"parsers.parsers.{module_name}")
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

__all__ = ["BaseParser", "ParserError", "_safe_get"] + list(_parser_registry.keys())
