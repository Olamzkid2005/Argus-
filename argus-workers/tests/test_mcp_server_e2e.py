"""
Lightweight MCP test server for E2E tests.

This is a minimal server that mimics the real mcp_server.py's main()
function but with no heavy initialization (no tool loading, no DNS
check, no preflight, no health server). It registers the same set of
handlers so we can validate the JSON-RPC protocol end-to-end without
waiting for the real server's slow startup.

Usage (spawned as subprocess from tests):
    python tests/test_mcp_server_e2e.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the parent directory (argus-workers/) is on sys.path so we can
# import mcp_transport when running directly from tests/
_SCRIPT_DIR = Path(__file__).resolve().parent
_PARENT_DIR = str(_SCRIPT_DIR.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from mcp_transport import MCPTransport, create_ping_handler

    transport = MCPTransport()

    # ── Standard handlers (same as real mcp_server.py) ──
    transport.register("ping", create_ping_handler())

    def handle_echo(params: dict | None) -> dict:
        """Echo back params — useful for testing argument passing."""
        return {"echo": params or {}}

    transport.register("echo", handle_echo)

    def handle_list_tools(params: dict | None) -> dict:
        """Return a minimal set of mock tool definitions."""
        return {
            "tools": [
                {
                    "name": "nuclei",
                    "description": "Fast and customisable vulnerability scanner",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "description": "Target URL/domain"},
                        },
                        "required": ["target"],
                    },
                    "capabilities": ["vuln_scan"],
                    "signal_quality": "CONFIRMED",
                },
                {
                    "name": "nmap",
                    "description": "Network discovery and security scanning",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string", "description": "Target host/IP"},
                        },
                        "required": ["target"],
                    },
                    "capabilities": ["port_scan"],
                    "signal_quality": "CONFIRMED",
                },
            ]
        }

    transport.register("list_tools", handle_list_tools)

    def handle_call_tool(params: dict | None) -> dict:
        """Mock tool execution — returns canned output."""
        name = params.get("name", "") if params else ""
        return {
            "content": [{"type": "text", "text": f"Mock execution of {name}"}],
            "isError": False,
            "meta": {"tool": name, "duration_ms": 42, "success": True},
        }

    transport.register("call_tool", handle_call_tool)

    def handle_agent_init(params: dict | None) -> dict:
        """Mock agent init — returns a test session."""
        return {
            "session_id": "test-session-001",
            "plan": ["nuclei", "nmap"],
            "reasoning": "Test plan",
            "phase": params.get("phase", "") if params else "",
            "hypotheses": [],
        }

    transport.register("agent_init", handle_agent_init)

    def handle_agent_next(params: dict | None) -> dict:
        """Mock agent next — returns done."""
        return {"done": True, "session_id": "test-session-001"}

    transport.register("agent_next", handle_agent_next)

    def handle_agent_observe(params: dict | None) -> dict:
        """Mock agent observe — returns done."""
        return {"done": True, "session_id": "test-session-001", "iteration": 1}

    transport.register("agent_observe", handle_agent_observe)

    def handle_get_checkpoint(params: dict | None) -> dict:
        """Mock checkpoint handler."""
        return {"completed_tools": []}

    transport.register("get_checkpoint", handle_get_checkpoint)

    def handle_acquire_lock(params: dict | None) -> dict:
        """Mock lock acquisition."""
        return {"acquired": True}

    transport.register("acquire_lock", handle_acquire_lock)

    def handle_release_lock(params: dict | None) -> dict:
        """Mock lock release."""
        return {"released": True}

    transport.register("release_lock", handle_release_lock)

    def handle_cancel(params: dict | None) -> dict:
        """Mock cancel handler."""
        return {"cancelled": True}

    transport.register("cancel", handle_cancel)

    def handle_get_attack_graph(params: dict | None) -> dict:
        """Mock attack graph handler."""
        return {"chains": [], "paths": [], "chain_plans": []}

    transport.register("get_attack_graph", handle_get_attack_graph)

    def handle_phase_complete(params: dict | None) -> dict:
        """Mock phase complete handler."""
        return {"next_capabilities": [], "reasoning": "Test complete", "stop": True}

    transport.register("phase_complete", handle_phase_complete)

    logger = logging.getLogger(__name__)
    logger.info("Test MCP server starting — registrations:")
    logger.info("  ping, echo, list_tools, call_tool, agent_init")
    logger.info("  agent_next, agent_observe, get_checkpoint")
    logger.info("  acquire_lock, release_lock, cancel")
    logger.info("  get_attack_graph, phase_complete")

    logger.info("Test MCP stdio transport running")
    transport.run()


if __name__ == "__main__":
    main()
