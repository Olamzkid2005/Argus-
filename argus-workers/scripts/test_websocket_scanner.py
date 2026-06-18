#!/usr/bin/env python3
"""
Test the WebSocketScanner against a local WebSocket server.

Starts an intentionally insecure WebSocket echo server, discovers its URL,
runs the WebSocketScanner against it, and reports findings.

Usage:
    ARGUS_FF_WS_SCANNER=true python scripts/test_websocket_scanner.py
"""

import asyncio
import logging
import os
import sys
import threading
import time

# Enable the feature flag for the scanner
os.environ["ARGUS_FF_WS_SCANNER"] = "true"

# Set up path to find argus-workers modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("test_ws_scanner")

# ── Intentional insecure WebSocket echo server ──


class TestWsServerProtocol:
    """A deliberately insecure WebSocket server for testing.

    Security weaknesses baked in:
    - No origin validation (accepts any Origin header)
    - No authentication required
    - Echoes all received messages back (no sanitization)
    - No rate limiting on messages
    """

    def __init__(self):
        self.server = None

    async def handler(self, websocket):
        """Echo all received messages back."""
        logger.info("  → WebSocket client connected from %s", websocket.remote_address)
        async for message in websocket:
            logger.info("  ← Echoing message (%d bytes)", len(message))
            try:
                await websocket.send(message)
            except Exception:
                break

    async def start(self, host="127.0.0.1", port=0):
        """Start the server and return (url, port)."""
        import websockets.asyncio.server

        self.server = await websockets.asyncio.server.serve(
            self.handler,
            host,
            port,
        )
        port = self.server.sockets[0].getsockname()[1]
        url = f"ws://{host}:{port}"
        logger.info("Test WebSocket server started at %s", url)
        return url, port

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Test WebSocket server stopped")


# ── Run server in a thread, then scan ──


def run_server_in_thread(url_holder: list):
    """Run the server in a background thread."""

    async def _start():
        server = TestWsServerProtocol()
        url, port = await server.start()
        url_holder.append(url)
        # Keep running until interrupted
        while True:
            await asyncio.sleep(3600)

    asyncio.run(_start())


def main():
    logger.info("═" * 60)
    logger.info("WebSocketScanner Integration Test")
    logger.info("═" * 60)

    # 1. Start the test server in a background thread
    url_holder: list[str] = []
    server_thread = threading.Thread(
        target=run_server_in_thread,
        args=(url_holder,),
        daemon=True,
    )
    server_thread.start()
    time.sleep(1)  # Wait for server to start

    if not url_holder:
        logger.error("Failed to start test WebSocket server")
        sys.exit(1)

    ws_url = url_holder[0]
    logger.info("")
    logger.info("Target WebSocket URL: %s", ws_url)

    # 2. Run the WebSocketScanner
    logger.info("")
    logger.info("─" * 60)
    logger.info("Running WebSocketScanner...")
    logger.info("─" * 60)

    sys.path.insert(0, "argus-workers")
    from tools.websocket_scanner import WebSocketScanner

    async def run_scan():
        scanner = WebSocketScanner(timeout=5)
        findings = await scanner.scan(ws_url)
        return findings

    findings = asyncio.run(run_scan())

    # 3. Report results
    logger.info("")
    logger.info("═" * 60)
    logger.info("SCAN RESULTS: %d finding(s)", len(findings))
    logger.info("═" * 60)

    if not findings:
        logger.warning("No findings were produced!")
        logger.warning("This may indicate the scanner isn't working correctly.")
        return

    for i, f in enumerate(findings, 1):
        logger.info("")
        logger.info("Finding #%d: %s", i, f.get("type", "UNKNOWN"))
        logger.info("  Severity:  %s", f.get("severity", "?"))
        logger.info("  Confidence: %.1f", f.get("confidence", 0))
        logger.info("  Endpoint:  %s", f.get("endpoint", "?"))
        evidence = f.get("evidence", {})
        if isinstance(evidence, dict):
            for k, v in evidence.items():
                if k != "server_response":  # Skip potentially long responses
                    logger.info("  Evidence:  %s = %s", k, v)

    logger.info("")
    logger.info("═" * 60)
    logger.info("Test %s", "✓ PASSED" if findings else "✗ FAILED (no findings)")
    logger.info("═" * 60)


if __name__ == "__main__":
    main()
