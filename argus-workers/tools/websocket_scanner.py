"""
WebSocket Security Scanner

Tests WebSocket endpoints for:
- Origin header validation
- Authentication requirements
- Message injection vulnerabilities
- Rate limiting

Gated behind ARGUS_FF_WS_SCANNER feature flag.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from feature_flags import is_enabled
from tool_core.base import AsyncTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

try:
    import websockets
    from websockets.exceptions import InvalidStatus, WebSocketException

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class WebSocketScanner(AsyncTool):
    """Test WebSocket endpoints for security issues."""

    tool_name = "websocket_scanner"

    INJECTION_PAYLOADS: list[str] = [
        "<script>alert(1)</script>",
        "' OR '1'='1",
        "; DROP TABLE users--",
        "${7*7}",
        "{{7*7}}",
        "<img src=x onerror=alert(1)>",
        "../../etc/passwd",
        '{"__proto__": {"polluted": true}}',
        "\x00\x01\x02",
        "\x00",
    ]

    RATE_LIMIT_MESSAGE_COUNT: int = 100
    RATE_LIMIT_BURST_SIZE: int = 20

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout
        self._builder: FindingBuilder | None = None
        self._check_deps()

    @staticmethod
    def _check_deps() -> None:
        if not HAS_WEBSOCKETS:
            raise RuntimeError(
                "websockets library is required. Install with: pip install websockets"
            )
        if not HAS_HTTPX:
            raise RuntimeError(
                "httpx library is required. Install with: pip install httpx"
            )

    def _add_finding(
        self,
        finding_type: str,
        severity: str,
        endpoint: str,
        evidence: dict,
        confidence: float = 0.8,
    ) -> dict:
        """Register a finding via ``self._builder``, lazily creating it if needed.

        Returns the finding dict so callers can build a local results list for
        backward compat with direct test calls.

        Matches the ``APISecurityScanner._add_finding`` pattern.
        """
        if self._builder is None:
            self._builder = FindingBuilder(
                source_tool=self.tool_name,
                engagement_id=getattr(self, "engagement_id", ""),
            )
        return self._builder.add(finding_type, severity, endpoint, evidence, confidence)

    async def scan(
        self, ws_url: str, builder: FindingBuilder | None = None
    ) -> list[dict[str, Any]]:
        """
        Run all WebSocket security tests.

        Backward-compatible shim that delegates to ``async_execute()``.
        Existing callers that call ``scan()`` directly still work unchanged.

        Args:
            ws_url: WebSocket URL (ws:// or wss://)
            builder: Deprecated — ignored, ``async_execute()`` creates its own builder.

        Returns:
            List of finding dicts compatible with VulnerabilityFinding schema
        """
        ctx = ToolContext(target=ws_url)
        result = await self.async_execute(ctx)
        return result.findings

    async def _test_origin_validation(self, ws_url: str) -> list[dict[str, Any]]:
        """Connect with spoofed Origin headers to check if server validates.

        Findings are registered via ``self._builder`` and returned as a list.
        """
        findings: list[dict[str, Any]] = []

        spoofed_origins = [
            "https://evil.com",
            "https://attacker.org",
            "null",
            "http://192.168.1.1",
        ]

        for origin in spoofed_origins:
            try:
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Origin": origin},
                    open_timeout=self.timeout,
                ) as ws:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                        response_text = self._decode_message(msg)
                    except TimeoutError:
                        response_text = "<no response within timeout>"

                    evidence = {
                        "spoofed_origin": origin,
                        "server_response": response_text,
                        "detail": "Server accepted connection with spoofed origin header",
                    }
                    findings.append(
                        self._add_finding(
                            "WEBSOCKET_ORIGIN_BYPASS",
                            "MEDIUM",
                            ws_url,
                            evidence,
                            confidence=0.7,
                        )
                    )
                    await ws.close()
            except InvalidStatus:
                logger.debug(
                    "Server rejected origin validation for %s with origin %s",
                    ws_url,
                    origin,
                )
            except (OSError, TimeoutError):
                logger.debug(
                    "Network error during origin validation for %s with origin %s",
                    ws_url,
                    origin,
                )
            except WebSocketException:
                logger.debug(
                    "WebSocket protocol error during origin validation for %s with origin %s",
                    ws_url,
                    origin,
                )

        return findings

    async def _test_auth_required(self, ws_url: str) -> list[dict[str, Any]]:
        """Connect without auth tokens to see if the server rejects the connection.

        Findings are registered via ``self._builder`` and returned as a list.
        """

        findings: list[dict[str, Any]] = []

        try:
            async with websockets.connect(ws_url, open_timeout=self.timeout) as ws:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    response_text = self._decode_message(msg)
                except TimeoutError:
                    response_text = "<no response within timeout>"

                evidence = {
                    "detail": "Server accepted connection without authentication",
                    "server_response": response_text,
                }
                findings.append(
                    self._add_finding(
                        "WEBSOCKET_NO_AUTH",
                        "HIGH",
                        ws_url,
                        evidence,
                        confidence=0.6,
                    )
                )
                await ws.close()
        except InvalidStatus:
            logger.debug("Server rejected auth test for %s (expected)", ws_url)
        except (OSError, TimeoutError):
            logger.debug("Network error during auth test for %s", ws_url)
        except WebSocketException:
            logger.debug("WebSocket protocol error during auth test for %s", ws_url)

        return findings

    async def _test_message_injection(self, ws_url: str) -> list[dict[str, Any]]:
        """Send malformed/injection messages to test for error leakage.

        Findings are registered via ``self._builder`` and returned as a list.
        """

        findings: list[dict[str, Any]] = []

        for payload in self.INJECTION_PAYLOADS:
            try:
                async with websockets.connect(ws_url, open_timeout=self.timeout) as ws:
                    await ws.send(payload)
                    try:
                        response = await asyncio.wait_for(
                            ws.recv(), timeout=self.timeout
                        )
                        response_text = self._decode_message(response)

                        if any(
                            keyword in response_text.lower()
                            for keyword in [
                                "error",
                                "exception",
                                "traceback",
                                "warning",
                                "invalid",
                                "syntax",
                                "unexpected",
                            ]
                        ):
                            evidence = {
                                "payload": payload,
                                "server_response": response_text,
                                "detail": (
                                    "Server returned error-like response "
                                    "to injected payload"
                                ),
                            }
                            findings.append(
                                self._add_finding(
                                    "WEBSOCKET_INJECTION",
                                    "HIGH",
                                    ws_url,
                                    evidence,
                                    confidence=0.7,
                                )
                            )
                    except TimeoutError:
                        pass
                    await ws.close()
            except InvalidStatus:
                logger.debug("Server rejected injection test for %s (expected)", ws_url)
            except (OSError, TimeoutError):
                logger.debug("Network error during injection test for %s", ws_url)
            except WebSocketException:
                logger.debug(
                    "WebSocket protocol error during injection test for %s", ws_url
                )

        return findings

    async def _test_rate_limiting(self, ws_url: str) -> list[dict[str, Any]]:
        """Send rapid messages to test for rate limiting.

        Findings are registered via ``self._builder`` and returned as a list.
        """

        findings: list[dict[str, Any]] = []

        try:
            async with websockets.connect(ws_url, open_timeout=self.timeout) as ws:
                rate_limited = False
                messages_sent = 0
                for i in range(self.RATE_LIMIT_MESSAGE_COUNT):
                    try:
                        await ws.send(f"rate-test-{i}")
                        messages_sent += 1
                    except WebSocketException:
                        rate_limited = True
                        break

                if rate_limited:
                    evidence = {
                        "messages_sent": messages_sent,
                        "total_attempted": self.RATE_LIMIT_MESSAGE_COUNT,
                        "detail": (
                            "Server closed connection after rapid messages "
                            "- rate limiting is active"
                        ),
                    }
                    findings.append(
                        self._add_finding(
                            "WEBSOCKET_RATE_LIMITED",
                            "INFO",
                            ws_url,
                            evidence,
                            confidence=0.9,
                        )
                    )
                else:
                    evidence = {
                        "messages_sent": self.RATE_LIMIT_MESSAGE_COUNT,
                        "detail": (
                            "Server accepted all messages without rate limiting"
                        ),
                    }
                    findings.append(
                        self._add_finding(
                            "WEBSOCKET_NO_RATE_LIMIT",
                            "MEDIUM",
                            ws_url,
                            evidence,
                            confidence=0.7,
                        )
                    )

                await ws.close()
        except InvalidStatus:
            logger.debug("Server rejected rate limit test for %s (expected)", ws_url)
        except (OSError, TimeoutError):
            logger.debug("Network error during rate limit test for %s", ws_url)
        except WebSocketException:
            logger.debug(
                "WebSocket protocol error during rate limit test for %s", ws_url
            )

        return findings

    async def async_execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        AsyncTool entry point.

        Creates a ``FindingBuilder`` from the context, maps ``ToolContext``
        settings, runs all WebSocket security tests, and returns a
        ``UnifiedToolResult`` with findings.
        """
        builder = FindingBuilder(
            source_tool=self.tool_name,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding,
        )

        # Map ToolContext timeout
        if ctx.timeout:
            self.timeout = ctx.timeout

        ws_url = ctx.target
        self._builder = builder

        slog = ScanLogger("websocket_scanner")

        if not is_enabled("WS_SCANNER", default=False):
            slog.info("WebSocket scanner disabled (feature flag off)")
            logger.info("WebSocket scanner disabled (ARGUS_FF_WS_SCANNER not set)")
            result = UnifiedToolResult(tool_name=self.tool_name, target=ws_url)
            result.mark_finished()
            return result

        slog.phase_header("WebSocket Scan", ws_url)

        slog.tool_start("origin_validation", target=ws_url)
        await self._test_origin_validation(ws_url)
        slog.tool_result("origin_validation", f"{len(builder.findings)} finding(s)")

        slog.tool_start("auth_required", target=ws_url)
        await self._test_auth_required(ws_url)
        slog.tool_result("auth_required", f"{len(builder.findings)} finding(s)")

        slog.tool_start("message_injection", target=ws_url)
        await self._test_message_injection(ws_url)
        slog.tool_result("message_injection", f"{len(builder.findings)} finding(s)")

        slog.tool_start("rate_limiting", target=ws_url)
        await self._test_rate_limiting(ws_url)
        slog.tool_result("rate_limiting", f"{len(builder.findings)} finding(s)")

        slog.tool_complete("websocket_scan", findings=len(builder.findings))

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ws_url,
        )
        result.findings = builder.findings
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    @staticmethod
    def _decode_message(msg: Any) -> str:
        if isinstance(msg, bytes):
            return msg.decode("utf-8", errors="replace")
        return str(msg)

    @staticmethod
    async def discover_websocket_urls(page_url: str) -> list[str]:
        """Scan page HTML for WebSocket URLs.

        Looks for:
        - ``new WebSocket('...')`` constructor calls
        - Literal ``wss://`` or ``ws://`` URLs in the page

        Args:
            page_url: HTTP/HTTPS URL to fetch and scan

        Returns:
            Deduplicated list of discovered WebSocket URLs
        """
        slog = ScanLogger("websocket_scanner")
        slog.info("Discovering WebSocket URLs: %s", page_url)
        urls: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(page_url)
                if resp.status_code != 200:
                    slog.info(
                        f"Page returned {resp.status_code}, no WebSocket discovery"
                    )
                    return urls

                html = resp.text

                ws_constructors = re.findall(
                    r"""new\s+WebSocket\s*\(\s*['"](wss?://[^'"]+)['"]\s*\)""",
                    html,
                    re.IGNORECASE,
                )
                urls.extend(ws_constructors)

                literal_urls = re.findall(r"(wss?://[^\s\"'<>,;)]+)", html)
                urls.extend(literal_urls)

        except httpx.RequestError:
            logger.debug("Failed to fetch %s for WebSocket discovery", page_url)
        except Exception:
            logger.debug("WebSocket discovery error for %s", page_url, exc_info=True)

        return list(set(urls))
