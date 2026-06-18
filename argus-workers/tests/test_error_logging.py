"""Tests that errors are logged instead of silently swallowed."""

from unittest.mock import MagicMock, patch


class TestErrorLogging:
    """Verify that operational paths log warnings instead of crashing or silently swallowing errors."""

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_missing_tool_logs_warning(self, _mock_is_enabled):
        """Missing tools should produce warning logs, not silent failures."""
        from tool_core.base import ToolContext
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": False, "nmap": False}
        )

        with patch("tools.port_scanner.logger") as mock_logger:
            ctx = ToolContext(target="example.com")
            result = scanner.execute(ctx)

        assert mock_logger.warning.called
        assert result.ports == []

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_returns_empty_on_missing_naabu(self, _mock_is_enabled):
        """When naabu is unavailable, scan returns empty result without crashing."""
        from tool_core.base import ToolContext
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": False, "nmap": False}
        )

        ctx = ToolContext(target="example.com")
        result = scanner.execute(ctx)

        assert isinstance(result.ports, list)
        assert result.target == "example.com"

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_continues_without_nmap(self, _mock_is_enabled):
        """When only nmap is missing, scan should still return naabu results."""
        from tool_core.base import ToolContext
        from tool_core.result import ToolStatus, UnifiedToolResult
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        naabu_result = UnifiedToolResult(
            tool_name="naabu",
            status=ToolStatus.SUCCESS,
            stdout='{"port":80,"protocol":"tcp"}\n',
        )
        scanner._tool_runner = MagicMock()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": True, "nmap": False}
        )
        scanner._tool_runner.run.return_value = naabu_result

        ctx = ToolContext(target="example.com")
        result = scanner.execute(ctx)

        assert len(result.ports) == 1
        assert result.ports[0]["port"] == 80

    @patch("tools.port_scanner.is_enabled", return_value=False)
    def test_port_scanner_disabled_flag(self, _mock_is_enabled):
        """When PORT_SCANNER feature flag is off, scan returns empty without checking tools."""
        from tool_core.base import ToolContext
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock()

        with patch("tools.port_scanner.logger") as mock_logger:
            ctx = ToolContext(target="example.com")
            result = scanner.execute(ctx)

        assert mock_logger.info.called
        assert mock_logger.warning.called is False
        assert result.ports == []
        scanner._check_tools_available.assert_not_called()
