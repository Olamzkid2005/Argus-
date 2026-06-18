"""
FfufScanner — Web fuzzing for directory/parameter discovery via ToolRunner + FfufParser.

Wraps the ``ffuf`` binary tool execution and output parsing into an
``AbstractTool`` that returns a ``UnifiedToolResult`` with standardized
findings.

Usage::

    scanner = FfufScanner()
    result = scanner.execute(ToolContext(target="https://example.com/FUZZ"))
    for f in result.findings:
        print(f["type"], f["endpoint"])
"""

from __future__ import annotations

import logging

from tool_core.base import AbstractTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult
from tools.tool_runner import ToolRunner
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class FfufScanner(AbstractTool):
    """
    Web fuzzing for directory/parameter discovery using the ``ffuf`` binary.

    Runs ffuf with ``-json`` output via ``ToolRunner``, then parses the
    JSON result with ``FfufParser`` to produce standardized
    ``DIRECTORY_FOUND`` findings.
    """

    tool_name: str = "ffuf"

    # Built-in wordlist paths (configurable via env)
    WORDLIST_MAP = {
        "passive": "common.txt",
        "normal": "common.txt",
        "aggressive": "extended.txt",
    }

    def __init__(self, tool_runner: ToolRunner | None = None) -> None:
        self._tool_runner = tool_runner or ToolRunner()

    @staticmethod
    def _get_wordlist_path(name: str) -> str:
        """Resolve path to a wordlist file."""
        try:
            from tools.tool_cache import get_wordlist_path

            return get_wordlist_path(name)
        except ImportError:
            # Fallback: look in common locations
            import os

            for base in (
                "/usr/share/wordlists",
                "/usr/share/ffuf",
                os.path.expanduser("~/wordlists"),
            ):
                candidate = os.path.join(base, name)
                if os.path.isfile(candidate):
                    return candidate
            return name

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        target = ctx.target
        timeout = ctx.timeout or 300
        aggressiveness = ctx.aggressiveness or "normal"

        slog = ScanLogger(self.tool_name)

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target,
        )

        wordlist_name = self.WORDLIST_MAP.get(aggressiveness, "common.txt")
        wordlist_path = self._get_wordlist_path(wordlist_name)

        slog.tool_start("ffuf", [target])

        args = ["-u", target, "-w", wordlist_path, "-json"]
        if aggressiveness == "aggressive":
            args.extend(["-t", "100", "-mc", "all"])
        elif aggressiveness == "high":
            args.extend(["-t", "50"])

        try:
            tool_result = self._tool_runner.run("ffuf", args, timeout=timeout)

            if not tool_result.success:
                if tool_result.status == ToolStatus.TIMEOUT:
                    # ffuf may time out on large wordlists — return partial results if any
                    if not tool_result.stdout:
                        slog.tool_complete("ffuf", success=False)
                        result.status = ToolStatus.TIMEOUT
                        result.error_message = tool_result.error_message
                        result.mark_finished()
                        return result

                else:
                    slog.tool_complete("ffuf", success=False)
                    result.status = ToolStatus.NONZERO_EXIT
                    result.stderr = tool_result.stderr
                    result.error_message = tool_result.error_message or "ffuf failed"
                    result.mark_finished()
                    return result

            # Parse stdout JSON
            from parsers.parsers.ffuf import FfufParser

            parsed = FfufParser().parse(tool_result.stdout or "")

            for finding in parsed:
                finding["source_tool"] = self.tool_name
            result.findings = parsed
            result.status = ToolStatus.SUCCESS
            slog.tool_complete("ffuf", success=True, findings=len(parsed))

        except Exception as e:
            logger.warning("FfufScanner failed for %s: %s", target, e)
            result.status = ToolStatus.EXCEPTION
            result.error_message = str(e)

        result.mark_finished()
        return result
