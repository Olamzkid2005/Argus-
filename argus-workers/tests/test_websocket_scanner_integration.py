"""
Integration tests for WebSocketScanner.

Starts an intentionally insecure local WebSocket echo server and verifies
the scanner produces the expected findings for each security test.

The test server has deliberately weak security:
- No origin validation (accepts any Origin header)
- No authentication required
- Echoes all received messages back (no sanitization)
- No rate limiting on messages

Usage:
    ARGUS_FF_WS_SCANNER=true python -m pytest tests/test_websocket_scanner_integration.py -v
"""

import asyncio
import logging
import os
import threading
import time
from unittest.mock import patch

import pytest

# Enable the scanner for all tests in this module
os.environ.setdefault("ARGUS_FF_WS_SCANNER", "true")

logger = logging.getLogger(__name__)


# ── Test WebSocket Server ────────────────────────────────────────────────


class _TestWsEchoServer:
    """Intentionally insecure WebSocket echo server for testing.

    Accepts all connections regardless of origin, auth, or rate.
    Echoes all messages back so injection tests can verify responses.
    """

    def __init__(self):
        self.server = None

    async def _handler(self, websocket):
        """Echo each received message back."""
        async for message in websocket:
            try:
                await websocket.send(message)
            except Exception:
                break

    async def start(self, host="127.0.0.1", port=0) -> tuple[str, int]:
        """Start the server. Returns (ws_url, port)."""
        import websockets.asyncio.server

        self.server = await websockets.asyncio.server.serve(
            self._handler, host, port,
        )
        port = self.server.sockets[0].getsockname()[1]
        url = f"ws://{host}:{port}"
        return url, port

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()


@pytest.fixture(scope="module")
def ws_server_url():
    """Start a local test WebSocket server and yield its URL.

    Scope is module so we only start/stop once for all tests.
    The server runs in a daemon thread.
    """
    url_holder: list[str] = []

    def _run():
        async def _main():
            server = _TestWsEchoServer()
            url, port = await server.start()
            url_holder.append(url)
            # Keep running until interrupted
            while True:
                await asyncio.sleep(3600)

        asyncio.run(_main())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    time.sleep(1)  # Allow server to start

    assert url_holder, "Test server failed to start"
    yield url_holder[0]

    # Module-scoped fixture cleanup happens automatically
    # (daemon thread dies with the process)


# ── Tests ────────────────────────────────────────────────────────────────


class TestWebSocketScannerIntegration:
    """Full integration tests — runs the scanner against a live local server."""

    def test_full_scan_produces_all_expected_findings(self, ws_server_url):
        """End-to-end scan produces all 4 finding types."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _scan():
            return await scanner.scan(ws_server_url)

        findings = asyncio.run(_scan())

        # Expect: 4 ORIGIN_BYPASS + 1 NO_AUTH + 1 INJECTION + 1 NO_RATE_LIMIT
        assert len(findings) == 7, f"Expected 7 findings, got {len(findings)}"

        types = {f["type"] for f in findings}

        assert "WEBSOCKET_ORIGIN_BYPASS" in types, (
            "Missing origin bypass findings — server accepts all origins"
        )
        assert "WEBSOCKET_NO_AUTH" in types, (
            "Missing no-auth finding — server accepts without credentials"
        )
        assert "WEBSOCKET_INJECTION" in types, (
            "Missing injection finding — server echoes unsanitized payloads"
        )
        assert "WEBSOCKET_NO_RATE_LIMIT" in types, (
            "Missing rate-limit finding — server has no throttling"
        )

        # Verify specific finding details
        origin_findings = [f for f in findings if f["type"] == "WEBSOCKET_ORIGIN_BYPASS"]
        assert len(origin_findings) == 4, (
            f"Expected 4 origin bypass findings (4 spoofed origins), got {len(origin_findings)}"
        )

        spoofed_origins = {f["evidence"]["spoofed_origin"] for f in origin_findings}
        assert "https://evil.com" in spoofed_origins
        assert "https://attacker.org" in spoofed_origins
        assert "null" in spoofed_origins
        assert "http://192.168.1.1" in spoofed_origins

        # All findings should have the required schema fields
        for f in findings:
            assert "type" in f
            assert "severity" in f
            assert "confidence" in f
            assert "endpoint" in f
            assert "evidence" in f
            assert f["endpoint"] == ws_server_url
            assert f.get("source_tool") == "websocket_scanner"

        # Severity sanity checks
        severities = {f["severity"] for f in findings}
        assert "HIGH" in severities  # WEBSOCKET_NO_AUTH + WEBSOCKET_INJECTION
        assert "MEDIUM" in severities  # WEBSOCKET_ORIGIN_BYPASS + WEBSOCKET_NO_RATE_LIMIT

    def test_origin_validation_detects_bypass(self, ws_server_url):
        """Origin validation test detects when server accepts spoofed origins."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _test():
            return await scanner._test_origin_validation(ws_server_url)

        findings = asyncio.run(_test())

        assert len(findings) == 4, f"Expected 4 origin bypass findings, got {len(findings)}"
        for f in findings:
            assert f["type"] == "WEBSOCKET_ORIGIN_BYPASS"
            assert f["severity"] == "MEDIUM"
            assert f["confidence"] == 0.7

    def test_auth_required_detects_missing_auth(self, ws_server_url):
        """Auth test detects when server accepts connections without credentials."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _test():
            return await scanner._test_auth_required(ws_server_url)

        findings = asyncio.run(_test())

        assert len(findings) == 1, f"Expected 1 no-auth finding, got {len(findings)}"
        assert findings[0]["type"] == "WEBSOCKET_NO_AUTH"
        assert findings[0]["severity"] == "HIGH"
        assert findings[0]["confidence"] == 0.6

    def test_message_injection_detects_unsanitized_echo(self, ws_server_url):
        """Injection test detects when server echoes unsanitized payloads."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _test():
            return await scanner._test_message_injection(ws_server_url)

        findings = asyncio.run(_test())

        # The echo server echoes everything back, and our payloads contain
        # keywords like "error" (../../etc/passwd has error? no... let me check)
        # Actually, the scanner checks if the echoed response contains
        # keywords like "error", "exception", "traceback", etc.
        # The echo server just echoes the payload verbatim.
        # Payloads like "' OR '1'='1" and "; DROP TABLE users--" contain none of these keywords.
        # But INJECTION_PAYLOADS includes things like "<img src=x onerror=alert(1)>"
        # which has "error" in it! So the scanner will flag that one.
        # Also <script>alert(1)</script> and <img src=x onerror=alert(1)>
        # Actually, it checks response_text.lower() for keywords. Let me look:
        # "error" - onerror=alert(1) matches "error"
        # "invalid" - not present in any payload
        # etc.
        # The <img src=x onerror=alert(1)> payload has "onerror" which contains "error"
        # So at minimum 1 finding from that payload.
        # The scanner sends INJECTION_PAYLOADS sequentially and checks each response.
        assert len(findings) >= 1, (
            f"Expected at least 1 injection finding, got {len(findings)}"
        )

        for f in findings:
            assert f["type"] == "WEBSOCKET_INJECTION"
            assert f["severity"] == "HIGH"

    def test_rate_limiting_detects_no_throttling(self, ws_server_url):
        """Rate limiting test detects when server has no throttling."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _test():
            return await scanner._test_rate_limiting(ws_server_url)

        findings = asyncio.run(_test())

        assert len(findings) == 1, f"Expected 1 rate-limit finding, got {len(findings)}"
        assert findings[0]["type"] == "WEBSOCKET_NO_RATE_LIMIT"
        assert findings[0]["severity"] == "MEDIUM"
        assert findings[0]["confidence"] == 0.7
        assert findings[0]["evidence"]["messages_sent"] == 100


class TestWebSocketScannerFeatureFlag:
    """Scanner respects the WS_SCANNER feature flag."""

    def test_returns_empty_when_flag_off(self, ws_server_url):
        """When ARGUS_FF_WS_SCANNER is 'false', scan() returns []."""
        from feature_flags import get_feature_flags
        from tools.websocket_scanner import WebSocketScanner

        with patch.dict(os.environ, {"ARGUS_FF_WS_SCANNER": "false"}, clear=False):
            get_feature_flags().clear_cache()
            scanner = WebSocketScanner(timeout=5)

            async def _scan():
                return await scanner.scan(ws_server_url)

            findings = asyncio.run(_scan())
            assert findings == [], (
                f"Expected empty findings when flag is off, got {len(findings)}"
            )

    def test_returns_findings_when_flag_on(self, ws_server_url):
        """When ARGUS_FF_WS_SCANNER is 'true', scan() returns findings."""
        from feature_flags import get_feature_flags
        from tools.websocket_scanner import WebSocketScanner

        with patch.dict(os.environ, {"ARGUS_FF_WS_SCANNER": "true"}, clear=False):
            get_feature_flags().clear_cache()
            scanner = WebSocketScanner(timeout=5)

            async def _scan():
                return await scanner.scan(ws_server_url)

            findings = asyncio.run(_scan())
            assert len(findings) > 0, (
                "Expected findings when flag is on, got empty list"
            )


class TestWebSocketScannerDeps:
    """Scanner validates dependencies on construction."""

    def test_raises_without_websockets(self):
        """Without websockets library, constructor raises RuntimeError."""
        import tools.websocket_scanner as ws_mod

        original = ws_mod.HAS_WEBSOCKETS
        ws_mod.HAS_WEBSOCKETS = False

        from tools.websocket_scanner import WebSocketScanner

        with pytest.raises(RuntimeError, match="websockets library is required"):
            WebSocketScanner(timeout=5)

        ws_mod.HAS_WEBSOCKETS = original

    def test_raises_without_httpx(self):
        """Without httpx library, constructor raises RuntimeError."""
        import tools.websocket_scanner as ws_mod

        original = ws_mod.HAS_HTTPX
        ws_mod.HAS_HTTPX = False

        from tools.websocket_scanner import WebSocketScanner

        with pytest.raises(RuntimeError, match="httpx library is required"):
            WebSocketScanner(timeout=5)

        ws_mod.HAS_HTTPX = original


class TestWebSocketScannerSchema:
    """Each finding from every test method conforms to the expected schema."""

    REQUIRED_KEYS = {"type", "severity", "confidence", "endpoint", "evidence", "source_tool"}

    def test_all_finding_types_have_required_schema(self, ws_server_url):
        """All finding types include required schema keys."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _run_all():
            findings = []
            findings.extend(await scanner._test_origin_validation(ws_server_url))
            findings.extend(await scanner._test_auth_required(ws_server_url))
            findings.extend(await scanner._test_message_injection(ws_server_url))
            findings.extend(await scanner._test_rate_limiting(ws_server_url))
            return findings

        findings = asyncio.run(_run_all())

        for f in findings:
            missing = self.REQUIRED_KEYS - set(f.keys())
            assert not missing, f"Finding {f.get('type', '?')} missing keys: {missing}"
            assert f["endpoint"] == ws_server_url
            assert f["source_tool"] == "websocket_scanner"
            assert 0.0 <= f["confidence"] <= 1.0

    def test_severity_levels_valid(self, ws_server_url):
        """Severity is one of the allowed levels."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=5)

        async def _run_all():
            findings = []
            findings.extend(await scanner._test_origin_validation(ws_server_url))
            findings.extend(await scanner._test_auth_required(ws_server_url))
            findings.extend(await scanner._test_message_injection(ws_server_url))
            findings.extend(await scanner._test_rate_limiting(ws_server_url))
            return findings

        findings = asyncio.run(_run_all())
        valid_severities = {"INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"}

        for f in findings:
            assert f["severity"] in valid_severities, (
                f"Invalid severity '{f['severity']}' for {f['type']}"
            )


class TestWebSocketScannerEdgeCases:
    """Edge cases the scanner should handle gracefully."""

    def test_unreachable_url(self):
        """Scanning an unreachable URL returns empty list, doesn't crash."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=3)

        async def _scan():
            return await scanner.scan("wss://nonexistent-12345.example/ws")

        findings = asyncio.run(_scan())
        assert findings == []

    def test_scanner_initializes_with_custom_timeout(self):
        """Constructor accepts and stores a custom timeout."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner(timeout=42)
        assert scanner.timeout == 42

    def test_scanner_initializes_with_default_timeout(self):
        """Constructor defaults to 10s timeout when not specified."""
        from tools.websocket_scanner import WebSocketScanner

        scanner = WebSocketScanner()
        assert scanner.timeout == 10

    def test_decode_message_bytes(self):
        """_decode_message decodes bytes to string."""
        from tools.websocket_scanner import WebSocketScanner

        result = WebSocketScanner._decode_message(b"hello bytes")
        assert result == "hello bytes"

    def test_decode_message_string(self):
        """_decode_message returns strings as-is."""
        from tools.websocket_scanner import WebSocketScanner

        result = WebSocketScanner._decode_message("hello string")
        assert result == "hello string"
