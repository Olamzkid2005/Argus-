"""Tests for tool_core/sandbox.py — AsyncToolRunner."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tool_core.registry import ToolRegistry
from tool_core.result import ToolStatus
from tool_core.sandbox import AsyncToolRunner


class TestAsyncToolRunnerInit:
    def test_default_creates_registry(self):
        runner = AsyncToolRunner()
        assert isinstance(runner.registry, ToolRegistry)
        assert runner._runner is None

    def test_with_custom_registry(self):
        reg = ToolRegistry()
        runner = AsyncToolRunner(registry=reg)
        assert runner.registry is reg


class TestAsyncToolRunnerGetRunner:
    def test_lazy_creation(self):
        runner = AsyncToolRunner()
        with patch("tools.tool_runner.ToolRunner") as mock_tr:
            r = runner._get_runner()
            mock_tr.assert_called_once()
            assert r is mock_tr.return_value

    def test_reuses_existing_runner(self):
        runner = AsyncToolRunner()
        mock_tool_runner = MagicMock()
        runner._runner = mock_tool_runner
        r = runner._get_runner()
        assert r is mock_tool_runner


class TestAsyncToolRunnerRun:
    def test_dangerous_args_raises(self):
        runner = AsyncToolRunner()
        with patch.object(runner, "_get_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_get_runner.return_value = mock_runner
            mock_runner.is_dangerous.return_value = True
            with pytest.raises(Exception) as exc:
                import asyncio
                asyncio.run(runner.run("nuclei", ["-u", "target.com; rm -rf /"]))
            assert "dangerous" in str(exc.value).lower() or "Blocked" in str(exc.value)

    def test_scope_out_of_range_returns_skipped(self):
        runner = AsyncToolRunner(engagement_id="eng-1")
        with patch.object(runner, "_get_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.is_dangerous.return_value = False
            mock_get_runner.return_value = mock_runner
            with patch("tool_core.validators.scope.validate_target_scope", return_value=False):
                import asyncio
                result = asyncio.run(runner.run("nuclei", [], target="https://evil.com"))
                assert result.status == ToolStatus.SKIPPED
                assert "out of scope" in result.error_message

    def test_tool_not_available(self):
        runner = AsyncToolRunner()
        with patch.object(runner, "_get_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.is_dangerous.return_value = False
            mock_runner.is_tool_available.return_value = False  # circuit breaker open
            mock_get_runner.return_value = mock_runner
            with patch("tool_core.validators.scope.validate_target_scope", return_value=True):
                import asyncio

                from tools.circuit_breaker import CircuitOpenError
                with pytest.raises(CircuitOpenError):
                    asyncio.run(runner.run("nuclei", [], target="https://example.com"))

    def test_async_execution(self):
        """Test that run creates an async subprocess and returns result."""
        runner = AsyncToolRunner()
        with patch.object(runner, "_get_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.is_dangerous.return_value = False
            mock_runner.is_tool_available.return_value = True
            mock_runner._resolve_tool_path.return_value = "/usr/bin/echo"
            mock_runner._locked_env.return_value = {"PATH": "/usr/bin"}
            mock_runner._redact_sensitive_args.return_value = (["hello"], {"PATH": "/usr/bin"})
            mock_runner.sandbox_dir = "/tmp"
            mock_get_runner.return_value = mock_runner

            with patch("tool_core.validators.scope.validate_target_scope", return_value=True):
                import asyncio

                # Mock the subprocess execution
                async def mock_run():
                    mock_proc = AsyncMock()
                    mock_proc.communicate.return_value = (b"Hello World", b"")
                    mock_proc.returncode = 0

                    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                        return await runner.run(
                            "echo", ["hello"], target="https://example.com", engagement_id="eng-1",
                        )

                result = asyncio.run(mock_run())
                assert result.stdout == "Hello World"
                assert result.status == ToolStatus.SUCCESS

    def test_timed_out(self):
        runner = AsyncToolRunner()
        with patch.object(runner, "_get_runner") as mock_get_runner:
            mock_runner = MagicMock()
            mock_runner.is_dangerous.return_value = False
            mock_runner.is_tool_available.return_value = True
            mock_runner._resolve_tool_path.return_value = "/usr/bin/sleep"
            mock_runner._locked_env.return_value = {"PATH": "/usr/bin"}
            mock_runner._redact_sensitive_args.return_value = (["100"], {"PATH": "/usr/bin"})
            mock_runner.sandbox_dir = "/tmp"
            mock_get_runner.return_value = mock_runner

            with patch("tool_core.validators.scope.validate_target_scope", return_value=True):
                import asyncio

                async def mock_run():
                    mock_proc = AsyncMock()
                    mock_proc.communicate.side_effect = TimeoutError()

                    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                        with patch("asyncio.wait_for", side_effect=TimeoutError()):
                            result = await runner.run("sleep", ["100"], timeout=0.001)
                            assert result.status == ToolStatus.TIMEOUT
                            return result

                result = asyncio.run(mock_run())
                assert result.status == ToolStatus.TIMEOUT
