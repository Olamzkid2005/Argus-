"""
Argus CLI main entry point.

Mirrors OpenCode's entry pattern:
  argus              → Launch TUI
  argus --version    → Show version
  argus --help       → Show help
  argus --config     → Show config path
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from argus_cli import __app_name__, __tagline__, __version__
from argus_cli.config.settings import Config
from argus_cli.core.banner import print_banner
from argus_cli.tui.argus_app import ArgusTUI


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name=__app_name__.lower())
@click.option(
    "--config",
    "show_config",
    is_flag=True,
    help="Show configuration file path and exit.",
)
@click.option(
    "--providers",
    is_flag=True,
    help="List available model providers and exit.",
)
@click.option(
    "--model",
    metavar="MODEL",
    help="Select model (e.g., gpt-5, claude-sonnet, gemini, ollama:qwen3).",
)
@click.option(
    "--api-key",
    envvar="ARGUS_API_KEY",
    help="API key for the selected provider.",
)
@click.option(
    "--target",
    "-t",
    metavar="TARGET",
    help="Target URL or domain to scan (launches scan immediately).",
)
@click.option(
    "--no-tui",
    is_flag=True,
    help="Disable TUI and use plain CLI mode.",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    help="Enable debug logging.",
)
@click.pass_context
def main(
    ctx: click.Context,
    show_config: bool,
    providers: bool,
    model: str | None,
    api_key: str | None,
    target: str | None,
    no_tui: bool,
    debug: bool,
) -> None:
    """
    ╔═══════════════════════════════════════════════════════╗
    ║  ARGUS v4  —  Security AI Agent                       ║
    ║                                                       ║
    ║  Claude Code + OWASP Testing + Security Automation    ║
    ╚═══════════════════════════════════════════════════════╝

    Interactive commands:
      /scan <target>     Run security scan
      /recon <target>    Run reconnaissance
      /auth <target>     Test authentication
      /api <target>      Test API security (BOLA/BOPLA)
      /report            Generate report
      /help              Show all commands
      /quit              Exit

    Examples:
      argus                          Launch interactive TUI
      argus --model claude-sonnet    Use specific model
      argus --target example.com     Scan target immediately
      argus --no-tui --target x.com  Plain CLI mode
    """
    if debug:
        os.environ["ARGUS_DEBUG"] = "1"

    config = Config.load()

    if show_config:
        click.echo(f"Config directory: {config.config_dir}")
        click.echo(f"Config file:      {config.config_file}")
        click.echo(f"Sessions DB:      {config.sessions_db}")
        ctx.exit(0)

    if providers:
        from argus_cli.core.providers import list_providers
        list_providers()
        ctx.exit(0)

    # Override config with CLI arguments
    if model:
        config.model = model
    if api_key:
        config.api_key = api_key

    # Print banner in non-TUI mode
    if no_tui:
        print_banner()

    if target:
        # Immediate scan mode — run without TUI
        _run_immediate_scan(target, config, no_tui)
        return

    # Launch TUI (default behavior, matching OpenCode)
    if not no_tui:
        app = ArgusTUI(config)
        try:
            app.run()
        except KeyboardInterrupt:
            click.echo("\n[argus] Interrupted. Goodbye.")
            ctx.exit(0)
    else:
        _run_repl(config)


def _run_immediate_scan(target: str, config: Config, no_tui: bool) -> None:
    """Run a scan immediately without entering interactive mode."""
    from argus_cli.core.runner import SecurityRunner

    if no_tui:
        print_banner()

    runner = SecurityRunner(config)
    try:
        runner.scan(target)
    except Exception as e:
        click.echo(f"[argus] Scan failed: {e}", err=True)
        sys.exit(1)


def _run_repl(config: Config) -> None:
    """Run a simple read-eval-print loop (plain CLI mode)."""
    from argus_cli.commands.registry import CommandRegistry

    print_banner()
    registry = CommandRegistry(config)

    click.echo("\n[argus] Type /help for commands, /quit to exit.\n")

    while True:
        try:
            user_input = click.prompt("argus>", prompt_suffix=" ")
        except (KeyboardInterrupt, EOFError):
            click.echo("\n[argus] Goodbye.")
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "quit", "exit"):
            click.echo("[argus] Goodbye.")
            break

        registry.execute(user_input)


if __name__ == "__main__":
    main()
