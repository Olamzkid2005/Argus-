"""
Constants for Argus CLI.

Single source of truth for version info, paths, defaults,
and feature flags.
"""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

# ═══════════════════════════════════════════════════════════════
# App Info
# ═══════════════════════════════════════════════════════════════

APP_NAME = "argus"
APP_AUTHOR = "argus-security"
VERSION = "4.0.0-alpha.1"

# ═══════════════════════════════════════════════════════════════
# Paths
# ═══════════════════════════════════════════════════════════════

CONFIG_DIR = Path(user_config_dir(APP_NAME, APP_AUTHOR))
DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
SESSIONS_DB = DATA_DIR / "sessions.db"
CONFIG_FILE = CONFIG_DIR / "config.toml"
FEATURE_FLAGS_FILE = CONFIG_DIR / "features.yaml"

# ═══════════════════════════════════════════════════════════════
# Defaults
# ═══════════════════════════════════════════════════════════════

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_PROVIDER = "openai"
DEFAULT_TEMPERATURE = 0.3
nDEFAULT_MAX_ITERATIONS = 10
DEFAULT_TIMEOUT = 300
DEFAULT_AGGRESSIVENESS = "balanced"  # passive | balanced | aggressive

# ═══════════════════════════════════════════════════════════════
# Providers — mirrors OpenCode's provider registry
# ═══════════════════════════════════════════════════════════════

PROVIDERS = {
    "openai": {
        "name": "OpenAI",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "env_key": "OPENAI_API_KEY",
        "models": ["gpt-5", "gpt-4o", "gpt-4o-mini", "o3", "o4-mini"],
    },
    "anthropic": {
        "name": "Anthropic",
        "api_url": "https://api.anthropic.com/v1/messages",
        "env_key": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4", "claude-sonnet-4", "claude-haiku-4"],
    },
    "gemini": {
        "name": "Google Gemini",
        "api_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env_key": "GEMINI_API_KEY",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    },
    "openrouter": {
        "name": "OpenRouter",
        "api_url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
        "models": ["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.0-flash"],
    },
    "ollama": {
        "name": "Ollama (Local)",
        "api_url": "http://localhost:11434/v1/chat/completions",
        "env_key": "OLLAMA_HOST",
        "models": ["qwen3", "llama3.3", "deepseek-r1", "codellama"],
    },
    "azure": {
        "name": "Azure OpenAI",
        "api_url": "",
        "env_key": "AZURE_OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
}

# ═══════════════════════════════════════════════════════════════
# Feature Flags — controlled rollback strategy
# ═══════════════════════════════════════════════════════════════

DEFAULT_FEATURES = {
    "planner": True,
    "recon": True,
    "auth": True,
    "api_testing": True,
    "reporting": True,
    "llm_driven": True,
    "streaming": True,
    "mcp_bridge": True,
    "swarm": False,
    "chain_exploits": False,
}

# ═══════════════════════════════════════════════════════════════
# Security Testing Phases
# ═══════════════════════════════════════════════════════════════

PHASES = [
    "created",
    "recon",
    "scanning",
    "analyzing",
    "reporting",
    "complete",
    "failed",
    "paused",
]

VALID_TRANSITIONS = {
    "created": ["recon", "failed"],
    "recon": ["scanning", "failed"],
    "scanning": ["analyzing", "failed"],
    "analyzing": ["reporting", "recon", "scanning", "failed"],
    "reporting": ["complete", "failed"],
    "paused": ["recon", "scanning", "analyzing", "reporting", "failed"],
    "failed": [],
    "complete": [],
}

# ═══════════════════════════════════════════════════════════════
# Tool Registry — Phase 1 (core tools)
# ═══════════════════════════════════════════════════════════════

CORE_TOOLS = [
    "httpx",
    "katana",
    "nuclei",
    "ffuf",
]

PHASE2_TOOLS = [
    "sqlmap",
    "zap",
    "dalfox",
    "nikto",
    "naabu",
]

PHASE3_TOOLS = [
    "semgrep",
    "custom_argus",
]

# ═══════════════════════════════════════════════════════════════
# CLI Styling
# ═══════════════════════════════════════════════════════════════

THEME = {
    "primary": "bright_cyan",
    "secondary": "green",
    "accent": "yellow",
    "error": "red",
    "warning": "dark_orange",
    "info": "blue",
    "success": "green",
    "dim": "dim white",
    "highlight": "bold bright_white",
}
