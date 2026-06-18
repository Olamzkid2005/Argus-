"""
Login tool — wraps agent/tools/login_tool.py as an AbstractTool.
"""

from __future__ import annotations

import logging

import requests

from agent.tools.login_tool import run_login
from tool_core.base import AbstractTool, ToolContext
from tool_core.result import UnifiedToolResult

logger = logging.getLogger(__name__)


class LoginTool(AbstractTool):
    """Autonomous login — discovers forms, submits credentials, captures session."""

    tool_name: str = "login"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        email = getattr(ctx, "_email", None)
        password = getattr(ctx, "_password", None)
        login_url = getattr(ctx, "_login_url", None)
        with requests.Session() as http_session:
            result, _auth_ctx = run_login(
                target=ctx.target,
                http_session=http_session,
                auth_context=None,
                email=email,
                password=password,
                recon_crawled_paths=getattr(ctx, "_recon_paths", None),
                login_url=login_url,
            )
        return result
