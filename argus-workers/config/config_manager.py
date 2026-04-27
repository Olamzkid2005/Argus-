"""
Configuration Manager - Hot-reloadable YAML configuration

Mirrors CyberStrikeAI's single config.yaml with hot-reload via API pattern.
Provides a singleton ConfigManager that reads from argus_config.yaml
and supports runtime reload without restart.
"""
import os
import logging
import threading
import time
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Default configuration (used if YAML file not found)
DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 9000, "workers": 4, "log_level": "INFO"},
    "database": {"pool_min": 2, "pool_max": 20, "slow_query_ms": 500},
    "redis": {"url": "redis://localhost:6379/0"},
    "tools": {
        "default_timeout": 300,
        "long_timeout": 600,
        "short_timeout": 60,
        "timeouts": {},
        "circuit_breaker": {"failure_threshold": 3, "cooldown_seconds": 300},
        "retry": {"max_attempts": 3, "base_delay": 1.0, "max_delay": 60.0, "backoff_multiplier": 2.0},
    },
    "scanning": {
        "max_pages_to_crawl": 20,
        "max_parameters_to_fuzz": 20,
        "rate_limit_delay_ms": 500,
        "ssl_timeout": 10,
        "default_aggressiveness": "default",
        "aggressiveness": {},
    },
    "agent": {"max_iterations": 20, "enable_llm_decisions": False, "memory_max_tokens": 8000},
    "streaming": {"enabled": True, "history_size": 500, "backpressure_queue_size": 1000},
    "security": {"ssl_verify": True, "block_dangerous_patterns": True, "allowed_schemes": ["https://", "http://"], "blocked_domains": []},
}


class ConfigManager:
    """
    Hot-reloadable configuration manager.
    
    Usage:
        config = get_config()
        timeout = config.get("tools.timeouts.nuclei", 600)
        config.reload()  # Hot-reload from disk
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._config_path = config_path or os.path.join(
            os.path.dirname(__file__), "argus_config.yaml"
        )
        self._config: Dict[str, Any] = {}
        self._last_mtime: float = 0
        self._reload()
    
    def _reload(self):
        """Load or reload configuration from YAML file."""
        path = Path(self._config_path)
        if not path.exists():
            logger.warning("Config file not found at %s, using defaults", self._config_path)
            self._config = DEFAULT_CONFIG.copy()
            return
        
        try:
            import yaml
            with open(path) as f:
                loaded = yaml.safe_load(f)
            if loaded and isinstance(loaded, dict):
                # Deep merge with defaults so missing keys fall back
                self._config = self._deep_merge(DEFAULT_CONFIG.copy(), loaded)
                self._last_mtime = path.stat().st_mtime
                logger.info("Configuration loaded from %s", self._config_path)
            else:
                self._config = DEFAULT_CONFIG.copy()
        except ImportError:
            logger.warning("PyYAML not installed, using default configuration")
            self._config = DEFAULT_CONFIG.copy()
        except Exception as e:
            logger.error("Failed to load config: %s, using defaults", e)
            self._config = DEFAULT_CONFIG.copy()
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries (override wins)."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def reload(self):
        """Hot-reload configuration from disk. Call this to pick up changes."""
        with self._lock:
            self._reload()
    
    def reload_if_changed(self):
        """Reload if the config file has been modified since last load."""
        path = Path(self._config_path)
        if path.exists() and path.stat().st_mtime > self._last_mtime:
            logger.info("Config file changed, reloading")
            self.reload()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a config value by dotted key path.
        
        Example:
            config.get("tools.timeouts.nuclei", 600)
            config.get("scanning.max_pages_to_crawl", 20)
        """
        with self._lock:
            parts = key.split(".")
            current = self._config
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                    if current is None:
                        return default
                else:
                    return default
            return current if current is not None else default
    
    def set(self, key: str, value: Any):
        """Set a config value by dotted key path at runtime."""
        with self._lock:
            parts = key.split(".")
            current = self._config
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
    
    def all(self) -> Dict:
        """Get the full configuration dict."""
        with self._lock:
            return self._config.copy()


# Singleton
_config_manager: Optional[ConfigManager] = None
_config_lock = threading.Lock()


def get_config() -> ConfigManager:
    """Get the singleton ConfigManager instance."""
    global _config_manager
    if _config_manager is None:
        with _config_lock:
            if _config_manager is None:
                _config_manager = ConfigManager()
    return _config_manager
