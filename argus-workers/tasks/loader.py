"""
Shared module loader for Celery workers.

Loads modules from the workers directory, avoiding sys.path issues in Celery fork pool workers.

Usage:
    from loader import load_module
    mod = load_module("orchestrator")
    Orchestrator = mod.Orchestrator
"""

import importlib.util
import os

_workers_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(module_name: str, rel_path: str = None):
    """
    Robust module loader for Celery tasks.

    Args:
        module_name: Name of the module to load (without .py extension)
        rel_path: Optional relative path from workers directory.
                  Defaults to {module_name}.py in tasks/ directory.

    Returns:
        The loaded Python module.

    Raises:
        FileNotFoundError: If the module file doesn't exist.
        ImportError: If the module cannot be loaded.
    """
    rel_path = rel_path or f"{module_name}.py"
    file_path = os.path.join(_workers_dir, rel_path)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Module not found: {file_path}")

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_workers_dir():
    """Return the workers directory path."""
    return _workers_dir
