"""Tests that errors are logged instead of silently swallowed."""
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


class TestErrorLogging:
    """Verify that operational paths log warnings instead of crashing or silently swallowing errors."""

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_missing_tool_logs_warning(self, mock_is_enabled):
        """Missing tools should produce warning logs, not silent failures."""
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": False, "nmap": False}
        )

        with patch("tools.port_scanner.logger") as mock_logger:
            result = scanner.scan("example.com")

        assert mock_logger.warning.called
        assert result.open_ports == []

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_returns_empty_on_missing_naabu(self, mock_is_enabled):
        """When naabu is unavailable, scan returns empty result without crashing."""
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": False, "nmap": False}
        )

        result = scanner.scan("example.com")

        assert isinstance(result.open_ports, list)
        assert result.target == "example.com"

    @patch("tools.port_scanner.is_enabled", return_value=True)
    def test_port_scanner_continues_without_nmap(self, mock_is_enabled):
        """When only nmap is missing, scan should still return naabu results."""
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock(
            return_value={"naabu": True, "nmap": False}
        )
        scanner._parse_naabu_ports = MagicMock(
            return_value=[{"port": 80, "protocol": "tcp"}]
        )

        with patch("tools.port_scanner.logger") as mock_logger:
            result = scanner.scan("example.com")

        assert mock_logger.warning.called
        assert len(result.open_ports) == 1
        assert result.open_ports[0].port == 80

    @patch("tools.port_scanner.is_enabled", return_value=False)
    def test_port_scanner_disabled_flag(self, mock_is_enabled):
        """When PORT_SCANNER feature flag is off, scan returns empty without checking tools."""
        from tools.port_scanner import PortScanner

        scanner = PortScanner()
        scanner._check_tools_available = MagicMock()

        with patch("tools.port_scanner.logger") as mock_logger:
            result = scanner.scan("example.com")

        assert mock_logger.info.called
        assert mock_logger.warning.called is False
        assert result.open_ports == []
        scanner._check_tools_available.assert_not_called()
