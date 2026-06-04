"""
Configuration management — replaces OpenCode's config loader.

Supports:
  - TOML config file (~/.config/argus/config.toml)
  - Environment variable overrides
  - Feature flags (~/.config/argus/features.yaml)
  - Per-session overrides
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import toml
import yaml

from argus_cli.core.constants import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_FEATURES,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    SESSIONS_DB,
)
from argus_cli.crypto import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)


@dataclass
class Config:
    """Argus CLI configuration — mirrors OpenCode's config structure."""

    # Paths
    config_dir: Path = field(default_factory=lambda: CONFIG_DIR)
    config_file: Path = field(default_factory=lambda: CONFIG_FILE)
    sessions_db: Path = field(default_factory=lambda: SESSIONS_DB)

    # Provider / Model
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    api_key: str | None = None
    api_url: str | None = None

    # Behavior
    temperature: float = 0.3
    max_iterations: int = 10
    timeout: int = 300
    aggressiveness: str = "balanced"  # passive | balanced | aggressive
    confirm_destructive: bool = True
    auto_approve: bool = False

    # Output
    output_format: str = "markdown"  # markdown | html | json
    verbose: bool = False
    stream_output: bool = True

    # Feature flags
    features: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_FEATURES))

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load configuration from file, with env var overrides."""
        config = cls()

        if path is not None:
            config.config_dir = path.parent
            config.config_file = path

        # Ensure config directory exists
        config.config_dir.mkdir(parents=True, exist_ok=True)

        # Load from TOML file
        config_file = config.config_file
        if config_file.exists():
            try:
                data = toml.load(config_file)
                config._apply_dict(data)
            except Exception as e:
                logger.warning("Failed to load config from %s: %s", config_file, e)

        # Environment variable overrides (highest priority)
        config._apply_env()

        # Load feature flags
        config._load_feature_flags()

        return config

    def save(self) -> None:
        """Save current configuration to file.

        B.08: API keys are encrypted with a machine-local key before writing.
        """
        self.config_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_iterations": self.max_iterations,
            "timeout": self.timeout,
            "aggressiveness": self.aggressiveness,
            "confirm_destructive": self.confirm_destructive,
            "auto_approve": self.auto_approve,
            "output_format": self.output_format,
            "verbose": self.verbose,
            "stream_output": self.stream_output,
            "features": self.features,
        }

        # B.08: Encrypt api_key before writing to disk
        if self.api_key:
            data["api_key_encrypted"] = encrypt_value(self.api_key)
        if self.api_url:
            data["api_url_encrypted"] = encrypt_value(self.api_url)

        try:
            with open(self.config_file, "w") as f:
                toml.dump(data, f)
        except Exception as e:
            logger.warning("Failed to save config to %s: %s", self.config_file, e)

    def _apply_dict(self, data: dict[str, Any]) -> None:
        """Apply configuration from a dictionary.

        B.08: Supports both plaintext and encrypted api_key fields.
        Encrypted fields (api_key_encrypted) take priority over plaintext.
        """
        if "provider" in data:
            self.provider = data["provider"]
        if "model" in data:
            self.model = data["model"]
        # B.08: Decrypt if stored encrypted; fall back to plaintext for backward compat
        if "api_key_encrypted" in data:
            self.api_key = decrypt_value(data["api_key_encrypted"])
        elif "api_key" in data:
            self.api_key = data["api_key"]
        if "api_url_encrypted" in data:
            self.api_url = decrypt_value(data["api_url_encrypted"])
        elif "api_url" in data:
            self.api_url = data["api_url"]
        if "temperature" in data:
            self.temperature = data["temperature"]
        if "max_iterations" in data:
            self.max_iterations = data["max_iterations"]
        if "timeout" in data:
            self.timeout = data["timeout"]
        if "aggressiveness" in data:
            self.aggressiveness = data["aggressiveness"]
        if "confirm_destructive" in data:
            self.confirm_destructive = data["confirm_destructive"]
        if "auto_approve" in data:
            self.auto_approve = data["auto_approve"]
        if "output_format" in data:
            self.output_format = data["output_format"]
        if "verbose" in data:
            self.verbose = data["verbose"]
        if "stream_output" in data:
            self.stream_output = data["stream_output"]
        if "features" in data:
            self.features.update(data["features"])

    def _apply_env(self) -> None:
        """Apply environment variable overrides."""
        env_map = {
            "ARGUS_PROVIDER": "provider",
            "ARGUS_MODEL": "model",
            "ARGUS_API_KEY": "api_key",
            "ARGUS_API_URL": "api_url",
            "ARGUS_TEMPERATURE": "temperature",
            "ARGUS_MAX_ITERATIONS": "max_iterations",
            "ARGUS_TIMEOUT": "timeout",
            "ARGUS_AGGRESSIVENESS": "aggressiveness",
            "ARGUS_AUTO_APPROVE": "auto_approve",
            "ARGUS_OUTPUT_FORMAT": "output_format",
            "ARGUS_VERBOSE": "verbose",
        }

        for env_var, attr in env_map.items():
            value = os.getenv(env_var)
            if value is not None:
                # Type coercion
                if attr in ("temperature",):
                    try:
                        value = float(value)
                    except ValueError:
                        continue
                elif attr in ("max_iterations", "timeout"):
                    try:
                        value = int(value)
                    except ValueError:
                        continue
                elif attr in ("auto_approve", "verbose"):
                    value = value.lower() in ("true", "1", "yes", "on")

                setattr(self, attr, value)

    def _feature_flags_path(self) -> Path:
        """Return the path to the feature flags file."""
        return self.config_dir / "features.yaml"

    def _load_feature_flags(self) -> None:
        """Load feature flags from YAML file."""
        flag_file = self._feature_flags_path()
        if flag_file.exists():
            try:
                with open(flag_file) as f:
                    flags = yaml.safe_load(f)
                if flags and isinstance(flags, dict):
                    self.features.update(flags)
            except Exception as e:
                logger.warning("Failed to load feature flags: %s", e)

    def save_feature_flags(self) -> None:
        """Save feature flags to YAML file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self._feature_flags_path(), "w") as f:
                yaml.dump(self.features, f, default_flow_style=False)
        except Exception as e:
            logger.warning("Failed to save feature flags: %s", e)

    def is_enabled(self, feature: str) -> bool:
        """Check if a feature flag is enabled."""
        return self.features.get(feature, DEFAULT_FEATURES.get(feature, False))

    def get_summary(self) -> str:
        """Return a one-line summary of current configuration."""
        key_status = "[key set]" if self.api_key else "[no key]"
        return f"model={self.model} {key_status} temp={self.temperature} mode={self.aggressiveness}"

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key[:8] + "..." if self.api_key else None,
            "api_url": self.api_url,
            "temperature": self.temperature,
            "max_iterations": self.max_iterations,
            "timeout": self.timeout,
            "aggressiveness": self.aggressiveness,
            "confirm_destructive": self.confirm_destructive,
            "auto_approve": self.auto_approve,
            "output_format": self.output_format,
            "verbose": self.verbose,
            "stream_output": self.stream_output,
            "features": self.features,
        }
