"""
Agent Session Store — In-memory state persistence for hybrid LLM planning.

Each assessment phase gets one session. Sessions live in-memory on the
Python MCP server (ephemeral per assessment). Long-term persistence is
via SQLite tool_execution_log — the session store is a performance
optimization, not a durability requirement.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class ToolExecution:
    """Record of a single tool execution within an agent session."""

    tool: str
    arguments: dict
    reasoning: str
    success: bool
    duration_ms: int
    finding_count: int
    summary: str


@dataclass
class AgentSession:
    """State container for one assessment phase."""

    session_id: str
    target: str
    phase: str
    created_at: int
    tech_stack: list[str]
    tool_history: list[ToolExecution] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    current_plan: list[str] | None = None
    plan_step: int = 0
    trigger: str | None = None


class AgentSessionStore:
    """In-memory store for agent sessions keyed by session_id.

    Sessions are ephemeral — they live for the duration of one assessment
    phase and are discarded when the assessment completes.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        self._eviction_ttl = 3600  # 1 hour
        self._last_eviction = time.time()
        self._start_eviction_loop()

    def create(
        self,
        target: str,
        phase: str,
        tech_stack: list[str] | None = None,
    ) -> str:
        """Create a new agent session and return its session_id.

        Args:
            target: The target being assessed (URL, repo path, etc.).
            phase: The assessment phase (e.g. \"recon\", \"vuln-scan\").
            tech_stack: Technology stack detected for the target.

        Returns:
            A unique session identifier (uuid4 hex string).
        """
        self._evict_expired()
        session_id = uuid4().hex
        with self._lock:
            self._sessions[session_id] = AgentSession(
                session_id=session_id,
                target=target,
                phase=phase,
                created_at=int(time.time()),
                tech_stack=tech_stack or [],
            )
        return session_id

    def _evict_expired(self) -> None:
        """Remove sessions that have exceeded the TTL."""
        now = time.time()
        if now - self._last_eviction < 300:  # only evict every 5 mins
            return
        self._last_eviction = now
        with self._lock:
            expired = [sid for sid, s in self._sessions.items()
                       if now - s.created_at > self._eviction_ttl]
            for sid in expired:
                del self._sessions[sid]

    def _start_eviction_loop(self) -> None:
        """Background thread for periodic eviction."""
        def _loop():
            while True:
                time.sleep(300)
                self._evict_expired()
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def get(self, session_id: str) -> AgentSession:
        """Retrieve a session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            The AgentSession instance.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            if session_id not in self._sessions:
                raise ValueError(f"Session {session_id} not found")
            return self._sessions[session_id]

    def add_execution(self, session_id: str, execution: ToolExecution) -> None:
        """Record a tool execution in the session history.

        Args:
            session_id: The session identifier.
            execution: The ToolExecution to append.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            session.tool_history.append(execution)

    def add_observation(self, session_id: str, observation: str) -> None:
        """Add an LLM-readable observation summary to the session.

        Args:
            session_id: The session identifier.
            observation: Summary text of tool output.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            session.observations.append(observation)

    def set_plan(self, session_id: str, plan: list[str]) -> None:
        """Set the current hybrid plan for the session and reset step counter.

        Args:
            session_id: The session identifier.
            plan: Ordered list of tool names to execute.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            session.current_plan = plan
            session.plan_step = 0

    def advance_plan(self, session_id: str) -> str | None:
        """Return the next tool name in the plan, or None if complete.

        When the plan is exhausted the caller should invoke the LLM to
        produce a new plan or mark the phase as done.

        Args:
            session_id: The session identifier.

        Returns:
            The next tool name, or None if all steps have been consumed.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            if session.current_plan is not None and session.plan_step < len(session.current_plan):
                tool = session.current_plan[session.plan_step]
                session.plan_step += 1
                return tool
        return None

    def add_finding(self, session_id: str, finding: dict) -> None:
        """Append a finding to the session's accumulated findings.

        Args:
            session_id: The session identifier.
            finding: A NormalizedFinding-compatible dict produced by a tool.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError(f"Session {session_id} not found")
            session.findings.append(finding)
