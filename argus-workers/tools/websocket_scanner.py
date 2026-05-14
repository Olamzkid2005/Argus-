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


class WebSocketScanner:
    """Test WebSocket endpoints for security issues."""

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
        self._check_deps()

    @staticmethod
    def _check_deps() -> None:
        if not HAS_WEBSOCKETS:
            raise RuntimeError(
                "websockets library is required. "
                "Install with: pip install websockets"
            )
        if not HAS_HTTPX:
            raise RuntimeError(
                "httpx library is required. Install with: pip install httpx"
            )

    async def scan(self, ws_url: str) -> list[dict[str, Any]]:
        """Run all WebSocket security tests.

        Args:
            ws_url: WebSocket URL (ws:// or wss://)

        Returns:
            List of finding dicts compatible with VulnerabilityFinding schema
        """
        slog = ScanLogger("websocket_scanner")

        if not is_enabled("WS_SCANNER", default=False):
            slog.info("WebSocket scanner disabled (feature flag off)")
            logger.info("WebSocket scanner disabled (ARGUS_FF_WS_SCANNER not set)")
            return []

        slog.phase_header("WebSocket Scan", ws_url)
        findings: list[dict[str, Any]] = []

        slog.tool_start("origin_validation", target=ws_url)
        origin_findings = await self._test_origin_validation(ws_url)
        slog.tool_result("origin_validation", f"{len(origin_findings)} finding(s)")
        findings.extend(origin_findings)

        slog.tool_start("auth_required", target=ws_url)
        auth_findings = await self._test_auth_required(ws_url)
        slog.tool_result("auth_required", f"{len(auth_findings)} finding(s)")
        findings.extend(auth_findings)

        slog.tool_start("message_injection", target=ws_url)
        injection_findings = await self._test_message_injection(ws_url)
        slog.tool_result("message_injection", f"{len(injection_findings)} finding(s)")
        findings.extend(injection_findings)

        slog.tool_start("rate_limiting", target=ws_url)
        rate_findings = await self._test_rate_limiting(ws_url)
        slog.tool_result("rate_limiting", f"{len(rate_findings)} finding(s)")
        findings.extend(rate_findings)

        slog.tool_complete("websocket_scan", findings=len(findings))
        return findings

    async def _test_origin_validation(self, ws_url: str) -> list[dict[str, Any]]:
        """Connect with spoofed Origin headers to check if server validates."""
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
                    extra_headers={"Origin": origin},
                    open_timeout=self.timeout,
                ) as ws:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                        response_text = self._decode_message(msg)
                    except TimeoutError:
                        response_text = "<no response within timeout>"

                    findings.append({
                        "type": "WEBSOCKET_ORIGIN_BYPASS",
                        "severity": "MEDIUM",
                        "confidence": 0.7,
                        "endpoint": ws_url,
                        "evidence": {
                            "spoofed_origin": origin,
                            "server_response": response_text,
                            "detail": "Server accepted connection with spoofed origin header",
                        },
                        "source_tool": "websocket_scanner",
                    })
                    await ws.close()
            except InvalidStatus:
                pass
            except (OSError, TimeoutError):
                pass
            except WebSocketException:
                pass
            except Exception:
                logger.debug(
                    "Origin test error for %s with origin %s",
                    ws_url,
                    origin,
                    exc_info=True,
                )

        return findings

    async def _test_auth_required(self, ws_url: str) -> list[dict[str, Any]]:
        """Connect without auth tokens to see if the server rejects the connection."""
        findings: list[dict[str, Any]] = []

        try:
            async with websockets.connect(ws_url, open_timeout=self.timeout) as ws:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
                    response_text = self._decode_message(msg)
                except TimeoutError:
                    response_text = "<no response within timeout>"

                findings.append({
                    "type": "WEBSOCKET_NO_AUTH",
                    "severity": "HIGH",
                    "confidence": 0.6,
                    "endpoint": ws_url,
                    "evidence": {
                        "detail": "Server accepted connection without authentication",
                        "server_response": response_text,
                    },
                    "source_tool": "websocket_scanner",
                })
                await ws.close()
        except InvalidStatus:
            pass
        except (OSError, TimeoutError):
            pass
        except WebSocketException:
            pass
        except Exception:
            logger.debug("Auth test error for %s", ws_url, exc_info=True)

        return findings

    async def _test_message_injection(self, ws_url: str) -> list[dict[str, Any]]:
        """Send malformed/injection messages to test for error leakage."""
        findings: list[dict[str, Any]] = []

        for payload in self.INJECTION_PAYLOADS:
            try:
                async with websockets.connect(ws_url, open_timeout=self.timeout) as ws:
                    await ws.send(payload)
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=self.timeout)
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
                            findings.append({
                                "type": "WEBSOCKET_INJECTION",
                                "severity": "HIGH",
                                "confidence": 0.7,
                                "endpoint": ws_url,
                                "evidence": {
                                    "payload": payload,
                                    "server_response": response_text,
                                    "detail": (
                                        "Server returned error-like response "
                                        "to injected payload"
                                    ),
                                },
                                "source_tool": "websocket_scanner",
                            })
                    except TimeoutError:
                        pass
                    await ws.close()
            except InvalidStatus:
                pass
            except (OSError, TimeoutError):
                pass
            except WebSocketException:
                pass
            except Exception:
                logger.debug("Injection test error for %s", ws_url, exc_info=True)

        return findings

    async def _test_rate_limiting(self, ws_url: str) -> list[dict[str, Any]]:
        """Send rapid messages to test for rate limiting."""
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
                    findings.append({
                        "type": "WEBSOCKET_RATE_LIMITED",
                        "severity": "INFO",
                        "confidence": 0.9,
                        "endpoint": ws_url,
                        "evidence": {
                            "messages_sent": messages_sent,
                            "total_attempted": self.RATE_LIMIT_MESSAGE_COUNT,
                            "detail": (
                                "Server closed connection after rapid messages "
                                "- rate limiting is active"
                            ),
                        },
                        "source_tool": "websocket_scanner",
                    })
                else:
                    findings.append({
                        "type": "WEBSOCKET_NO_RATE_LIMIT",
                        "severity": "MEDIUM",
                        "confidence": 0.7,
                        "endpoint": ws_url,
                        "evidence": {
                            "messages_sent": self.RATE_LIMIT_MESSAGE_COUNT,
                            "detail": (
                                "Server accepted all messages without rate limiting"
                            ),
                        },
                        "source_tool": "websocket_scanner",
                    })

                await ws.close()
        except InvalidStatus:
            pass
        except (OSError, TimeoutError):
            pass
        except WebSocketException:
            pass
        except Exception:
            logger.debug("Rate limit test error for %s", ws_url, exc_info=True)

        return findings

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
        slog.info(f"Discovering WebSocket URLs: {page_url}")
        urls: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(page_url)
                if resp.status_code != 200:
                    slog.info(f"Page returned {resp.status_code}, no WebSocket discovery")
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
            logger.debug(
                "WebSocket discovery error for %s", page_url, exc_info=True
            )

        return list(set(urls))
