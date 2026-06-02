"""
Banner and branding — replaces OpenCode branding with Argus.

Provides:
  - ASCII art banner
  - Styled Rich banner
  - Version info header
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from argus_cli import __app_name__, __tagline__, __version__

# ═══════════════════════════════════════════════════════════════
# ASCII Banner — shown on startup
# ═══════════════════════════════════════════════════════════════

ASCII_BANNER = r"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     █████╗ ██████╗  ██████╗ ██╗   ██╗███████╗            ║
    ║    ██╔══██╗██╔══██╗██╔════╝ ██║   ██║██╔════╝            ║
    ║    ███████║██████╔╝██║  ███╗██║   ██║███████╗            ║
    ║    ██╔══██║██╔══██╗██║   ██║██║   ██║╚════██║            ║
    ║    ██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║            ║
    ║    ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝            ║
    ║                                                           ║
    ║         Security AI Agent  —  v{version:8}              ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
""".format(version=__version__)

BANNER_COMPACT = r"""
 ╔══════════════════════════════════════════════════════════════╗
 ║  ARGUS v{version}  —  {tagline}                            ║
 ╚══════════════════════════════════════════════════════════════╝
""".format(version=__version__, tagline=__tagline__)


def print_banner(console: Console | None = None, compact: bool = False) -> None:
    """Print the Argus banner to console."""
    if console is None:
        console = Console()

    banner = BANNER_COMPACT if compact else ASCII_BANNER
    console.print(banner, style="bold cyan")


def get_rich_banner() -> Panel:
    """Return a Rich Panel containing the styled Argus banner."""
    text = Text()
    text.append("ARGUS", style="bold bright_cyan")
    text.append(f"  v{__version__}", style="dim cyan")
    text.append("\n")
    text.append(__tagline__, style="italic white")
    text.append("\n")
    text.append("Claude Code + OWASP Testing + Security Automation", style="dim white")

    return Panel(
        text,
        title="[bold green]Security AI Agent[/bold green]",
        subtitle="[dim]type /help for commands[/dim]",
        border_style="bright_cyan",
        expand=False,
        padding=(1, 2),
    )


def get_status_header(config_summary: str) -> Panel:
    """Return a status panel showing current configuration."""
    text = Text()
    text.append("Ready.", style="bold green")
    text.append(f"  {config_summary}", style="dim")

    return Panel(
        text,
        border_style="green",
        expand=False,
        padding=(0, 1),
    )
