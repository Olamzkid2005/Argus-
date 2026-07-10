"""
ArjunScanner — HTTP parameter discovery via ToolRunner + ArjunParser.

Wraps the ``arjun`` binary tool execution and output parsing into an
``AbstractTool`` that returns a ``UnifiedToolResult`` with standardized
findings.

Usage::

    scanner = ArjunScanner()
    result = scanner.execute(ToolContext(target="https://example.com"))
    for f in result.findings:
        print(f["type"], f["endpoint"])
"""

from __future__ import annotations

import logging
import os
import tempfile

from tool_core.base import AbstractTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult
from tools.tool_runner import ToolRunner
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class ArjunScanner(AbstractTool):
    """
    HTTP parameter discovery using the ``arjun`` binary.

    Writes arjun output to a temporary file (``-o``), runs via
    ``ToolRunner``, then parses the JSON result with ``ArjunParser``
    to produce standardized ``PARAMETER_DISCOVERY`` findings.
    """

    tool_name: str = "arjun"

    def __init__(self, tool_runner: ToolRunner | None = None) -> None:
        self._tool_runner = tool_runner or ToolRunner()

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        target = ctx.target
        timeout = ctx.timeout or 300
        engagement_id = ctx.engagement_id or ""
        aggressiveness = ctx.aggressiveness or "normal"

        slog = ScanLogger(self.tool_name, engagement_id=engagement_id)

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target,
        )

        # Determine thread count based on aggressiveness
        thread_map = {"passive": "10", "normal": "20", "aggressive": "50"}
        threads = thread_map.get(aggressiveness, "20")

        # Write arjun output to a temp file
        fd, output_path = tempfile.mkstemp(
            suffix=".json", prefix=f"arjun_{engagement_id}_"
        )
        os.close(fd)

        try:
            slog.tool_start("arjun", [target])
            args = ["-u", target, "-m", "GET", "-o", output_path, "-t", threads]
            tool_result = self._tool_runner.run("arjun", args, timeout=timeout)

            if not tool_result.success:
                slog.tool_complete("arjun", success=False)
                result.status = ToolStatus.NONZERO_EXIT
                result.stderr = tool_result.stderr
                result.error_message = tool_result.error_message or "arjun failed"
                result.mark_finished()
                return result

            # Read and parse the output file
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                with open(output_path) as f:
                    raw_output = f.read()

                from parsers.parsers.arjun import ArjunParser

                parsed = ArjunParser().parse(raw_output)

                # Normalize findings
                for finding in parsed:
                    finding["source_tool"] = self.tool_name
                result.findings = parsed
                result.status = ToolStatus.SUCCESS
                slog.tool_complete("arjun", success=True, findings=len(parsed))
            else:
                result.status = ToolStatus.SUCCESS_EMPTY
                slog.tool_complete("arjun", success=True, findings=0)

        except Exception as e:
            logger.warning("ArjunScanner failed for %s: %s", target, e)
            result.status = ToolStatus.EXCEPTION
            result.error_message = str(e)
            result.mark_finished()
            return result
        finally:
            # Clean up temp file
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except OSError:
                logger.debug("Failed to remove temp file %s", output_path)

        result.mark_finished()
        return result
