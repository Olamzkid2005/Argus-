"""Sandbox package — Docker-based isolation for exploit verification.

This package provides a Docker container sandbox for running generated
exploit scripts and PoCs in an isolated environment. When Docker is
unavailable, it gracefully falls back to subprocess-based execution.

Usage:
    from tool_core.sandbox.client import SandboxClient, SandboxResult

    client = SandboxClient()
    result = client.run_command(["echo", "hello"])
    if result.returncode == 0:
        print(result.stdout)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Configuration defaults — can be overridden via env vars
SANDBOX_ENABLED = os.environ.get("SANDBOX_ENABLED", "true").lower() == "true"
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "argus-sandbox:latest")
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "60"))


# Backward-compatible re-export: AsyncToolRunner was formerly in sandbox.py
from tool_core.async_runner import AsyncToolRunner  # noqa: F401


def is_available() -> bool:
    """Check if the Docker sandbox is available (Docker SDK + reachable daemon).

    Returns:
        True if Docker is installed and a daemon is reachable.
    """
    if not SANDBOX_ENABLED:
        return False
    try:
        from tool_core.sandbox.client import SandboxClient
        client = SandboxClient()
        return client.is_docker_available
    except Exception:
        return False
