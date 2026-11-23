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
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def get_augmented_path() -> str:
    """Build a PATH string that includes venv/bin, Go bin, and Homebrew bin.

    Returns the PATH with extra directories prepended so that tools installed
    via pip, go install, or Homebrew are findable regardless of the current
    shell environment.

    ``~/go/bin`` comes first on purpose, mirroring
    ``mcp_server._augmented_tool_path()``: the venv ships Python console
    scripts whose names collide with the Go security binaries — ``venv/bin/httpx``
    is the *Python* HTTPX CLI, not ProjectDiscovery's httpx — so with the venv
    first this resolver returned a different program than the worker's
    discovery check, and execution failed with ``Error: No such option: -s``.
    """
    venv_bin = str(Path(sys.executable).parent)
    go_bin = os.path.expanduser("~/go/bin")
    local_bin = os.path.expanduser("~/.local/bin")

    # Also check the project-level venv (in case system python is used)
    project_venv_bin = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin")
    )

    extra_dirs = [
        go_bin,
        local_bin,
        venv_bin,
        project_venv_bin,
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]

    current_path = os.environ.get("PATH", "")
    # Prepend the extra dirs *in priority order*. Appending to a string in a
    # loop reverses the priority (the last dir ends up first), which put
    # ``venv/bin`` ahead of ``~/go/bin`` and resolved ``httpx`` to the Python
    # HTTPX CLI instead of ProjectDiscovery's binary.
    ordered: list[str] = []
    seen: set[str] = set()
    for d in extra_dirs:
        if os.path.isdir(d) and d not in seen:
            ordered.append(d)
            seen.add(d)
    for part in current_path.split(os.pathsep):
        if part and part not in seen:
            ordered.append(part)
            seen.add(part)
    return os.pathsep.join(ordered)


# Tools whose real implementation is a native binary. A pip console script of
# the same name is a different program, never a substitute: `pip install httpx`
# installs the Python HTTP client's `httpx` CLI, and the venv's bin directory
# comes first on the worker PATH, so it shadowed ProjectDiscovery's httpx and
# every probe died on "The httpx command line client could not run".
NATIVE_ONLY_TOOLS = frozenset(
    {
        "amass",
        "alterx",
        "chaos",
        "dalfox",
        "dnsx",
        "ffuf",
        "gau",
        "gobuster",
        "gospider",
        "httpx",
        "katana",
        "naabu",
        "nuclei",
        "subfinder",
        "testssl",
        "uncover",
        "waybackurls",
        "whatweb",
        "wpscan",
    }
)


def is_python_console_script(path: str) -> bool:
    """True when *path* is a script whose shebang is a Python interpreter.

    A pip-installed console script (``venv/bin/httpx``) looks like an
    executable file to :func:`shutil.which`, so it has to be recognised by its
    shebang rather than by its name.
    """
    try:
        with open(path, "rb") as handle:
            first_line = handle.readline(200)
    except OSError:
        return False
    if not first_line.startswith(b"#!"):
        return False
    return b"python" in first_line.lower()


def _iter_candidates(
    tool_name: str, path_str: str, extra_dirs: list[str] | None
) -> list[str]:
    """Every executable named *tool_name* on the search path, in order."""
    dirs = [d for d in path_str.split(os.pathsep) if d]
    if extra_dirs:
        dirs.extend(extra_dirs)
    candidates: list[str] = []
    seen: set[str] = set()
    for directory in dirs:
        candidate = os.path.join(directory, tool_name)
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        candidates.append(candidate)
    return candidates


def shadowing_diagnostic(tool_name: str) -> str | None:
    """Explain why a native-only tool is unusable, or return None.

    Returns a message naming the offending interpreter script when the only
    executables found for *tool_name* are Python console scripts.
    """
    if tool_name not in NATIVE_ONLY_TOOLS:
        return None
    candidates = _iter_candidates(tool_name, get_augmented_path(), None)
    shadows = [c for c in candidates if is_python_console_script(c)]
    if not shadows or len(shadows) != len(candidates):
        return None
    return (
        f"{tool_name!r} resolves only to Python console script(s) "
        f"({', '.join(shadows)}), not the native {tool_name} binary; "
        f"install the native tool (e.g. go install "
        f"github.com/projectdiscovery/{tool_name}/cmd/{tool_name}@latest) "
        f"or put it earlier on the worker PATH."
    )


def resolve_tool_binary(
    tool_name: str, extra_dirs: list[str] | None = None
) -> str | None:
    """Resolve the full path to a tool binary.

    Checks the augmented PATH (venv, Go, Homebrew) via :func:`get_augmented_path`.
    If *extra_dirs* is provided, those directories are also searched as a
    final fallback via a direct file-existence check.

    Native binaries win over Python console scripts with the same name, and for
    :data:`NATIVE_ONLY_TOOLS` a console script alone means the tool is not
    installed: returning it would run an unrelated program and surface as a
    generic "failed after 1 retry".

    Args:
        tool_name: Name of the tool binary (e.g. "nuclei", "httpx").
        extra_dirs: Additional directories to scan as a direct-file fallback
            (``shutil.which`` may not find binaries in all contexts).

    Returns:
        Full path to the binary, or None if not found.
    """
    candidates = _iter_candidates(tool_name, get_augmented_path(), extra_dirs)
    if not candidates:
        return None

    natives = [c for c in candidates if not is_python_console_script(c)]
    if natives:
        if natives[0] != candidates[0]:
            logger.warning(
                "Ignoring Python console script %s for %r; using native binary %s",
                candidates[0],
                tool_name,
                natives[0],
            )
        return natives[0]

    if tool_name in NATIVE_ONLY_TOOLS:
        logger.warning(
            "%r is shadowed by Python console script %s and no native binary was "
            "found on the worker PATH",
            tool_name,
            candidates[0],
        )
        return None

    return candidates[0]


def is_tool_available(tool_name: str, extra_dirs: list[str] | None = None) -> bool:
    """Check if a tool binary is available on the system or augmented PATH.

    Args:
        tool_name: Name of the tool binary to check.
        extra_dirs: Optional extra directories to search as fallback.

    Returns:
        True if the tool binary is found, False otherwise.
    """
    return resolve_tool_binary(tool_name, extra_dirs=extra_dirs) is not None
