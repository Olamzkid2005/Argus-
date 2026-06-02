"""
Command Registry — interactive slash commands.

Registers all CLI commands:
  /scan, /recon, /auth, /api, /report, /help, /quit, /clear,
  /status, /config, /model, /providers, /sessions

Mirrors OpenCode's command palette with security-specific commands.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from rich.console import Console
from rich.table import Table

from argus_cli.config.settings import Config
from argus_cli.core.constants import PHASES, PROVIDERS
from argus_cli.core.providers import get_provider_for_model, resolve_provider
from argus_cli.core.runner import SecurityRunner
from argus_cli.session.manager import SessionManager

logger = logging.getLogger(__name__)
console = Console()


class CommandRegistry:
    """
    Registry for all interactive CLI commands.

    Usage:
        registry = CommandRegistry(config)
        result = registry.execute("/scan example.com")
    """

    def __init__(
        self,
        config: Config,
        ui_callback: Callable[[str, str], None] | None = None,
    ) -> None:
        self.config = config
        self.runner = SecurityRunner(config)
        self.sessions = SessionManager(config)
        self._ui = ui_callback
        self._commands: dict[str, Callable[..., dict[str, Any]]] = {
            "/help": self.cmd_help,
            "/scan": self.cmd_scan,
            "/recon": self.cmd_recon,
            "/auth": self.cmd_auth,
            "/api": self.cmd_api,
            "/report": self.cmd_report,
            "/status": self.cmd_status,
            "/config": self.cmd_config,
            "/model": self.cmd_model,
            "/providers": self.cmd_providers,
            "/sessions": self.cmd_sessions,
            "/clear": self.cmd_clear,
            "/quit": self.cmd_quit,
            "/exit": self.cmd_quit,
        }

    def execute(self, user_input: str) -> dict[str, Any] | None:
        """
        Parse and execute a command.

        Args:
            user_input: Raw user input (e.g., "/scan example.com")

        Returns:
            Command result dict or None
        """
        user_input = user_input.strip()
        if not user_input:
            return None

        # Parse command and args
        if user_input.startswith("/"):
            parts = user_input[1:].split(maxsplit=1)
            cmd_name = "/" + parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
        else:
            # Treat bare input as a scan command
            cmd_name = "/scan"
            args = user_input

        handler = self._commands.get(cmd_name)
        if handler:
            return handler(args)
        else:
            console.print(f"[red]Unknown command: {cmd_name}[/red]")
            console.print("Type /help for available commands.")
            return {"error": f"Unknown command: {cmd_name}"}

    def _write(self, text: str, style: str = "") -> None:
        """Write output via UI callback or console."""
        if self._ui:
            self._ui(text, style)
        else:
            if style:
                console.print(f"[{style}]{text}[/{style}]")
            else:
                console.print(text)

    # ═══════════════════════════════════════════════════════════
    # Command Handlers
    # ═══════════════════════════════════════════════════════════

    def cmd_help(self, _args: str = "") -> dict[str, Any]:
        """Show help information."""
        table = Table(title="Argus Commands", show_lines=True)
        table.add_column("Command", style="bold cyan", no_wrap=True)
        table.add_column("Description", style="white")
        table.add_column("Example", style="dim")

        commands = [
            ("/scan <target>", "Run full security scan", "/scan example.com"),
            ("/recon <target>", "Run reconnaissance only", "/recon example.com"),
            ("/auth <target>", "Test authentication mechanisms", "/auth example.com"),
            ("/api <target>", "Test API security (BOLA/BOPLA)", "/api api.example.com"),
            ("/report", "Generate security report", "/report"),
            ("/status", "Show current engagement status", "/status"),
            ("/config", "Show current configuration", "/config"),
            ("/model <name>", "Change AI model", "/model claude-sonnet"),
            ("/providers", "List available model providers", "/providers"),
            ("/sessions", "List saved sessions", "/sessions"),
            ("/clear", "Clear the screen", "/clear"),
            ("/quit", "Exit Argus", "/quit"),
        ]

        for cmd, desc, example in commands:
            table.add_row(cmd, desc, example)

        console.print(table)

        console.print("\n[bold]Keyboard Shortcuts:[/bold]")
        console.print("  [dim]Ctrl+C[/dim]  Quit")
        console.print("  [dim]Ctrl+L[/dim]  Clear screen")
        console.print("  [dim]↑/↓[/dim]    Command history")
        console.print("  [dim]Tab[/dim]     Command completion")

        return {"message": "Help displayed"}

    def cmd_scan(self, args: str) -> dict[str, Any]:
        """Run a full security scan."""
        if not args:
            console.print("[yellow]Usage: /scan <target>[/yellow]")
            return {"error": "Missing target"}

        target = args.strip()
        console.print(f"[bold]Scanning {target}...[/bold]")

        if not self.config.is_enabled("planner"):
            console.print("[yellow]Planner disabled — running deterministic workflow[/yellow]")

        return self.runner.scan(target)

    def cmd_recon(self, args: str) -> dict[str, Any]:
        """Run reconnaissance only."""
        if not args:
            console.print("[yellow]Usage: /recon <target>[/yellow]")
            return {"error": "Missing target"}

        target = args.strip()
        console.print(f"[bold]Reconnaissance: {target}[/bold]")
        return self.runner.recon(target)

    def cmd_auth(self, args: str) -> dict[str, Any]:
        """Test authentication mechanisms."""
        if not args:
            console.print("[yellow]Usage: /auth <target>[/yellow]")
            return {"error": "Missing target"}

        target = args.strip()
        console.print(f"[bold]Auth testing: {target}[/bold]")
        return self.runner.auth_test(target)

    def cmd_api(self, args: str) -> dict[str, Any]:
        """Test API security."""
        if not args:
            console.print("[yellow]Usage: /api <target>[/yellow]")
            return {"error": "Missing target"}

        target = args.strip()
        console.print(f"[bold]API security testing: {target}[/bold]")
        return self.runner.api_test(target)

    def cmd_report(self, _args: str = "") -> dict[str, Any]:
        """Generate security report."""
        console.print("[bold]Generating report...[/bold]")
        return self.runner.report()

    def cmd_status(self, _args: str = "") -> dict[str, Any]:
        """Show current engagement status."""
        status = self.runner.get_status()

        table = Table(title="Engagement Status")
        table.add_column("Field", style="bold cyan")
        table.add_column("Value", style="white")

        for key, value in status.items():
            table.add_row(key, str(value))

        # Add config summary
        table.add_row("model", self.config.model)
        table.add_row("provider", self.config.provider)
        table.add_row("mode", self.config.aggressiveness)
        table.add_row("llm_driven", str(self.config.is_enabled("llm_driven")))

        console.print(table)
        return status

    def cmd_config(self, args: str = "") -> dict[str, Any]:
        """Show or modify configuration."""
        if not args:
            # Show current config
            table = Table(title="Configuration")
            table.add_column("Setting", style="bold cyan")
            table.add_column("Value", style="white")

            for key, value in self.config.to_dict().items():
                if key == "api_key" and value:
                    value = value[:12] + "***"
                table.add_row(key, str(value))

            console.print(table)
            return self.config.to_dict()

        # Parse key=value
        if "=" in args:
            key, value = args.split("=", 1)
            key = key.strip()
            value = value.strip()

            if hasattr(self.config, key):
                # Type coercion
                attr_type = type(getattr(self.config, key))
                if attr_type == bool:
                    value = value.lower() in ("true", "1", "yes")
                elif attr_type == int:
                    value = int(value)
                elif attr_type == float:
                    value = float(value)

                setattr(self.config, key, value)
                self.config.save()
                console.print(f"[green]Set {key} = {value}[/green]")
                return {"status": "updated", key: value}
            else:
                console.print(f"[red]Unknown setting: {key}[/red]")
                return {"error": f"Unknown setting: {key}"}

        console.print("[yellow]Usage: /config or /config key=value[/yellow]")
        return {"error": "Invalid config command"}

    def cmd_model(self, args: str) -> dict[str, Any]:
        """Change the AI model."""
        if not args:
            console.print(f"[bold]Current model:[/bold] {self.config.model}")
            console.print(f"[bold]Provider:[/bold] {self.config.provider}")
            console.print("\nUsage: /model <model_name>")
            console.print("Examples:")
            console.print("  /model gpt-5")
            console.print("  /model claude-sonnet")
            console.print("  /model gemini")
            console.print("  /model ollama:qwen3")
            return {"model": self.config.model}

        model = args.strip()
        provider_id, resolved_model = resolve_provider(model)

        self.config.model = resolved_model
        self.config.provider = provider_id
        self.config.save()

        console.print(f"[green]Model set to: {resolved_model}[/green]")
        console.print(f"[dim]Provider: {provider_id}[/dim]")

        return {"model": resolved_model, "provider": provider_id}

    def cmd_providers(self, _args: str = "") -> dict[str, Any]:
        """List available model providers."""
        from argus_cli.core.providers import list_providers
        list_providers()
        return {"message": "Providers listed"}

    def cmd_sessions(self, args: str = "") -> dict[str, Any]:
        """List or manage sessions."""
        if args == "clear":
            self.sessions.clear_all()
            console.print("[green]All sessions cleared[/green]")
            return {"status": "cleared"}

        sessions = self.sessions.list_sessions()
        if not sessions:
            console.print("[dim]No saved sessions.[/dim]")
            return {"sessions": []}

        table = Table(title="Saved Sessions")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Target", style="cyan")
        table.add_column("Phase", style="bold")
        table.add_column("Created", style="dim")

        for s in sessions:
            table.add_row(
                s.get("id", "?")[:8],
                s.get("target", "?"),
                s.get("phase", "?"),
                s.get("created_at", "?"),
            )

        console.print(table)
        return {"sessions": sessions}

    def cmd_clear(self, _args: str = "") -> dict[str, Any]:
        """Clear screen — handled by TUI."""
        console.print("[dim]Screen cleared[/dim]")
        return {"action": "clear"}

    def cmd_quit(self, _args: str = "") -> dict[str, Any]:
        """Exit Argus."""
        console.print("[dim]Goodbye.[/dim]")
        return {"action": "quit"}


# Convenience function for direct command execution
def execute_command(command: str, config: Config) -> dict[str, Any] | None:
    """Execute a single command (for scripting)."""
    registry = CommandRegistry(config)
    return registry.execute(command)
