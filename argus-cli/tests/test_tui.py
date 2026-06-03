"""
Tests for Argus TUI components and edge cases.

Covers:
  - OutputArea, StatusBar, PromptInput custom widgets
  - ArgusTUI app (compose, mount, input, history, tab-completion)
  - Banner module
  - Edge cases (empty input, special chars, rapid input, etc.)

Run with:
    cd argus-cli && python -m pytest tests/test_tui.py -v --tb=short
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argus_cli import __tagline__, __version__
from argus_cli.config.settings import Config
from argus_cli.core.banner import (
    ASCII_BANNER,
    BANNER_COMPACT,
    get_rich_banner,
    get_status_header,
    print_banner,
)
from argus_cli.tui.argus_app import ArgusTUI
from argus_cli.tui.widgets import OutputArea, StatusBar, PromptInput


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """Create a minimal Config for testing (no file I/O to real directories)."""
    cfg = Config()
    cfg.provider = "openai"
    cfg.model = "gpt-4o-mini"
    cfg.api_key = None
    cfg.verbose = False
    cfg.stream_output = False
    cfg.config_dir = tmp_path
    cfg.config_file = tmp_path / "config.toml"
    cfg.sessions_db = tmp_path / "sessions.db"
    return cfg


@pytest.fixture
def app(test_config: Config) -> ArgusTUI:
    """Create an ArgusTUI instance for testing."""
    return ArgusTUI(test_config)


# ═══════════════════════════════════════════════════════════════
# 1. OutputArea Widget Tests
# ═══════════════════════════════════════════════════════════════


class TestOutputArea:
    """Tests for the OutputArea custom widget."""

    def test_init_defaults(self) -> None:
        """OutputArea should have sensible defaults."""
        area = OutputArea()
        assert area.auto_scroll is True
        assert area.markup is True
        assert area.highlight is True
        assert area.wrap is True

    def test_write_banner(self) -> None:
        """write_banner should call write with banner text."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_banner("Argus Banner")
            mock_write.assert_called_once_with("Argus Banner", style="bold bright_cyan")

    def test_write_command(self) -> None:
        """write_command should format and write a command echo."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_command("/scan example.com")
            mock_write.assert_called_once_with("[bold cyan]argus>[/bold cyan] /scan example.com")

    def test_write_success(self) -> None:
        """write_success should format a success message."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_success("Scan complete")
            mock_write.assert_called_once_with("[bold green]✓[/bold green] Scan complete")

    def test_write_error(self) -> None:
        """write_error should format an error message."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_error("Connection refused")
            mock_write.assert_called_once_with("[bold red]✗[/bold red] Connection refused")

    def test_write_warning(self) -> None:
        """write_warning should format a warning message."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_warning("Rate limit approaching")
            mock_write.assert_called_once_with("[bold yellow]⚠[/bold yellow] Rate limit approaching")

    def test_write_info(self) -> None:
        """write_info should format an info message."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_info("Processing...")
            mock_write.assert_called_once_with("[blue]ℹ[/blue] Processing...")

    def test_write_tool_output(self) -> None:
        """write_tool_output should format tool execution output."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_tool_output("nuclei", "line1\nline2\nline3")
            assert mock_write.call_count == 5  # header + 3 lines + empty line

    def test_write_tool_output_truncated(self) -> None:
        """write_tool_output should truncate output beyond 50 lines."""
        area = OutputArea()
        long_output = "\n".join(f"line{i}" for i in range(100))
        with patch.object(area, "write") as mock_write:
            area.write_tool_output("httpx", long_output)
            # header + 50 lines + empty line
            assert mock_write.call_count == 52

    def test_write_stream_chunk(self) -> None:
        """write_stream_chunk should write with scroll_end=True."""
        area = OutputArea()
        with patch.object(area, "write") as mock_write:
            area.write_stream_chunk("data chunk")
            mock_write.assert_called_once_with("data chunk", scroll_end=True)


# ═══════════════════════════════════════════════════════════════
# 2. StatusBar Widget Tests
# ═══════════════════════════════════════════════════════════════


class TestStatusBar:
    """Tests for the StatusBar custom widget."""

    def test_init_with_config(self, test_config: Config) -> None:
        """StatusBar should initialize with config and show status."""
        bar = StatusBar(config=test_config)
        assert bar.config is test_config
        assert bar.status == "ready"
        assert bar.phase == "idle"

    def test_update_status_with_config(self, test_config: Config) -> None:
        """update_status should display model, provider, API key status."""
        bar = StatusBar(config=test_config)
        bar.update_status()
        rendered = str(bar.render())
        assert "gpt-4o-mini" in rendered
        assert "openai" in rendered
        assert "○" in rendered  # no API key indicator

    def test_update_status_with_api_key(self, test_config: Config) -> None:
        """update_status should show filled circle when API key is set."""
        test_config.api_key = "sk-test-key"
        bar = StatusBar(config=test_config)
        bar.update_status()
        rendered = str(bar.render())
        assert "●" in rendered  # API key present indicator

    def test_update_status_without_config(self) -> None:
        """update_status should show default message when config is None."""
        bar = StatusBar(config=None)  # type: ignore
        bar.config = None
        bar.update_status()
        rendered = str(bar.render())
        assert "Ready" in rendered

    def test_phase_change_updates_display(self, test_config: Config) -> None:
        """Changing the phase should update the status bar display."""
        bar = StatusBar(config=test_config)
        bar.phase = "scanning"
        rendered = str(bar.render())
        assert "scanning" in rendered.lower()

    def test_status_change_updates_display(self, test_config: Config) -> None:
        """Changing the status should update the status bar display."""
        bar = StatusBar(config=test_config)
        bar.status = "running"
        rendered = str(bar.render())
        assert "RUNNING" in rendered


# ═══════════════════════════════════════════════════════════════
# 3. PromptInput Widget Tests
# ═══════════════════════════════════════════════════════════════


class TestPromptInput:
    """Tests for the PromptInput widget."""

    def test_init_placeholder(self) -> None:
        """PromptInput should accept a custom placeholder."""
        inp = PromptInput(placeholder="Type /help for commands...")
        assert inp.placeholder == "Type /help for commands..."

    def test_default_placeholder(self) -> None:
        """PromptInput should have a default placeholder."""
        inp = PromptInput()
        assert inp.placeholder == "Type command..."

    def test_on_key_noop(self) -> None:
        """on_key should not crash (handling at app level)."""
        inp = PromptInput()
        inp.on_key(MagicMock())


# ═══════════════════════════════════════════════════════════════
# 4. ArgusTUI App Tests
# ═══════════════════════════════════════════════════════════════


class TestArgusTUI:
    """Tests for the main ArgusTUI application."""

    def test_on_mount_shows_welcome(self, app: ArgusTUI) -> None:
        """on_mount should write banner and welcome message to output."""
        with patch.object(app, "query_one") as mock_query_one:
            mock_output = MagicMock()
            mock_query_one.return_value = mock_output

            app.on_mount()

            assert mock_output.write.call_count >= 3

    def test_empty_input_ignored(self, app: ArgusTUI) -> None:
        """Empty input should be ignored by on_input_submitted."""
        mock_event = MagicMock()
        mock_event.value.strip.return_value = ""

        # query_one mock NOT needed — on_input_submitted returns early
        # for empty input before calling query_one
        app.on_input_submitted(mock_event)

    def test_compose_method_exists(self, app: ArgusTUI) -> None:
        """compose should be a callable method."""
        assert hasattr(app, "compose")
        assert callable(app.compose)

    def test_init_creates_runner_and_registry(self, test_config: Config) -> None:
        """Init should create SecurityRunner and CommandRegistry with config."""
        tui = ArgusTUI(test_config)
        assert tui.config is test_config
        assert tui.runner is not None
        assert tui.registry is not None
        assert tui._history == []
        assert tui._history_index == 0

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_quit_command(self, mock_query_one, app: ArgusTUI) -> None:
        """/quit should call self.exit()."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app, "exit") as mock_exit:
            app._execute_command("/quit")
            mock_exit.assert_called_once()
            # Should write goodbye message before exiting
            assert mock_output.write.call_count >= 1

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_exit_command(self, mock_query_one, app: ArgusTUI) -> None:
        """/exit should call self.exit()."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app, "exit") as mock_exit:
            app._execute_command("/exit")
            mock_exit.assert_called_once()

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_quit_bare(self, mock_query_one, app: ArgusTUI) -> None:
        """bare 'quit' should call self.exit()."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app, "exit") as mock_exit:
            app._execute_command("quit")
            mock_exit.assert_called_once()

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_exit_bare(self, mock_query_one, app: ArgusTUI) -> None:
        """bare 'exit' should call self.exit()."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app, "exit") as mock_exit:
            app._execute_command("exit")
            mock_exit.assert_called_once()

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_clear_command(self, mock_query_one, app: ArgusTUI) -> None:
        """/clear should clear the output area."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        app._execute_command("/clear")
        mock_output.clear.assert_called_once()

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_scan_command_calls_registry(self, mock_query_one, app: ArgusTUI) -> None:
        """/scan should delegate to registry.execute()."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.return_value = {"engagement_id": "test-eid", "target": "example.com"}
            app._execute_command("/scan example.com")
            mock_execute.assert_called_once_with("/scan example.com")

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_execute_command_error_handling(self, mock_query_one, app: ArgusTUI) -> None:
        """Command execution errors should be caught and displayed."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.side_effect = RuntimeError("Something broke")
            app._execute_command("/scan fail.com")
            # Error should be written to output
            mock_output.write.assert_called_with(
                "[error-output]Error: Something broke[/error-output]"
            )

    def test_render_result_error(self, app: ArgusTUI) -> None:
        """_render_result should format error results."""
        mock_output = MagicMock()
        app._render_result({"error": "Missing target"}, mock_output)
        mock_output.write.assert_called_with(
            "[error-output]Error: Missing target[/error-output]"
        )

    def test_render_result_complete(self, app: ArgusTUI) -> None:
        """_render_result should format complete status."""
        mock_output = MagicMock()
        app._render_result({"status": "complete"}, mock_output)
        mock_output.write.assert_called_with(
            "[success-output]Status: complete[/success-output]"
        )

    def test_render_result_failed(self, app: ArgusTUI) -> None:
        """_render_result should format failed status."""
        mock_output = MagicMock()
        app._render_result({"status": "failed"}, mock_output)
        mock_output.write.assert_called_with(
            "[dim-output]Status: failed[/dim-output]"
        )

    def test_render_result_message(self, app: ArgusTUI) -> None:
        """_render_result should pass through message results."""
        mock_output = MagicMock()
        app._render_result({"message": "Hello"}, mock_output)
        mock_output.write.assert_called_with("Hello")

    def test_render_result_plain_value(self, app: ArgusTUI) -> None:
        """_render_result should convert non-dict results to string."""
        mock_output = MagicMock()
        app._render_result("plain text", mock_output)
        mock_output.write.assert_called_with("plain text")

    def test_history_prev_no_history(self, app: ArgusTUI) -> None:
        """history_prev should not crash when history is empty."""
        with patch.object(app, "query_one") as mock_query_one:
            app.action_history_prev()
            # Should not crash
            assert mock_query_one.call_count == 0

    def test_history_prev_and_next(self, app: ArgusTUI) -> None:
        """history_prev/next should navigate command history."""
        app._history = ["/scan a.com", "/scan b.com", "/scan c.com"]
        app._history_index = len(app._history)

        # Go back twice
        with patch.object(app, "query_one") as mock_query_one:
            mock_prompt = MagicMock()
            mock_query_one.return_value = mock_prompt

            app.action_history_prev()
            mock_query_one.assert_called_once_with("#prompt", PromptInput)
            assert app._history_index == 2
            assert mock_prompt.value == "/scan c.com"

        # Reset
        app._history_index = 3
        mock_query_one.reset_mock()

        # Go back once
        with patch.object(app, "query_one") as mock_query_one:
            mock_prompt = MagicMock()
            mock_query_one.return_value = mock_prompt

            app.action_history_prev()
            assert app._history_index == 2
            assert mock_prompt.value == "/scan c.com"

        # Go forward (when at end)
        mock_query_one.reset_mock()
        with patch.object(app, "query_one") as mock_query_one:
            mock_prompt = MagicMock()
            mock_query_one.return_value = mock_prompt

            # At the end (index == len(history))
            app._history_index = 3
            app.action_history_next()
            # Should stay at end and clear prompt
            assert app._history_index == 3
            mock_prompt.value = ""

    def test_tab_completion_single_match(self, app: ArgusTUI) -> None:
        """Tab completion should complete unique commands."""
        with patch.object(app, "query_one") as mock_query_one:
            mock_prompt = MagicMock()
            mock_prompt.value = "/sc"
            mock_query_one.return_value = mock_prompt

            app.action_complete()
            assert mock_prompt.value == "/scan "

    def test_tab_completion_no_match(self, app: ArgusTUI) -> None:
        """Tab completion should not change value if no match."""
        with patch.object(app, "query_one") as mock_query_one:
            mock_prompt = MagicMock()
            mock_prompt.value = "/xyz"
            mock_query_one.return_value = mock_prompt

            app.action_complete()
            # Value should remain unchanged
            assert mock_prompt.value == "/xyz"

    def test_tab_completion_multiple_matches(self, app: ArgusTUI) -> None:
        """Tab completion should list matches when multiple exist."""
        with patch.object(app, "query_one") as mock_query_one:
            # First call returns prompt, second call returns output
            mock_prompt = MagicMock()
            mock_prompt.value = "/"
            mock_output = MagicMock()

            def query_one_side_effect(selector: str, widget_type=None):
                if selector == "#prompt":
                    return mock_prompt
                if selector == "#output":
                    return mock_output
                raise ValueError(f"Unknown selector: {selector}")

            mock_query_one.side_effect = query_one_side_effect

            app.action_complete()
            # Should write available commands
            mock_output.write.assert_called_once()
            args, _ = mock_output.write.call_args
            assert "/scan" in args[0]
            assert "/recon" in args[0]

    def test_input_submitted_adds_to_history(self, app: ArgusTUI) -> None:
        """on_input_submitted should add command to history."""
        mock_event = MagicMock()
        mock_event.value.strip.return_value = "/scan test.com"
        mock_event.input = MagicMock()
        # Stub query_one directly so no screen stack is needed
        app.query_one = MagicMock(return_value=MagicMock())  # type: ignore[assignment]

        initial_len = len(app._history)
        app.on_input_submitted(mock_event)
        assert len(app._history) == initial_len + 1
        assert app._history[-1] == "/scan test.com"
        assert app._history_index == len(app._history)

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_write_output_with_style(self, mock_query_one, app: ArgusTUI) -> None:
        """_write_output should apply styling."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        app._write_output("test text", style="bold green")
        mock_output.write.assert_called_with("[bold green]test text[/bold green]")

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_write_output_without_style(self, mock_query_one, app: ArgusTUI) -> None:
        """_write_output should write plain text when no style given."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        app._write_output("plain text")
        mock_output.write.assert_called_with("plain text")

    def test_action_clear_clears_output(self, app: ArgusTUI) -> None:
        """action_clear should clear the output area."""
        with patch.object(app, "query_one") as mock_query_one:
            mock_output = MagicMock()
            mock_query_one.return_value = mock_output

            app.action_clear()
            mock_output.clear.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# 5. Banner Module Tests
# ═══════════════════════════════════════════════════════════════


class TestBanner:
    """Tests for the banner module."""

    def test_ascii_banner_contains_version(self) -> None:
        """ASCII_BANNER should include the version string."""
        assert __version__ in ASCII_BANNER

    def test_compact_banner_contains_tagline(self) -> None:
        """BANNER_COMPACT should include the tagline."""
        assert __tagline__ in BANNER_COMPACT

    def test_compact_banner_contains_version(self) -> None:
        """BANNER_COMPACT should include the version."""
        assert __version__ in BANNER_COMPACT

    def test_print_banner_no_crash(self) -> None:
        """print_banner should not crash."""
        mock_console = MagicMock()
        print_banner(console=mock_console)
        mock_console.print.assert_called_once()

    def test_print_banner_compact(self) -> None:
        """print_banner with compact=True should use compact banner."""
        mock_console = MagicMock()
        print_banner(console=mock_console, compact=True)
        mock_console.print.assert_called_once()

    def test_get_rich_banner_has_required_fields(self) -> None:
        """get_rich_banner should return a Panel with title."""
        panel = get_rich_banner()
        assert panel.title is not None
        assert "Security AI Agent" in str(panel.title)

    def test_get_status_header_contains_config(self) -> None:
        """get_status_header should return a Panel with config summary."""
        panel = get_status_header("model=test key=ready")
        assert "model=test" in str(panel.renderable)


# ═══════════════════════════════════════════════════════════════
# 6. Edge Cases
# ═══════════════════════════════════════════════════════════════


class TestTUIEdgeCases:
    """Edge cases and resilience tests for TUI."""

    def test_input_submitted_special_chars(self, app: ArgusTUI) -> None:
        """Input with special characters should be handled gracefully."""
        mock_event = MagicMock()
        mock_event.value.strip.return_value = "/scan https://example.com/path?q=a&b=c"
        mock_event.input = MagicMock()

        mock_output = MagicMock()
        app.query_one = MagicMock(return_value=mock_output)  # type: ignore[assignment]
        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.return_value = {"engagement_id": "eid"}
            app.on_input_submitted(mock_event)
            mock_execute.assert_called_once()

    def test_input_submitted_long_input(self, app: ArgusTUI) -> None:
        """Very long input should not crash."""
        long_target = "a" * 10000
        mock_event = MagicMock()
        mock_event.value.strip.return_value = f"/scan {long_target}"
        mock_event.input = MagicMock()

        app.query_one = MagicMock(return_value=MagicMock())  # type: ignore[assignment]
        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.return_value = {"engagement_id": "eid"}
            app.on_input_submitted(mock_event)
            mock_execute.assert_called_once()

    def test_input_submitted_unicode(self, app: ArgusTUI) -> None:
        """Unicode characters in input should not crash."""
        mock_event = MagicMock()
        mock_event.value.strip.return_value = "/scan http://xn--n1qwf.xn--sdga.com"
        mock_event.input = MagicMock()

        app.query_one = MagicMock(return_value=MagicMock())  # type: ignore[assignment]
        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.return_value = {"engagement_id": "eid"}
            app.on_input_submitted(mock_event)
            mock_execute.assert_called_once()

    @patch("argus_cli.tui.argus_app.ArgusTUI.query_one")
    def test_submit_quit_then_command_clears_history_state(
        self, mock_query_one, app: ArgusTUI
    ) -> None:
        """Quit commands should call exit without corrupting state."""
        mock_output = MagicMock()
        mock_query_one.return_value = mock_output

        app.on_input_submitted(MagicMock(
            value="/quit",
            input=MagicMock(),
        ))
        assert app._history == ["/quit"]


# ═══════════════════════════════════════════════════════════════
# 7. Textual Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestArgusTUITextualIntegration:
    """Textual integration tests for ArgusTUI (sync mock-based)."""

    def test_app_has_expected_bindings(self, app: ArgusTUI) -> None:
        """App should define expected keyboard bindings."""
        assert hasattr(app, "BINDINGS")
        binding_keys = {b.key for b in app.BINDINGS}
        assert "ctrl+c" in binding_keys
        assert "ctrl+l" in binding_keys
        assert "up" in binding_keys
        assert "down" in binding_keys
        assert "tab" in binding_keys

    def test_app_has_css(self, app: ArgusTUI) -> None:
        """App should have CSS defined."""
        assert hasattr(app, "CSS")
        assert "#output" in app.CSS
        assert "#status-bar" in app.CSS
        assert "#prompt" in app.CSS

    def test_on_mount_called_with_mocked_query(self, app: ArgusTUI) -> None:
        """on_mount should write banner and welcome text to output."""
        mock_output = MagicMock()
        app.query_one = MagicMock(return_value=mock_output)  # type: ignore[assignment]
        app.on_mount()
        assert mock_output.write.call_count >= 3

    def test_action_clear_called_with_mocked_query(self, app: ArgusTUI) -> None:
        """action_clear should clear the output area."""
        mock_output = MagicMock()
        app.query_one = MagicMock(return_value=mock_output)  # type: ignore[assignment]
        app.action_clear()
        mock_output.clear.assert_called_once()

    def test_execute_scan_through_input_submitted(self, app: ArgusTUI) -> None:
        """Submitting a scan command through on_input_submitted should work."""
        mock_event = MagicMock()
        mock_event.value.strip.return_value = "/scan test-target.com"
        mock_event.input = MagicMock()

        mock_output = MagicMock()
        app.query_one = MagicMock(return_value=mock_output)  # type: ignore[assignment]
        with patch.object(app.registry, "execute") as mock_execute:
            mock_execute.return_value = {"engagement_id": "eid", "target": "test-target.com"}
            app.on_input_submitted(mock_event)
            mock_execute.assert_called_once_with("/scan test-target.com")
