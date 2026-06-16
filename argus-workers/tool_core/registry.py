"""
tool_core/registry.py — ToolRegistry

Central registry for tool discovery and availability checking.

- Scans augmented PATH at startup
- Caches results with TTL
- Reports availability for all consumers
- Provides tool metadata from ``ToolDefinition`` fields

Singleton pattern: one instance per worker process.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import ClassVar

from tool_core.config.models import ToolMetadata

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for tool discovery and availability checking.

    Usage::

        registry = ToolRegistry()
        if registry.is_available("nuclei"):
            path = registry.resolve("nuclei")
            # ...
    """

    # Default extra directories to search for binaries
    _EXTRA_DIRS: ClassVar[list[str]] = [
        "/usr/local/bin",
        "/opt/homebrew/bin",
    ]

    def __init__(self) -> None:
        self._cache: dict[str, str | None] = {}
        self._last_scan: float = 0.0
        self._scan_interval: int = 300  # rescans PATH every 5 min

    # ── Public API ───────────────────────────────────────────────────

    def is_available(self, tool_name: str) -> bool:
        """Check if *tool_name* binary is available on PATH or known locations."""
        self._maybe_rescan()
        if tool_name not in self._cache:
            self._cache[tool_name] = self._resolve(tool_name)
        return self._cache[tool_name] is not None

    def resolve(self, tool_name: str) -> str | None:
        """Resolve full path to *tool_name* binary, or ``None``."""
        self._maybe_rescan()
        cached = self._cache.get(tool_name)
        if cached is not None:
            return cached
        resolved = self._resolve(tool_name)
        self._cache[tool_name] = resolved
        return resolved

    def available_tools(self) -> list[str]:
        """Return list of all currently available tool names."""
        self._maybe_rescan()
        return [name for name, path in self._cache.items() if path is not None]

    def scan_path(self) -> None:
        """Force a rescan of PATH and known locations for all registered tools."""
        self._cache.clear()
        self._last_scan = time.time()
        # Register tools from tool_definitions to populate cache
        try:
            from tool_definitions import TOOLS

            for name in TOOLS:
                self._cache[name] = self._resolve(name)
        except ImportError:
            pass

    def register_from_definition(self, tool_name: str) -> None:
        """Register a single tool from ``tool_definitions.TOOLS``."""
        try:
            from tool_definitions import TOOLS

            if tool_name in TOOLS:
                self._cache[tool_name] = self._resolve(tool_name)
        except ImportError:
            pass

    def get_metadata(self, tool_name: str) -> ToolMetadata | None:
        """Get metadata for *tool_name* from ``tool_definitions.py``."""
        try:
            from tool_definitions import TOOLS

            tool = TOOLS.get(tool_name)
            if tool and hasattr(tool, "metadata"):
                return tool.metadata
        except ImportError:
            pass
        return None

    # ── Internal helpers ─────────────────────────────────────────────

    def _maybe_rescan(self) -> None:
        """Rescan PATH if the scan interval has elapsed."""
        now = time.time()
        if now - self._last_scan > self._scan_interval:
            self._last_scan = now
            self._refresh_from_path()

    def _refresh_from_path(self) -> None:
        """Refresh cache by resolving all known tool names."""
        try:
            from tool_definitions import TOOLS

            for name in TOOLS:
                if name not in self._cache:
                    self._cache[name] = self._resolve(name)
        except ImportError:
            pass

    def _resolve(self, tool_name: str) -> str | None:
        """Resolve a single tool binary path using augmented PATH."""
        augmented_path = self._get_augmented_path()

        resolved = shutil.which(tool_name, path=augmented_path)
        if resolved:
            return resolved

        # Final fallback: direct file check in extra directories
        for d in self._EXTRA_DIRS:
            candidate = os.path.join(d, tool_name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        return None

    @staticmethod
    def _get_augmented_path() -> str:
        """Build augmented PATH including venv/bin, ~/go/bin, Homebrew."""
        venv_bin = str(Path(sys.executable).parent)
        go_bin = os.path.expanduser("~/go/bin")

        project_venv = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "venv", "bin")
        )

        extra_dirs = [
            venv_bin,
            project_venv,
            go_bin,
            "/usr/local/bin",
            "/opt/homebrew/bin",
        ]

        current_path = os.environ.get("PATH", "")
        for d in extra_dirs:
            if d not in current_path and os.path.isdir(d):
                current_path = f"{d}:{current_path}"
        return current_path
