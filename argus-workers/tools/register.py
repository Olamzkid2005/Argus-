"""
Register tool — wraps agent/tools/register_tool.py as an AbstractTool.
"""
from __future__ import annotations

import json
import logging

import requests

from agent.tools.register_tool import run_register
from tool_core.base import AbstractTool, ToolContext
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class RegisterTool(AbstractTool):
    """Autonomous account creation — discovers forms, generates credentials, registers."""

    tool_name: str = "register"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        http_session = requests.Session()
        result, _auth_ctx = run_register(
            target=ctx.target,
            http_session=http_session,
            auth_context=None,
            recon_crawled_paths=getattr(ctx, "_recon_paths", None),
        )
        return result
