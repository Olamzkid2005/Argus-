"""
Custom widgets for Argus TUI.

Provides:
  - OutputArea: Scrollable output with Rich formatting
  - StatusBar: Bottom status bar
  - PromptInput: Enhanced input with history
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Label, RichLog, Input, Static

from argus_cli.config.settings import Config


class OutputArea(RichLog):
    """
    Scrollable output area for command results and tool output.

    Wraps RichLog with convenience methods for styled output.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.auto_scroll = True
        self.markup = True
        self.highlight = True
        self.wrap = True

    def write_banner(self, text: str) -> None:
        """Write the Argus banner."""
        self.write(text, style="bold bright_cyan")

    def write_command(self, command: str) -> None:
        """Write a command echo."""
        self.write(f"[bold cyan]argus>[/bold cyan] {command}")

    def write_success(self, text: str) -> None:
        """Write success message."""
        self.write(f"[bold green]✓[/bold green] {text}")

    def write_error(self, text: str) -> None:
        """Write error message."""
        self.write(f"[bold red]✗[/bold red] {text}")

    def write_warning(self, text: str) -> None:
        """Write warning message."""
        self.write(f"[bold yellow]⚠[/bold yellow] {text}")

    def write_info(self, text: str) -> None:
        """Write info message."""
        self.write(f"[blue]ℹ[/blue] {text}")

    def write_tool_output(self, tool: str, output: str) -> None:
        """Write tool execution output."""
        self.write(f"[dim]─── {tool} ───[/dim]")
        for line in output.splitlines()[:50]:  # Limit output
            self.write(f"  {line}")
        self.write("")

    def write_stream_chunk(self, text: str) -> None:
        """Write a streaming chunk (for real-time tool output)."""
        self.write(text, scroll_end=True)


class StatusBar(Static):
    """
    Bottom status bar showing current state.

    Displays: model, provider, engagement status, phase.
    """

    config: reactive[Config | None] = reactive(None)
    status: reactive[str] = reactive("ready")
    phase: reactive[str] = reactive("idle")

    def __init__(self, config: Config, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = config
        self.update_status()

    def watch_status(self, status: str) -> None:
        """React to status changes."""
        self.update_status()

    def watch_phase(self, phase: str) -> None:
        """React to phase changes."""
        self.update_status()

    def update_status(self) -> None:
        """Update the status bar display."""
        if self.config is None:
            self.update("Argus — Ready")
            return

        model = self.config.model
        provider = self.config.provider
        key_status = "●" if self.config.api_key else "○"

        status_text = (
            f"[bold]{self.status.upper()}[/bold] | "
            f"Model: {model} ({provider}) {key_status} | "
            f"Phase: {self.phase} | "
            f"Press Ctrl+C to quit"
        )
        self.update(status_text)


class PromptInput(Input):
    """
    Enhanced input widget with command history support.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.placeholder = kwargs.get("placeholder", "Type command...")

    def on_key(self, event) -> None:
        """Handle special key presses."""
        pass  # Key handling is done at app level
