"""
Provider abstraction layer — preserves OpenCode's multi-provider support.

Maps to Argus LLM client's provider system while adding
CLI-native provider management.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

from argus_cli.core.constants import PROVIDERS

console = Console()


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider."""

    id: str
    name: str
    api_url: str
    api_key: str | None = None
    default_model: str | None = None
    is_enabled: bool = True

    @classmethod
    def from_env(cls, provider_id: str) -> "ProviderConfig":
        """Load provider config from environment variables."""
        info = PROVIDERS.get(provider_id, {})
        env_key = info.get("env_key", "")
        api_key = os.getenv(env_key) or os.getenv("ARGUS_API_KEY") or None

        models = info.get("models", [])
        default_model = models[0] if models else None

        return cls(
            id=provider_id,
            name=info.get("name", provider_id),
            api_url=info.get("api_url", ""),
            api_key=api_key,
            default_model=default_model,
        )

    @property
    def is_configured(self) -> bool:
        """Check if this provider has an API key set."""
        return bool(self.api_key)


def resolve_provider(model: str) -> tuple[str, str]:
    """
    Resolve a model string to (provider_id, model_name).

    Supports shorthand notation:
      "gpt-5"        → ("openai", "gpt-5")
      "claude-sonnet" → ("anthropic", "claude-sonnet-4")
      "gemini"       → ("gemini", "gemini-2.5-pro")
      "ollama:qwen3" → ("ollama", "qwen3")

    Args:
        model: Model identifier (can include provider prefix)

    Returns:
        Tuple of (provider_id, resolved_model_name)
    """
    if ":" in model:
        # Explicit provider prefix: "ollama:qwen3"
        provider_id, model_name = model.split(":", 1)
        return provider_id, model_name

    # Shorthand — match against known model families
    model_lower = model.lower()

    # GPT family → OpenAI
    if model_lower.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai", model

    # Claude family → Anthropic
    if model_lower.startswith(("claude-", "claude_")):
        return "anthropic", model

    # Gemini family → Google
    if model_lower.startswith(("gemini-", "gemini_")):
        return "gemini", model

    # Qwen family → Ollama (local default)
    if model_lower.startswith(("qwen", "llama", "deepseek", "codellama")):
        return "ollama", model

    # Default fallback
    return "openai", model


def get_provider_for_model(model: str) -> ProviderConfig:
    """Get the appropriate provider configuration for a model."""
    provider_id, resolved_model = resolve_provider(model)
    config = ProviderConfig.from_env(provider_id)
    config.default_model = resolved_model
    return config


def list_providers() -> None:
    """Display all available providers in a formatted table."""
    table = Table(title="Available Model Providers", show_lines=True)
    table.add_column("Provider", style="bright_cyan", no_wrap=True)
    table.add_column("Status", style="bold")
    table.add_column("Models", style="white")
    table.add_column("Env Var", style="dim")

    for pid, info in PROVIDERS.items():
        config = ProviderConfig.from_env(pid)
        status = "[green]Configured[/green]" if config.is_configured else "[dim]Not set[/dim]"
        models = ", ".join(info.get("models", [])[:3])
        env_var = info.get("env_key", "N/A")

        table.add_row(
            f"[bold]{info.get('name', pid)}[/bold]",
            status,
            models,
            env_var,
        )

    console.print(table)
    console.print("\n[dim]Set API keys via environment variables or argus config.[/dim]")
    console.print("[dim]Usage: argus --model <model>[/dim]")
    console.print("[dim]       argus --model ollama:qwen3  # local model[/dim]")
