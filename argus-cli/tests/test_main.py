"""
Tests for the main CLI entry point — edge cases not covered by e2e.

Covers:
  - --target immediate scan mode
  - --no-tui REPL mode
  - --debug flag
  - --api-key from environment
  - KeyboardInterrupt handling
  - _run_immediate_scan and _run_repl helpers
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from argus_cli.main import main, _run_immediate_scan, _run_repl


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


class TestMainDebug:
    """Tests for the --debug flag."""

    def test_debug_flag_sets_env_var(self, cli_runner: CliRunner) -> None:
        """--debug should set ARGUS_DEBUG=1."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("argus_cli.main.Config.load") as mock_load:
                mock_cfg = MagicMock()
                mock_cfg.model = "gpt-4o-mini"
                mock_load.return_value = mock_cfg
                with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                    result = cli_runner.invoke(main, ["--debug", "--target", "test.com"])
                    assert result.exit_code == 0
                    assert "ARGUS_DEBUG" in __import__("os").environ

    def test_debug_no_env_lingers(self, cli_runner: CliRunner) -> None:
        """Without --debug, ARGUS_DEBUG should not be set."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("argus_cli.main.Config.load") as mock_load:
                mock_cfg = MagicMock()
                mock_cfg.model = "gpt-4o-mini"
                mock_load.return_value = mock_cfg
                with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                    cli_runner.invoke(main, ["--target", "test.com"])
                    assert "ARGUS_DEBUG" not in __import__("os").environ


class TestMainApiKey:
    """Tests for --api-key flag."""

    def test_api_key_passed_to_config(self, cli_runner: CliRunner) -> None:
        """--api-key should set config.api_key."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                cli_runner.invoke(main, ["--api-key", "sk-test-key-12345", "--target", "test.com"])
                assert cfg_mock.api_key == "sk-test-key-12345"

    def test_api_key_from_env(self, cli_runner: CliRunner) -> None:
        """API key from ARGUS_API_KEY env var should be used."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch.dict("os.environ", {"ARGUS_API_KEY": "env-key-67890"}, clear=False):
                with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                    cli_runner.invoke(main, ["--target", "test.com"])
                    assert cfg_mock.api_key == "env-key-67890"


class TestMainModel:
    """Tests for --model flag."""

    def test_model_flag_sets_config(self, cli_runner: CliRunner) -> None:
        """--model should set config.model."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                cli_runner.invoke(main, ["--model", "claude-sonnet-4", "--target", "test.com"])
                assert cfg_mock.model == "claude-sonnet-4"


class TestMainTarget:
    """Tests for --target immediate scan mode."""

    def test_target_invokes_scan(self, cli_runner: CliRunner) -> None:
        """--target should trigger immediate scan."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                result = cli_runner.invoke(main, ["--target", "example.com"])
                mock_scan.assert_called_once_with("example.com", cfg_mock, False)
                assert result.exit_code == 0

    def test_target_with_no_tui(self, cli_runner: CliRunner) -> None:
        """--target --no-tui should scan in plain mode."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                result = cli_runner.invoke(main, ["--target", "example.com", "--no-tui"])
                mock_scan.assert_called_once_with("example.com", cfg_mock, True)
                assert result.exit_code == 0

    def test_target_with_model(self, cli_runner: CliRunner) -> None:
        """--target with --model should set model before scanning."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_immediate_scan") as mock_scan:
                cli_runner.invoke(main, ["--model", "claude-sonnet", "--target", "example.com"])
                assert cfg_mock.model == "claude-sonnet"
                mock_scan.assert_called_once_with("example.com", cfg_mock, False)


class TestMainNoTui:
    """Tests for --no-tui flag (REPL mode)."""

    def test_no_tui_launches_repl(self, cli_runner: CliRunner) -> None:
        """--no-tui without --target should launch REPL."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main._run_repl") as mock_repl:
                result = cli_runner.invoke(main, ["--no-tui"])
                mock_repl.assert_called_once_with(cfg_mock)
                assert result.exit_code == 0


class TestRunImmediateScan:
    """Tests for _run_immediate_scan helper."""

    def test_scan_success(self) -> None:
        """_run_immediate_scan should run scan via SecurityRunner."""
        cfg = MagicMock()
        with patch("argus_cli.main.SecurityRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            _run_immediate_scan("test.com", cfg, no_tui=False)
            mock_runner.scan.assert_called_once_with("test.com")

    def test_scan_failure_exits(self) -> None:
        """_run_immediate_scan should exit on scan failure."""
        cfg = MagicMock()
        with patch("argus_cli.main.SecurityRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner.scan.side_effect = RuntimeError("Scan crashed")
            mock_runner_cls.return_value = mock_runner
            with pytest.raises(SystemExit):
                _run_immediate_scan("test.com", cfg, no_tui=False)

    def test_no_tui_prints_banner(self) -> None:
        """_run_immediate_scan with no_tui=True should print banner."""
        cfg = MagicMock()
        with patch("argus_cli.main.SecurityRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            with patch("argus_cli.main.print_banner") as mock_banner:
                _run_immediate_scan("test.com", cfg, no_tui=True)
                mock_banner.assert_called_once()

    def test_no_tui_false_does_not_print_banner(self) -> None:
        """_run_immediate_scan with no_tui=False should not print banner."""
        cfg = MagicMock()
        with patch("argus_cli.main.SecurityRunner") as mock_runner_cls:
            mock_runner = MagicMock()
            mock_runner_cls.return_value = mock_runner
            with patch("argus_cli.main.print_banner") as mock_banner:
                _run_immediate_scan("test.com", cfg, no_tui=False)
                mock_banner.assert_not_called()


class TestRunRepl:
    """Tests for _run_repl helper."""

    def test_repl_prints_banner(self) -> None:
        """_run_repl should print the initial banner."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.print_banner") as mock_banner:
                with patch("argus_cli.main.click.prompt") as mock_prompt:
                    mock_prompt.side_effect = EOFError()
                    _run_repl(cfg)
                    mock_banner.assert_called_once()

    def test_repl_handles_slash_quit(self) -> None:
        """_run_repl should exit on /quit."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.click.prompt") as mock_prompt:
                mock_prompt.side_effect = ["/quit", EOFError()]
                _run_repl(cfg)

    def test_repl_handles_exit(self) -> None:
        """_run_repl should exit on /exit."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.click.prompt") as mock_prompt:
                mock_prompt.side_effect = ["/exit", EOFError()]
                _run_repl(cfg)

    def test_repl_handles_bare_quit(self) -> None:
        """_run_repl should exit on bare 'quit'."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.click.prompt") as mock_prompt:
                mock_prompt.side_effect = ["quit", EOFError()]
                _run_repl(cfg)

    def test_repl_handles_empty_input(self) -> None:
        """_run_repl should skip empty input."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.click.prompt") as mock_prompt:
                mock_prompt.side_effect = ["", "/scan test.com", "/quit", EOFError()]
                _run_repl(cfg)
                # Should only execute the non-empty command, skip empty
                assert mock_reg.execute.call_count == 1

    def test_repl_delegates_to_registry(self) -> None:
        """_run_repl should delegate commands to CommandRegistry."""
        cfg = MagicMock()
        with patch("argus_cli.main.CommandRegistry") as mock_reg_cls:
            mock_reg = MagicMock()
            mock_reg_cls.return_value = mock_reg
            with patch("argus_cli.main.click.prompt") as mock_prompt:
                mock_prompt.side_effect = ["/scan test.com", "/quit", EOFError()]
                _run_repl(cfg)
                mock_reg.execute.assert_any_call("/scan test.com")


class TestMainKeyboardInterrupt:
    """Tests for KeyboardInterrupt handling."""

    def test_tui_keyboard_interrupt(self, cli_runner: CliRunner) -> None:
        """KeyboardInterrupt during TUI should exit gracefully."""
        cfg_mock = MagicMock()
        cfg_mock.model = "gpt-4o-mini"
        with patch("argus_cli.main.Config.load") as mock_load:
            mock_load.return_value = cfg_mock
            with patch("argus_cli.main.ArgusTUI") as mock_tui:
                mock_app = MagicMock()
                mock_app.run.side_effect = KeyboardInterrupt()
                mock_tui.return_value = mock_app
                result = cli_runner.invoke(main, [])
                assert result.exit_code == 0
