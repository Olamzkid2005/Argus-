"""
Web scanner check modules — each check type is a separate module.

Auto-discovers available check modules so the registry stays in sync
without manual __init__ updates.
"""

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

_check_registry: dict[str, type] = {}

_this_dir = Path(__file__).parent
_skip_modules = {"__init__", "_helpers", "base"}

for module_info in pkgutil.iter_modules([str(_this_dir)]):
    module_name = module_info.name
    if module_name in _skip_modules:
        continue
    try:
        module = importlib.import_module(f"tools.web_scanner_checks.{module_name}")
        # Look for a class ending in "Check" in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and attr_name.endswith("Check"):
                _check_registry[module_name] = attr
                globals()[attr_name] = attr
    except Exception as e:
        logger.warning(f"Failed to load check module '{module_name}': {e}")

__all__ = list(_check_registry.keys())
