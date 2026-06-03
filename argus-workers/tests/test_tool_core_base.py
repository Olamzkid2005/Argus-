"""Tests for tool_core/base.py — AbstractTool, AsyncTool, ToolContext."""

from unittest.mock import MagicMock, patch

import pytest

from tool_core.base import AbstractTool, AsyncTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult


class TestToolContext:
    def test_default_values(self):
        ctx = ToolContext()
        assert ctx.target == ""
        assert ctx.engagement_id == ""
        assert ctx.tech_stack is None
        assert ctx.timeout == 120
        assert ctx.rate_limit == 0.05
        assert ctx.aggressiveness == "normal"
        assert ctx.trace_id is None
        assert ctx.dual_auth is None

    def test_custom_values(self):
        ctx = ToolContext(
            target="https://example.com",
            engagement_id="eng-123",
            tech_stack=["python"],
            timeout=300,
            aggressiveness="aggressive",
            trace_id="trace-1",
        )
        assert ctx.target == "https://example.com"
        assert ctx.engagement_id == "eng-123"
        assert ctx.tech_stack == ["python"]
        assert ctx.timeout == 300


class TestAbstractTool:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AbstractTool()

    def test_concrete_subclass_must_implement_execute(self):
        class MissingExecute(AbstractTool):
            tool_name = "bad"

        with pytest.raises(TypeError):
            MissingExecute()

    def test_concrete_subclass_works(self):
        class MyScanner(AbstractTool):
            tool_name = "my_scanner"

            def execute(self, ctx: ToolContext) -> UnifiedToolResult:
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        scanner = MyScanner()
        assert scanner.tool_name == "my_scanner"

    def test_run_returns_result(self):
        import asyncio

        class MyScanner(AbstractTool):
            tool_name = "my_scanner"

            def execute(self, ctx: ToolContext) -> UnifiedToolResult:
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        scanner = MyScanner()
        ctx = ToolContext(target="https://example.com")
        result = asyncio.run(scanner.run(ctx))
        assert result.tool_name == "my_scanner"
        assert result.target == "https://example.com"

    def test_run_handles_exception(self):
        import asyncio

        class BrokenScanner(AbstractTool):
            tool_name = "broken"

            def execute(self, ctx: ToolContext) -> UnifiedToolResult:
                raise RuntimeError("something broke")

        scanner = BrokenScanner()
        ctx = ToolContext(target="https://example.com")
        result = asyncio.run(scanner.run(ctx))
        assert result.tool_name == "broken"
        assert result.status == ToolStatus.EXCEPTION
        assert "something broke" in result.error_message


class TestAsyncTool:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AsyncTool()

    def test_concrete_subclass_works(self):
        class MyAsyncScanner(AsyncTool):
            tool_name = "async_scanner"

            async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        scanner = MyAsyncScanner()
        assert scanner.tool_name == "async_scanner"

    def test_run_returns_result(self):
        class MyAsyncScanner(AsyncTool):
            tool_name = "async_scanner"

            async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
                result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
                result.status = ToolStatus.SUCCESS
                result.mark_finished()
                return result

        scanner = MyAsyncScanner()
        ctx = ToolContext(target="https://example.com")
        import asyncio
        result = asyncio.run(scanner.run(ctx))
        assert result.tool_name == "async_scanner"
        assert result.status.is_ok

    def test_run_handles_exception(self):
        class BrokenAsyncScanner(AsyncTool):
            tool_name = "broken_async"

            async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
                raise ValueError("async error")

        scanner = BrokenAsyncScanner()
        ctx = ToolContext(target="https://example.com")
        import asyncio
        result = asyncio.run(scanner.run(ctx))
        assert result.status == ToolStatus.EXCEPTION
        assert "async error" in result.error_message
