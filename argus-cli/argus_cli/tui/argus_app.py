"""
Argus TUI — Terminal User Interface.

Built with Textual. Provides a Claude-Code-style experience:
  - Scrollable output area
  - Fixed prompt at bottom
  - Status bar
  - Command handling
  - Streaming output support
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Header,
    Input,
    Label,
    RichLog,
    Static,
    Footer,
)

from argus_cli import __version__
from argus_cli.config.settings import Config
from argus_cli.core.banner import BANNER_COMPACT
from argus_cli.core.runner import SecurityRunner
from argus_cli.commands.registry import CommandRegistry
from argus_cli.tui.widgets import StatusBar, OutputArea, PromptInput


class ArgusTUI(App):
    """
    Main TUI application for Argus CLI.

    Mirrors OpenCode's terminal experience:
      - Scrollable output log
      - Fixed input prompt
      - Status indicators
      - Keyboard shortcuts
    """

    CSS = """
    Screen {
        layout: vertical;
    }

    #header {
        height: 3;
        background: $surface;
        color: $text;
        content-align: center middle;
        text-style: bold;
    }

    #main {
        layout: vertical;
        height: 1fr;
    }

    #output {
        height: 1fr;
        border: solid $primary;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        content-align: left middle;
    }

    #prompt-container {
        height: 3;
        background: $surface;
    }

    #prompt {
        width: 1fr;
    }

    .argus-banner {
        color: $text-accent;
        text-style: bold;
    }

    .command-output {
        color: $text;
    }

    .error-output {
        color: $error;
    }

    .success-output {
        color: $success;
    }

    .dim {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear", "Clear", show=True),
        Binding("up", "history_prev", "Prev", show=False),
        Binding("down", "history_next", "Next", show=False),
        Binding("tab", "complete", "Complete", show=False),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.runner = SecurityRunner(config)
        self.registry = CommandRegistry(config, ui_callback=self._write_output)
        self._history: list[str] = []
        self._history_index: int = 0

    def compose(self) -> ComposeResult:
        """Build the UI layout."""
        yield Static(f"ARGUS v{__version__} — Security AI Agent", id="header")

        with Vertical(id="main"):
            yield OutputArea(id="output")

        yield StatusBar(config=self.config, id="status-bar")

        with Horizontal(id="prompt-container"):
            yield Static("argus>", classes="argus-banner")
            yield PromptInput(id="prompt", placeholder="Type /help for commands...")

        yield Footer()

    def on_mount(self) -> None:
        """Called when app is mounted. Show welcome message."""
        output = self.query_one("#output", OutputArea)
        output.write(BANNER_COMPACT, style="argus-banner")
        output.write("\nWelcome to Argus Security AI Agent.")
        output.write("Type /help for available commands, /quit to exit.\n")
        output.write(f"Config: {self.config.get_summary()}\n")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        value = event.value.strip()
        if not value:
            return

        # Add to history
        self._history.append(value)
        self._history_index = len(self._history)

        # Clear input
        event.input.value = ""

        # Echo command
        output = self.query_one("#output", OutputArea)
        output.write(f"\n[bold cyan]argus>[/bold cyan] {value}\n")

        # Execute command
        self._execute_command(value)

    def _execute_command(self, command: str) -> None:
        """Execute a command and display output."""
        output = self.query_one("#output", OutputArea)

        if command in ("/quit", "/exit", "quit", "exit"):
            output.write("[dim]Goodbye.[/dim]")
            self.exit()
            return

        if command == "/clear":
            output.clear()
            return

        # Route through command registry
        try:
            result = self.registry.execute(command)
            if result:
                self._render_result(result, output)
        except Exception as e:
            output.write(f"[error-output]Error: {e}[/error-output]")

    def _render_result(self, result: dict[str, Any], output: OutputArea) -> None:
        """Render a command result to the output area."""
        if isinstance(result, dict):
            if "error" in result:
                output.write(f"[error-output]Error: {result['error']}[/error-output]")
            elif "status" in result:
                status_color = "success" if result["status"] == "complete" else "dim"
                output.write(f"[{status_color}-output]Status: {result['status']}[/{status_color}-output]")
            elif "message" in result:
                output.write(result["message"])
        else:
            output.write(str(result))

    def _write_output(self, text: str, style: str = "") -> None:
        """Write text to the output area (callback for streaming)."""
        output = self.query_one("#output", OutputArea)
        if style:
            output.write(f"[{style}]{text}[/{style}]")
        else:
            output.write(text)

    def action_clear(self) -> None:
        """Clear the output area."""
        self.query_one("#output", OutputArea).clear()

    def action_history_prev(self) -> None:
        """Navigate to previous history entry."""
        if self._history and self._history_index > 0:
            self._history_index -= 1
            prompt = self.query_one("#prompt", PromptInput)
            prompt.value = self._history[self._history_index]

    def action_history_next(self) -> None:
        """Navigate to next history entry."""
        if self._history and self._history_index < len(self._history) - 1:
            self._history_index += 1
            prompt = self.query_one("#prompt", PromptInput)
            prompt.value = self._history[self._history_index]
        else:
            self._history_index = len(self._history)
            self.query_one("#prompt", PromptInput).value = ""

    def action_complete(self) -> None:
        """Tab completion for commands."""
        prompt = self.query_one("#prompt", PromptInput)
        value = prompt.value
        if value.startswith("/"):
            commands = ["/scan", "/recon", "/auth", "/api", "/report", "/help", "/quit", "/clear"]
            matches = [c for c in commands if c.startswith(value)]
            if len(matches) == 1:
                prompt.value = matches[0] + " "
            elif len(matches) > 1:
                output = self.query_one("#output", OutputArea)
                output.write(f"[dim]{'  '.join(matches)}[/dim]")
