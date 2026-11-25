"""Stdio MCP transport that drives a worker through the typed ``task_*`` methods.

The dispatcher owns scheduling, leases and graph writes; the worker only runs
one bounded job and returns a result. This bridge is the dispatcher-facing
:class:`~control_plane.dispatcher.WorkerRunner`: it starts ``mcp_server.py`` (or
a command from ``ARGUS_TASK_WORKER_CMD``), sends one typed JSON-RPC request per
job and hands the raw result back to the dispatcher for contract parsing.

Timeouts are real timeouts (``TimeoutError``) so the dispatcher may run the
same-session conclude fallback. A malformed reply or JSON-RPC error is a
``ProtocolError``. A process that exits, or a failed write, also becomes a
contract error; the next call starts a fresh session.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from control_plane.contracts import ProtocolError
from control_plane.task_service import (
    EXECUTOR_METHODS,
    MAX_REQUEST_BYTES,
    SCHEMA_VERSION,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def default_worker_command() -> list[str]:
    """The in-repo MCP worker, started with the current interpreter."""
    server = Path(__file__).resolve().parent.parent / "mcp_server.py"
    return [sys.executable, str(server)]


class MCPTaskBridge:
    """WorkerRunner implementation over newline-delimited JSON-RPC on stdio."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        *,
        worker_id: str = "mcp-task-worker",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        env: Mapping[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.command = list(command or default_worker_command())
        self.worker_id = worker_id
        #: Task types this transport can execute; the tick registers them.
        self.task_types = frozenset(EXECUTOR_METHODS.values())
        self.timeout_seconds = float(timeout_seconds)
        self._env = dict(env) if env is not None else None
        self._cwd = str(cwd) if cwd is not None else None
        self._process: subprocess.Popen[str] | None = None
        self._lines: Queue[str | None] | None = None
        self._next_id = 0
        self._lock = threading.Lock()

    # ----- WorkerRunner -----

    def supports(self, task_type: str) -> bool:
        return task_type in self.task_types

    def bootstrap(self, job: dict[str, Any], *, conclude: bool = False) -> Any:
        return self._call("task_bootstrap", "bootstrap", job, conclude)

    def reason(self, job: dict[str, Any]) -> Any:
        return self._call("task_reason", "reason", job, False)

    def explore(self, job: dict[str, Any], *, conclude: bool = False) -> Any:
        return self._call("task_explore", "explore", job, conclude)

    # ----- dispatcher-owned task control -----

    def generate_subtasks(
        self,
        task_id: str,
        subtasks: list[dict[str, Any]],
        *,
        existing_titles: list[str] | None = None,
    ) -> Any:
        return self._call(
            "task_generate_subtasks",
            "generate_subtasks",
            {
                "task_id": task_id,
                "subtasks": subtasks,
                "existing_titles": list(existing_titles or []),
            },
            False,
        )

    def refine_subtasks(
        self, task_id: str, operations: list[dict[str, Any]]
    ) -> Any:
        return self._call(
            "task_refine_subtasks",
            "refine_subtasks",
            {"task_id": task_id, "operations": operations},
            False,
        )

    def progress(
        self,
        task_id: str,
        subtask_id: str,
        event: dict[str, Any],
    ) -> Any:
        return self._call(
            "task_progress",
            "progress",
            {"task_id": task_id, "subtask_id": subtask_id, "event": event},
            False,
        )

    def cancel(self, task_id: str, reason: str) -> Any:
        return self._call(
            "task_cancel",
            "cancel",
            {"task_id": task_id, "reason": reason},
            False,
        )

    # ----- process lifecycle -----

    def _start(self) -> tuple[subprocess.Popen[str], Queue[str | None]]:
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            env=dict(os.environ, **self._env) if self._env else None,
            cwd=self._cwd,
        )
        lines: Queue[str | None] = Queue()

        def _pump() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(
            target=_pump, name=f"mcp-task-bridge-{self.worker_id}", daemon=True
        ).start()
        self._process = process
        self._lines = lines
        return process, lines

    def _ensure_process(self) -> tuple[subprocess.Popen[str], Queue[str | None]]:
        if self._process is not None and self._process.poll() is None and self._lines:
            return self._process, self._lines
        self.close()
        return self._start()

    def close(self) -> None:
        process, self._process = self._process, None
        self._lines = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def __enter__(self) -> MCPTaskBridge:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ----- transport -----

    def _call(
        self,
        method: str,
        task_type: str,
        job: dict[str, Any],
        conclude: bool,
    ) -> dict[str, Any]:
        params = {
            "schema_version": SCHEMA_VERSION,
            "task_type": task_type,
            "conclude": bool(conclude),
            "request": dict(job),
        }
        encoded = json.dumps(params, default=str).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ProtocolError(
                f"{method} request is {len(encoded)} bytes; "
                f"the limit is {MAX_REQUEST_BYTES}"
            )

        with self._lock:
            process, lines = self._ensure_process()
            self._next_id += 1
            request_id = self._next_id
            message = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                },
                default=str,
            )
            try:
                assert process.stdin is not None
                process.stdin.write(message + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.close()
                raise ProtocolError(f"{method} could not be sent: {exc}") from exc

            try:
                line = lines.get(timeout=self.timeout_seconds)
            except Empty:
                self.close()
                raise TimeoutError(
                    f"{method} timed out after {self.timeout_seconds:g}s"
                ) from None

            if line is None:
                self.close()
                raise ProtocolError(f"{method}: worker exited before replying")
            if len(line.encode("utf-8", errors="ignore")) > MAX_RESPONSE_BYTES:
                self.close()
                raise ProtocolError(f"{method}: worker reply exceeds the size limit")

            try:
                reply = json.loads(line)
            except json.JSONDecodeError as exc:
                self.close()
                raise ProtocolError(f"{method}: worker reply is not JSON: {exc}") from exc

            if not isinstance(reply, Mapping):
                raise ProtocolError(f"{method}: worker reply must be an object")
            if reply.get("id") != request_id:
                raise ProtocolError(
                    f"{method}: worker reply id {reply.get('id')!r} "
                    f"does not match request {request_id}"
                )
            if "error" in reply:
                raise ProtocolError(f"{method} failed: {reply['error']}")
            result = reply.get("result")
            if not isinstance(result, Mapping):
                raise ProtocolError(f"{method}: worker result must be an object")
            return dict(result)


def worker_runner_from_env() -> MCPTaskBridge | None:
    """Build the live worker transport, or ``None`` when none is configured."""
    command = os.getenv("ARGUS_TASK_WORKER_CMD", "").strip()
    if not command:
        return None
    try:
        timeout = float(os.getenv("ARGUS_TASK_TIMEOUT_SECONDS", "120"))
    except ValueError:
        logger.warning("ARGUS_TASK_TIMEOUT_SECONDS is not a number; using 120")
        timeout = DEFAULT_TIMEOUT_SECONDS
    return MCPTaskBridge(
        shlex.split(command),
        worker_id=os.getenv("ARGUS_CONTROL_PLANE_WORKER_ID", "mcp-task-worker"),
        timeout_seconds=timeout,
        cwd=os.getenv("ARGUS_TASK_WORKER_CWD") or None,
    )
