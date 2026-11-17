"""Register delegated tools from their YAML definitions.

A delegated tool runs through ``tools/scripts/delegate_shim.py`` (its YAML ``args``
point at the shim). For those tools the YAML file is the only definition: mirroring
the same metadata by hand in ``_generated_tools.py`` needed a second edit for every
change and drifted (a stale ``target_kind``, wrong phases, one-off indentation).

So the mirror no longer carries them. This module turns each delegate YAML into a
:class:`ToolDefinition` at import time, which keeps metadata and invocation in one
file. ``mcp_server.py`` already builds the command from the same YAML, so the two
views cannot disagree.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import yaml

DEFINITIONS = Path(__file__).resolve().parent / "tools" / "definitions"

#: Marker in a definition's ``args`` that identifies a delegated tool.
SHIM = "delegate_shim.py"


def delegate_specs() -> Iterator[dict[str, Any]]:
    """Yield the parsed YAML spec of every tool that runs through the shim."""
    for path in sorted(DEFINITIONS.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        if any(SHIM in str(arg) for arg in spec.get("args") or ()):
            yield spec


def register_delegates(
    register: Callable[[Any], None],
    ToolDefinition: Any,
    ToolParameter: Any,
    ToolRequires: Any,
    SignalQuality: Any,
) -> int:
    """Register one ToolDefinition per delegate YAML. Returns how many were added."""
    count = 0
    for spec in delegate_specs():
        requires = spec.get("requires") or {}
        register(
            ToolDefinition(
                name=spec["name"],
                description=spec.get("description", ""),
                phases=list(spec.get("phases") or ()),
                binary=spec.get("command"),
                default_args=list(spec.get("args") or ()),
                parameters=[
                    ToolParameter(
                        name=param["name"],
                        description=param.get("description", ""),
                        required=bool(param.get("required", False)),
                        flag=param.get("flag"),
                        default=param.get("default"),
                    )
                    for param in spec.get("parameters") or ()
                ],
                target_kind=spec.get("target_kind", "any"),
                timeout=int(spec.get("timeout", 300)),
                signal_quality=SignalQuality[str(spec.get("signal_quality", "CANDIDATE"))],
                requires=ToolRequires(**requires) if requires else None,
                priority=spec.get("priority"),
                cost=spec.get("cost"),
                risk_level=spec.get("risk_level"),
                disabled_reason=spec.get("disabled_reason"),
                required_env=tuple(spec.get("required_env") or ()),
            )
        )
        count += 1
    return count
