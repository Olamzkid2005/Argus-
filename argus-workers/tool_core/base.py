"""
tool_core/base.py — AbstractTool base class and ToolContext.

Every scanner in Argus implements ``AbstractTool`` (sync) or ``AsyncTool``
(natively async).  The template method ``run()`` wraps ``execute()`` /
``async_execute()`` with timing, logging, and error handling so subclasses
focus only on domain-specific scanning logic.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

from tool_core.config.models import DualAuthConfig
from tool_core.result import UnifiedToolResult


@dataclass
class ToolContext:
    """
    Shared context passed to every tool execution.

    Created by the orchestrator and injected into every ``AbstractTool.run()``
    or ``AsyncTool.run()`` call.
    """

    target: str = ""
    engagement_id: str = ""
    tech_stack: list[str] | None = None
    authorized_scope: str | None = None
    timeout: int = 120
    rate_limit: float = 0.05  # seconds between requests
    aggressiveness: str = "normal"  # "passive", "normal", "aggressive"
    emit_finding: Callable[[str, dict, str], None] | None = None
    trace_id: str | None = None

    # Scanner-specific configs (only used by relevant scanners)
    dual_auth: DualAuthConfig | None = None


class AbstractTool(ABC):
    """
    Base class for all synchronous scanners in Argus.

    Every scanner must implement:
    - ``tool_name: str`` (class variable)
    - ``execute(self, ctx: ToolContext) -> UnifiedToolResult``

    Design principles:
    - All shared orchestration logic (finding emission, logging, timing) lives
      in the ``run()`` template method.
    - Subclasses implement only domain-specific scanning logic in ``execute()``.
    - ``execute()`` is **sync** — HTTP scanners (WebScanner, APIScanner) use
      ``ThreadPoolExecutor`` internally; binary tool execution is delegated to
      ``ToolRunner`` which handles its own async.
    - The ``run()`` template method runs ``execute()`` in a thread pool executor
      so callers always see an async interface.
    """

    tool_name: str = ""  # Override in subclasses

    @abstractmethod
    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Run the scanner against the target.

        Returns a ``UnifiedToolResult`` with findings populated.
        Subclasses should use ``FindingBuilder`` for creating findings.
        This method is **sync**; if you need async, use ``AsyncTool`` instead.
        """
        ...

    async def run(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Template method: wraps ``execute()`` with timing, logging, error handling.

        Runs the sync ``execute()`` in a thread pool executor so callers
        always see an async interface.

        Subclasses should override ``execute()``, **not** ``run()``.
        """
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
            started_at=datetime.now(UTC),
        )

        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.execute, ctx)
        except Exception as e:
            result = UnifiedToolResult.from_exception(
                self.tool_name, [self.tool_name], e, target=ctx.target,
            )
        finally:
            result.mark_finished()

        return result


class AsyncTool(ABC):
    """
    Variant of ``AbstractTool`` for tools that are natively async
    (e.g., WebSocketScanner).

    Subclasses implement ``async_execute()`` instead of ``execute()``.
    The ``run()`` template method provides the same timing, logging, and
    error-handling safety net as ``AbstractTool.run()``, but calls
    ``async_execute()`` directly without a thread pool.

    Usage::

        class WebSocketScanner(AsyncTool):
            tool_name = "websocket_scanner"

            async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
                # ... native async scanning logic ...
    """

    tool_name: str = ""  # Override in subclasses

    @abstractmethod
    async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Async-only variant of ``execute()``.

        Subclasses must implement this as a coroutine function.
        """
        ...

    async def run(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Template method with the same safety net as ``AbstractTool.run()``.

        Times execution, handles exceptions, calls ``mark_finished()``.
        """
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
            started_at=datetime.now(UTC),
        )

        try:
            result = await self.async_execute(ctx)
        except Exception as e:
            result = UnifiedToolResult.from_exception(
                self.tool_name, [self.tool_name], e, target=ctx.target,
            )
        finally:
            result.mark_finished()

        return result
