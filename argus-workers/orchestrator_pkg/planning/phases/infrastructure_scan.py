"""Phase: infrastructure_scan — _activate_infrastructure and _infrastructure_scan_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)




# ── Phase: Infrastructure Testing ──────────────────────────────────────

def _activate_infrastructure(rc) -> tuple[bool, str]:
    """Activate when open ports or web servers are detected beyond standard web ports."""
    ports = _get_attr(rc, "open_ports", [])
    if not ports:
        return False, "no open ports data"
    # Check for non-standard ports (beyond 80, 443, 8080)
    standard = {80, 443, 8080, 8443}
    non_standard = [p for p in ports if p.get("port", 0) not in standard] if ports else []
    if non_standard:
        return True, f"{len(non_standard)} non-standard port(s) detected"
    return True, f"{len(ports)} open port(s) — running infrastructure checks"


def _infrastructure_scan_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for infrastructure scanning."""
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Infrastructure and network vulnerability scanning",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "network,misconfig,exposure"],
        ),
    ]
    # TLS testing if HTTPS
    target = _get_attr(recon_context, "target_url", "")
    if target and target.startswith("https"):
        tools.append(ToolTask(
            tool_name="nuclei",
            description="TLS/SSL vulnerability scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssl,tls,ssl-tls"],
        ))
    return tools
