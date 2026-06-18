"""
Tool Utilities — shared PATH resolution and binary discovery.

Consolidates the augmented PATH logic that was duplicated across:
  - tool_definitions.py::is_tool_available()
  - tool_runner.py::_resolve_tool_path()
  - mcp_bridge.py::_is_binary_available()

Usage:
    from tools.tool_utils import is_tool_available, resolve_tool_binary
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def get_augmented_path() -> str:
    """Build a PATH string that includes venv/bin, Go bin, and Homebrew bin.

    Returns the PATH with extra directories prepended so that tools installed
    via pip, go install, or Homebrew are findable regardless of the current
    shell environment.
    """
    venv_bin = str(Path(sys.executable).parent)
    go_bin = os.path.expanduser("~/go/bin")

    # Also check the project-level venv (in case system python is used)
    project_venv_bin = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin")
    )

    extra_dirs = [
        venv_bin,
        project_venv_bin,
        go_bin,
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]

    current_path = os.environ.get("PATH", "")
    for d in extra_dirs:
        if d not in current_path and os.path.isdir(d):
            current_path = f"{d}:{current_path}"
    return current_path


def resolve_tool_binary(
    tool_name: str, extra_dirs: list[str] | None = None
) -> str | None:
    """Resolve the full path to a tool binary.

    Checks the augmented PATH (venv, Go, Homebrew) via :func:`get_augmented_path`.
    If *extra_dirs* is provided, those directories are also searched as a
    final fallback via a direct file-existence check.

    Args:
        tool_name: Name of the tool binary (e.g. "nuclei", "httpx").
        extra_dirs: Additional directories to scan as a direct-file fallback
            (``shutil.which`` may not find binaries in all contexts).

    Returns:
        Full path to the binary, or None if not found.
    """
    augmented_path = get_augmented_path()

    resolved = shutil.which(tool_name, path=augmented_path)
    if resolved:
        return resolved

    # Optional direct-file fallback for caller-provided directories
    if extra_dirs:
        for d in extra_dirs:
            candidate = os.path.join(d, tool_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

    return None


def is_tool_available(tool_name: str, extra_dirs: list[str] | None = None) -> bool:
    """Check if a tool binary is available on the system or augmented PATH.

    Args:
        tool_name: Name of the tool binary to check.
        extra_dirs: Optional extra directories to search as fallback.

    Returns:
        True if the tool binary is found, False otherwise.
    """
    return resolve_tool_binary(tool_name, extra_dirs=extra_dirs) is not None
