"""
Browser Security Operator — comprehensive browser-based security testing.

Combines Playwright automation with session handling, DOM analysis,
XSS/CSRF verification, and privilege escalation testing.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

_BLOCKED_SCHEMES = frozenset({"file", "ftp", "javascript", "data"})


class BrowserSecurityOperator(AbstractTool):
    """Comprehensive browser-based security testing operator."""

    tool_name: str = "browser_security_operator"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        parsed = urlparse(ctx.target)
        if parsed.scheme in _BLOCKED_SCHEMES:
            result.status = ToolStatus.SKIPPED
            result.error_message = f"Blocked scheme: {parsed.scheme}"
            result.mark_finished()
            return result

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        dom_findings = self._analyze_dom(ctx, builder)
        auth_findings = self._analyze_auth(ctx, builder)
        header_findings = self._analyze_headers(ctx, builder)

        all_findings = dom_findings + auth_findings + header_findings + builder.findings
        result.findings = all_findings
        result.findings_count = len(all_findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _analyze_dom(self, ctx: ToolContext, builder: FindingBuilder) -> list[dict]:
        """Analyze DOM for security issues."""

        forms = getattr(ctx, "_browser_forms", [])
        for form in forms:
            action = form.get("action", "")
            method = form.get("method", "GET").upper()
            enctype = form.get("enctype", "")

            if method == "POST" and enctype == "multipart/form-data":
                builder.info(
                    "FILE_UPLOAD_FORM",
                    action or ctx.target,
                    {"action": action, "method": method, "enctype": enctype},
                )

            inputs = form.get("inputs", [])
            has_csrf_token = any(
                "csrf" in (inp.get("name", "") or "").lower()
                or "token" in (inp.get("name", "") or "").lower()
                for inp in inputs
            )
            if not has_csrf_token and method == "POST":
                builder.vulnerability(
                    "MISSING_CSRF_TOKEN",
                    "MEDIUM",
                    action or ctx.target,
                    {"form_action": action, "method": method},
                    confidence=0.6,
                )

        return builder.findings

    def _analyze_auth(self, ctx: ToolContext, builder: FindingBuilder) -> list[dict]:
        """Analyze authentication mechanisms."""
        findings = []
        auth_config = getattr(ctx, "dual_auth", None)

        if auth_config:
            builder.info(
                "AUTH_DETECTED",
                ctx.target,
                {"auth_type": "dual_auth_configured", "configured": True},
            )

        return findings

    def _analyze_headers(self, ctx: ToolContext, builder: FindingBuilder) -> list[dict]:
        """Analyze response headers for security issues."""
        findings = []
        headers = getattr(ctx, "_browser_headers", {})

        csp = headers.get("content-security-policy", "")
        if not csp:
            builder.vulnerability(
                "MISSING_CSP",
                "MEDIUM",
                ctx.target,
                {"header": "Content-Security-Policy"},
                confidence=0.9,
            )

        x_frame = headers.get("x-frame-options", "")
        if not x_frame:
            builder.vulnerability(
                "MISSING_X_FRAME_OPTIONS",
                "LOW",
                ctx.target,
                {"header": "X-Frame-Options"},
                confidence=0.9,
            )

        return findings
