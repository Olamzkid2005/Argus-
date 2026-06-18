"""
tool_core/config/models.py — Configuration dataclasses

- ``ToolRuntimeConfig`` — injected, mutable per-scan runtime settings.
- ``ToolMetadata`` — optional static metadata for installable/updatable tools.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolRuntimeConfig:
    """
    Runtime configuration injected into every tool execution.

    Mutable per scan — values can differ between engagements.
    """

    timeout: int = 120
    rate_limit: float = 0.05  # seconds between requests
    max_output_bytes: int = 10_485_760  # 10 MB
    enable_llm_payloads: bool = True
    max_llm_payloads: int = 2
    verify_ssl: bool = True
    user_agent: str = "Argus-Scanner/1.0"
    feature_flag: str = ""  # e.g., "WS_SCANNER"


@dataclass
class DualAuthConfig:
    """
    Configuration for dual-auth BOLA/BOPLA scanning.

    auth_a: Auth config for User A (resource owner who creates resources).
    auth_b: Auth config for User B (attacker who tries cross-account access).
    """

    auth_a: dict
    auth_b: dict


@dataclass(frozen=True)
class ToolMetadata:
    """
    Optional static metadata for an installable/updatable tool.

    Defined inline with the ``ToolDefinition`` in ``tool_definitions.py``,
    not in a separate YAML file.  Extended incrementally — only the fields
    needed for a given tool are populated.
    """

    vendor: str = ""
    homepage: str = ""
    license: str = ""
    default_version: str = ""
    pip_package: str = ""
    pip_allowlisted: bool = False
    download_url: str = ""
    sha256: str = ""
    feature_flag: str = ""  # e.g., "WS_SCANNER"
