#!/usr/bin/env python3
"""
Mock Celery Worker Bridge — Consumes jobs from Redis queues and
executes task functions with mocked external dependencies (LLM, tools).

This script is launched as a subprocess by the E2E test. It:
1. Patches llm_client and tools.tool_runner BEFORE any task modules import them
2. Connects to Redis and BLPOPs from Celery queues
3. Deserializes Celery messages and dispatches to task functions
4. Stores results back to Redis for the test to inspect

Usage:
    python3 mock_worker_bridge.py [--db-url DATABASE_URL] [--redis-url REDIS_URL]
"""

import argparse
import importlib
import json
import logging
import os
import sys
import time
import traceback

# ─── Apply patches BEFORE any task modules are imported ──────────────────────
# These patches replace external dependencies with mocks so tests run
# without real LLM API keys, real security tools, or network access.
import unittest.mock as mock
import uuid

# ── Mock LLM client ──────────────────────────────────────────────────────────
# Replace the real LLMClient with one that returns canned responses.
# The system falls back to deterministic mode when is_available() is False,
# which tests the fallback pipeline. If we want agent mode, we return True
# and provide fake responses.

MOCK_LLM_RESPONSES = {
    "default": json.dumps({
        "tool": "nuclei",
        "arguments": {"target": "{target}", "template": "misconfiguration"},
        "reasoning": "Mock: Testing basic recon with nuclei",
        "confidence": 0.8,
        "cost_usd": 0.0,
    }),
    "analysis": json.dumps({
        "actions": [
            {"type": "deep_scan", "tool": "nuclei", "reasoning": "Mock analysis action", "priority": "HIGH"}
        ],
        "priorities": ["nuclei"],
        "summary": "Mock analysis completed"
    }),
}

_mock_llm = mock.MagicMock()
_mock_llm.is_available.return_value = False  # Force deterministic fallback
_mock_llm.chat_sync.return_value = MOCK_LLM_RESPONSES["default"]
_mock_llm.chat_async = mock.AsyncMock(return_value=MOCK_LLM_RESPONSES["default"])


class MockLLMClient:
    """Drop-in replacement for LLMClient that returns canned responses."""

    def __init__(self, *args, **kwargs):
        self.provider = "mock"
        self.model = "mock-model"
        self.api_key = None
        self.max_retries = 0

    def is_available(self):
        return False  # Force deterministic fallback

    def chat_sync(self, *args, **kwargs):
        return MOCK_LLM_RESPONSES["default"]

    async def chat_async(self, *args, **kwargs):
        return MOCK_LLM_RESPONSES["default"]

    def chat(self, *args, **kwargs):
        return MOCK_LLM_RESPONSES["default"]


def _make_mock_response(text="Mock response", input_tokens=0, output_tokens=0, cost_usd=0.0):
    """Create a mock LLMResponse-like object."""
    resp = mock.MagicMock()
    resp.text = text
    resp.input_tokens = input_tokens
    resp.output_tokens = output_tokens
    resp.cost_usd = cost_usd
    return resp


# ── Mock Tool Runner ─────────────────────────────────────────────────────────
# Instead of running real subprocess tools (nuclei, sqlmap, etc.), return
# realistic fixture findings that the parsers can process.

FIXTURE_FINDINGS = [
    {
        "type": "SQL_INJECTION",
        "severity": "HIGH",
        "confidence": 0.85,
        "endpoint": "https://example.com/login",
        "evidence": {
            "payload": "' OR 1=1--",
            "parameter": "username",
            "method": "POST",
            "response_snippet": "SQL syntax error near OR 1=1"
        },
        "source_tool": "nuclei",
        "description": "SQL injection detected in login form via classic payload",
        "remediation": "Use parameterized queries instead of string concatenation",
        "cvss_score": 8.5,
        "cwe_id": "CWE-89",
        "owasp_category": "A03:2021-Injection",
    },
    {
        "type": "XSS_REFLECTED",
        "severity": "MEDIUM",
        "confidence": 0.75,
        "endpoint": "https://example.com/search",
        "evidence": {
            "payload": "<script>alert(1)</script>",
            "parameter": "q",
            "method": "GET",
            "response_snippet": "<script>alert(1)</script>"
        },
        "source_tool": "dalfox",
        "description": "Reflected XSS in search parameter",
        "remediation": "Encode HTML output, implement Content-Security-Policy",
        "cvss_score": 6.1,
        "cwe_id": "CWE-79",
        "owasp_category": "A03:2021-Injection",
    },
    {
        "type": "MISCONFIGURATION",
        "severity": "LOW",
        "confidence": 0.6,
        "endpoint": "https://example.com/.env",
        "evidence": {
            "response_code": 200,
            "content_type": "text/plain",
        },
        "source_tool": "httpx",
        "description": "Exposed .env file accessible via web root",
        "remediation": "Block access to sensitive files via web server configuration",
        "cvss_score": 3.5,
        "cwe_id": "CWE-200",
        "owasp_category": "A05:2021-Security Misconfiguration",
    },
    {
        "type": "INFO_DISCLOSURE",
        "severity": "INFO",
        "confidence": 0.5,
        "endpoint": "https://example.com/robots.txt",
        "evidence": {
            "content": "Disallow: /admin/\nDisallow: /private/"
        },
        "source_tool": "httpx",
        "description": "robots.txt reveals restricted paths",
        "remediation": "Review robots.txt for sensitive path disclosure",
        "cvss_score": 0.0,
        "cwe_id": "CWE-200",
        "owasp_category": "A05:2021-Security Misconfiguration",
    },
]


class MockToolRunner:
    """Drop-in replacement for ToolRunner that returns fixture findings.

    Accepts all constructor args that the real ToolRunner takes,
    but ignores them — just returns fixture findings on .run().
    """

    def __init__(self, *args, **kwargs):
        self.findings_index = 0
        self.engagement_id = kwargs.get("engagement_id", "")

    def cleanup(self):
        """No-op cleanup matching real ToolRunner interface."""
        pass

    def run(self, tool_name="", target="", **kwargs):
        """Return fixture findings instead of running real tools.

        Returns a simple object with the attributes the pipeline expects:
          - .status, .findings, .errors, .duration, .success, .stdout, .stderr, .tool
        """
        class FakeToolResult:
            status = "completed"
            findings = FIXTURE_FINDINGS
            errors = []
            duration = 0.1
            success = True
            tool = tool_name
            stdout = json.dumps(FIXTURE_FINDINGS)
            stderr = ""
            output = json.dumps(FIXTURE_FINDINGS)
        return FakeToolResult()

    def run_streaming(self, *args, **kwargs):
        """Streaming variant — returns the same fixture findings."""
        return self.run(*args, **kwargs)

    def run_async(self, tool_name, target, **kwargs):
        """Async variant returning fixture findings."""
        return self.run(tool_name, target, **kwargs)


# Patch the modules before they can be imported by task modules
_PATCHED_MODULES = {}


def _install_patches():
    """Install all module-level patches for external dependencies.

    Strategy:
    - LLM: Only mock if no API key is set. When OPENAI_API_KEY or LLM_API_KEY
      is available, use the REAL LLM client.
    - ToolRunner: Always mocked (returns fixture findings, prevents real execution).
    - streaming/websocket: Mocked (no WS connections in test).
    - mcp_server: Properly faked (MagicMock breaks Python import machinery).
    """
    has_llm_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY"))

    if not has_llm_key:
        # Patch llm_client — deterministic fallback
        mock_llm_mod = mock.MagicMock()
        mock_llm_mod.LLMClient = MockLLMClient
        mock_llm_mod.LLMResponse = mock.MagicMock()
        sys.modules["llm_client"] = mock_llm_mod
        _PATCHED_MODULES["llm_client"] = mock_llm_mod
        logger = logging.getLogger("mock_worker")
        logger.info("LLM: Mocked (no API key) — using deterministic fallback")
    else:
        logger = logging.getLogger("mock_worker")
        logger.info("LLM: Using real client with API key from environment")

    # Patch tools.tool_runner
    mock_tool_mod = mock.MagicMock()
    mock_tool_mod.ToolRunner = MockToolRunner
    mock_tool_mod.SecurityError = Exception
    sys.modules["tools.tool_runner"] = mock_tool_mod
    _PATCHED_MODULES["tools.tool_runner"] = mock_tool_mod

    # Patch streaming (prevent WebSocket connects during test)
    mock_streaming = mock.MagicMock()
    mock_streaming.StreamManager = mock.MagicMock()
    mock_streaming.emit_event = mock.MagicMock()
    sys.modules["streaming"] = mock_streaming
    _PATCHED_MODULES["streaming"] = mock_streaming

    # Patch websocket_events
    mock_ws = mock.MagicMock()
    sys.modules["websocket_events"] = mock_ws
    _PATCHED_MODULES["websocket_events"] = mock_ws

    # Patch mcp_server — provide a proper fake module, not a MagicMock.
    # The real mcp_server.py exports: MCPServer, ToolDefinition, ToolSchema, get_mcp_server
    class _FakeToolDef:
        """Minimal ToolDefinition stand-in."""
        def __init__(self, name="", command="", description="", args=None,
                     parameters=None, timeout=300, **kw):
            self.name = name or "mock-tool"
            self.command = command or "/bin/echo"
            self.description = description or "Mock tool"
            self.args = args or []
            self.parameters = parameters or []
            self.timeout = timeout

    class _FakeToolSchema:
        """Minimal ToolSchema stand-in."""
        def __init__(self, name="", type="string", description="", **kw):
            self.name = name
            self.type = type
            self.description = description

    class _FakeMCPServer:
        def __init__(self, *a, **kw):
            self.tools = []
        def get_tools(self):
            return []
        def register_tool(self, *a, **kw):
            pass

    class _FakeModule:
        """Stand-in for the mcp_server module."""
        MCPServer = _FakeMCPServer
        ToolDefinition = _FakeToolDef
        ToolSchema = _FakeToolSchema
        get_mcp_server = staticmethod(lambda *_, **__: _FakeMCPServer())

    sys.modules["mcp_server"] = _FakeModule()
    _PATCHED_MODULES["mcp_server"] = True  # mark as patched


def parse_celery_message(queue_key: str, raw: bytes) -> dict | None:
    """
    Parse a Celery v5.x Redis message.

    The Next.js server pushes messages in this format (redis.ts):
      body = base64(JSON.stringify([args, kwargs, embed]))
      message = JSON.stringify({
        body: bodyBase64,
        headers: { task: "tasks.recon.run_recon", id: "..." },
        properties: { body_encoding: "base64" },
      })

    Returns dict with task_name, args, kwargs if parseable, None otherwise.
    """
    try:
        data = json.loads(raw)
        headers = data.get("headers", {}) or {}
        task_name = headers.get("task") or data.get("task")
        task_id = headers.get("id") or data.get("id")

        body_raw = data.get("body")
        if body_raw:
            import base64
            try:
                body_bytes = base64.b64decode(body_raw)
            except Exception:
                body_bytes = body_raw.encode("utf-8") if isinstance(body_raw, str) else body_raw
            try:
                body_data = json.loads(body_bytes)
            except json.JSONDecodeError:
                body_data = json.loads(body_raw) if isinstance(body_raw, str) else None
        else:
            body_data = data

        # Celery v5 body format: [args_list, kwargs_dict, embed_or_null]
        args_list = []
        kwargs_dict = {}
        if isinstance(body_data, list):
            if len(body_data) >= 1 and isinstance(body_data[0], list):
                args_list = body_data[0]
            if len(body_data) >= 2 and isinstance(body_data[1], dict):
                kwargs_dict = body_data[1]
            if len(body_data) >= 2 and not isinstance(body_data[1], dict):
                # Some formats have args as first element
                pass

        return {
            "task": task_name or "",
            "args": args_list,
            "kwargs": kwargs_dict,
            "id": task_id or "",
        }
    except (json.JSONDecodeError, UnicodeDecodeError, Exception) as e:
        logging.getLogger("mock_worker").warning(f"parse_celery_message failed: {e}")
        return None


# ── Known task routing ──
TASK_QUEUE_MAP = {
    "recon": "recon",
    "scan": "scan",
    "analyze": "analyze",
    "report": "report",
}

QUEUES = ["celery", "recon", "scan", "analyze", "report", "repo_scan"]


def _make_mock_task_context(
    task_name: str,
    engagement_id: str,
    trace_id: str = "",
    db_conn_string: str = "",
    redis_url: str = "",
):
    """Build a mock TaskContext shaped like the real TaskContext dataclass.

    Follows the pattern from test_full_scan_pipeline_e2e.py.
    """
    ctx = mock.MagicMock()
    ctx.trace_id = trace_id or uuid.uuid4().hex
    ctx.engagement_id = engagement_id
    ctx.job_type = task_name
    ctx.job = {
        "type": task_name,
        "engagement_id": engagement_id,
        "trace_id": ctx.trace_id,
    }
    ctx.db_conn_string = db_conn_string or os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/argus_test")
    ctx.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")

    # Orchestrator stubs
    orch = mock.MagicMock()
    orch.engagement_id = engagement_id
    orch.trace_id = ctx.trace_id
    ctx.orchestrator = orch

    # State machine stub
    ctx.state = mock.MagicMock()
    ctx.state.current_state = "created"
    ctx.orchestrator.state = ctx.state

    return ctx


class _CapturingContext:
    """Minimal context manager wrapping a mock TaskContext."""

    def __init__(self, ctx):
        self._ctx = ctx

    def __enter__(self):
        return self._ctx

    def __exit__(self, *args):
        return False


def execute_task(task_info: dict, redis_url: str = "") -> dict:
    """
    Execute a Celery task function directly with the given arguments.
    Uses the real task functions but with mocked external deps.
    Follows the proven pattern from test_full_scan_pipeline_e2e.py.
    """
    task_name = task_info.get("task", "")
    raw_args = task_info.get("args", [])
    raw_kwargs = task_info.get("kwargs", {})

    if not task_name:
        return {"status": "error", "error": "No task name"}

    logger = logging.getLogger("mock_worker")

    # Determine engagement_id from args (varies by task, but args[0] is always engagement_id)
    engagement_id = raw_args[0] if raw_args else ""
    trace_id = raw_kwargs.get("trace_id", f"mock-{uuid.uuid4().hex[:8]}")

    try:
        # Import the module dynamically (patches are already applied at import time)
        if task_name.startswith("tasks."):
            module_path, func_name = task_name.rsplit(".", 1)
        else:
            module_path = f"tasks.{task_name.split('.')[0]}"
            func_name = task_name.split(".")[-1] if "." in task_name else task_name

        module = importlib.import_module(module_path)
        task_func = getattr(module, func_name, None)

        if task_func is None:
            return {"status": "error", "error": f"Function {func_name} not found in {module_path}"}

        # Build a mock task context following the existing test pattern
        ctx = _make_mock_task_context(
            task_name, engagement_id, trace_id,
            db_conn_string=os.getenv("DATABASE_URL", ""),
            redis_url=redis_url or os.getenv("REDIS_URL", "redis://localhost:6379"),
        )

        # Determine what the task context should return based on task phase
        # This follows the pattern from test_full_scan_pipeline_e2e.py where
        # the orchestrator mock returns phase-appropriate fixtures.
        phase = task_name.split(".")[-1] if "." in task_name else ""

        logger.info(f"Executing task: {task_name} phase={phase} eid={engagement_id[:12]}")

        # Patch task_context and app for this execution
        with (
            mock.patch(f"{module_path}.task_context", side_effect=lambda *_, **__: _CapturingContext(ctx)),
            mock.patch(f"{module_path}.app.send_task", side_effect=lambda *_, **__: mock.MagicMock(id=f"mock-{uuid.uuid4().hex[:8]}")),
        ):
            # Call .run() — the Celery task's actual implementation
            result = task_func.run(*raw_args, **raw_kwargs)

        return {"status": "completed", "result": str(result)[:500] if result else "ok"}

    except Exception as e:
        logger.error(f"Task {task_name} failed: {e}")
        logger.debug(traceback.format_exc())
        return {"status": "error", "error": str(e)[:300]}


def main():
    parser = argparse.ArgumentParser(description="Mock Celery worker bridge")
    parser.add_argument("--redis-url", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--db-url", default=None, help="Database URL (optional)")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Redis poll interval")
    parser.add_argument("--exit-after", type=int, default=0, help="Exit after N seconds (0 = run forever)")
    args = parser.parse_args()

    # Install patches before anything else
    _install_patches()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s MOCK_WORKER %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("mock_worker")

    # Set DB URL if provided
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    # Connect to Redis
    import redis as redis_lib
    r = redis_lib.from_url(args.redis_url)

    logger.info(f"Connected to Redis: {args.redis_url}")
    logger.info(f"Watching queues: {QUEUES}")
    logger.info("Mock worker ready — waiting for tasks...")

    start_time = time.time()
    task_count = 0

    try:
        while True:
            if args.exit_after > 0 and (time.time() - start_time) > args.exit_after:
                logger.info(f"Exit timeout reached ({args.exit_after}s), shutting down")
                break

            # BLPOP from all queues with timeout
            result = r.blpop(QUEUES, timeout=args.poll_interval)
            if result is None:
                continue

            queue_name, raw_data = result
            raw_data_bytes = raw_data if isinstance(raw_data, bytes) else raw_data.encode("utf-8")

            # Parse Celery message
            task_info = parse_celery_message(queue_name, raw_data_bytes)
            if task_info is None:
                logger.warning(f"Unparseable message on {queue_name}: {raw_data[:200]}")
                continue

            task_count += 1
            task_name = task_info.get("task", "unknown")
            logger.info(f"[{task_count}] Received: {task_name} on queue:{queue_name}")

            # Execute the task
            execution_result = execute_task(task_info, redis_url=args.redis_url)

            if execution_result["status"] == "completed":
                logger.info(f"[{task_count}] Completed: {task_name}")
            else:
                logger.error(f"[{task_count}] Failed: {task_name} — {execution_result.get('error')}")

    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
    finally:
        r.close()
        logger.info(f"Processed {task_count} tasks")


if __name__ == "__main__":
    main()
