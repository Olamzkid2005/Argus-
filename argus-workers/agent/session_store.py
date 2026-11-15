"""
Agent Session Store — In-memory state persistence for hybrid LLM planning.

Each assessment phase gets one session. Sessions live in-memory on the
Python MCP server (ephemeral per assessment). Long-term persistence is
via SQLite tool_execution_log — the session store is a performance
optimization, not a durability requirement.
"""

from __future__ import annotations

import copy
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
    # Non-secret identity label the action used, when one was named. This is
    # provenance metadata only; secret values are redacted before recording.
    identity: str = ""


@dataclass
class AgentSession:
    """State container for one assessment phase."""

    session_id: str
    target: str
    phase: str
    created_at: int
    tech_stack: list[str]
    last_accessed_at: int = 0
    tool_history: list[ToolExecution] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    current_plan: list[str] | None = None
    plan_step: int = 0
    trigger: str | None = None
    # Shared iteration counter for TS/Python coordination (blocker 32)
    execution_iteration: int = 0
    # Engagement this phase belongs to. The driver passes it in `agent_init`;
    # without it the agent cannot load the persisted ReconContext (so the LLM
    # selection branch never reacts to recon) and cannot record decisions.
    engagement_id: str = ""
    # Who authored `current_plan`: "llm" or "deterministic". Overall provenance
    # for logs; the audit trail uses the per-step `plan_sources` instead, since
    # a plan can start with engine choices and end with deterministic ones.
    plan_source: str = ""
    # Per-step provenance, parallel to `current_plan`: "llm" for a tool the
    # engine chose, "deterministic" for one the fallback order supplied.
    plan_sources: list[str] = field(default_factory=list)
    # Per-step arguments, parallel to `current_plan` (Stage 5.1 item 2). A step
    # is (tool, arguments), so the choice's arguments reach the executor instead
    # of being discarded when the plan is reduced to tool names.
    plan_arguments: list[dict] = field(default_factory=list)
    # Action signatures already issued (signature -> tool) and how many times
    # each tool ran. Dedupe is by whole action, not by tool name, so a revisit
    # with different arguments is a different action (Stage 5.1 item 3).
    action_signatures: dict[str, str] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)
    # Tool names that actually executed, for required-coverage accounting.
    executed_tools: list[str] = field(default_factory=list)
    stop_requested: bool = False
    required_coverage: list[str] = field(default_factory=list)
    # Structured, engagement-keyed observations mirrored on the session so the
    # replan prompt can include discovered endpoints/parameters (Stage 5.1).
    structured_observations: list[dict] = field(default_factory=list)
    # 2.2 protocol: exactly one advancement owner. `agent_next` issues an
    # action (with a stable action_id); `agent_observe` only acknowledges it.
    # The last issued action is remembered so an observation for an unknown
    # or already-consumed action can be rejected instead of silently skipped.
    last_action_id: str = ""
    last_action_tool: str = ""
    action_counter: int = 0


class AgentSessionStore:
    """In-memory store for agent sessions keyed by session_id.

    Sessions are ephemeral — they live for the duration of one assessment
    phase and are discarded when the assessment completes.
    """

    # Class-level guard to prevent unbounded eviction-thread accumulation.
    # Each AgentSessionStore instance would otherwise spawn a new daemon
    # thread, which becomes a problem if multiple instances are created
    # (e.g. during test fixtures or if the MCP server singleton pattern
    # is bypassed). The thread is daemon=True so it won't prevent shutdown.
    _eviction_thread_started: bool = False

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}
        self._lock = threading.Lock()
        # Use 2-hour TTL to cover the maximum assessment phase duration (7200s).
        # Actively-used sessions are never evicted because every access method
        # bumps last_accessed_at.
        self._eviction_ttl = 7200  # 2 hours
        self._last_eviction = time.time()
        self._start_eviction_loop()

    def create(
        self,
        target: str,
        phase: str,
        tech_stack: list[str] | None = None,
        engagement_id: str | None = None,
    ) -> str:
        """Create a new agent session and return its session_id.

        Args:
            target: The target being assessed (URL, repo path, etc.).
            phase: The assessment phase (e.g. \"recon\", \"vuln-scan\").
            tech_stack: Technology stack detected for the target.
            engagement_id: Engagement this phase belongs to, so the persisted
                recon context can be loaded and decisions can be recorded.

        Returns:
            A unique session identifier (uuid4 hex string).
        """
        self._evict_expired()
        now = int(time.time())
        session_id = uuid4().hex
        with self._lock:
            self._sessions[session_id] = AgentSession(
                session_id=session_id,
                target=target,
                phase=phase,
                created_at=now,
                last_accessed_at=now,
                tech_stack=tech_stack or [],
                engagement_id=engagement_id or "",
            )
        return session_id

    def _touch(self, session: AgentSession) -> None:
        """Update the last_accessed_at timestamp on a session."""
        session.last_accessed_at = int(time.time())

    def _evict_expired(self) -> None:
        """Remove sessions that have exceeded the TTL.

        Uses last_accessed_at to determine expiry — actively-used sessions
        are never evicted mid-scan. Falls back to created_at if
        last_accessed_at is 0 (legacy sessions from prior runs).
        """
        now = time.time()
        if now - self._last_eviction < 300:  # only evict every 5 mins
            return
        self._last_eviction = now
        with self._lock:
            expired = [
                sid
                for sid, s in self._sessions.items()
                if (
                    s.last_accessed_at > 0
                    and now - s.last_accessed_at > self._eviction_ttl
                )
                or (
                    s.last_accessed_at == 0
                    and now - s.created_at > self._eviction_ttl
                )
            ]
            for sid in expired:
                del self._sessions[sid]

    def _start_eviction_loop(self) -> None:
        """Start the background eviction thread (singleton via class-level guard)."""
        if AgentSessionStore._eviction_thread_started:
            return
        AgentSessionStore._eviction_thread_started = True

        def _loop():
            while True:
                time.sleep(300)
                self._evict_expired()

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def get(self, session_id: str) -> AgentSession:
        """Retrieve a copy of a session by ID.

        Returns a deep copy so callers cannot mutate the session's internal
        state (tool_history, findings, observations) outside the store lock.
        Use the dedicated mutation methods (add_execution, add_observation,
        etc.) to modify session state safely.

        Args:
            session_id: The session identifier.

        Returns:
            A copy of the AgentSession.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            if session_id not in self._sessions:
                raise ValueError(f"Session {session_id} not found")
            self._touch(self._sessions[session_id])
            return copy.deepcopy(self._sessions[session_id])

    def _get_and_touch(self, session_id: str) -> AgentSession:
        """Get the live session under lock and update last_accessed_at.

        Internal helper for mutation methods. Returns the live object
        (safe because the caller already holds the lock).
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        self._touch(session)
        return session

    def add_execution(self, session_id: str, execution: ToolExecution) -> None:
        """Record a tool execution in the session history.

        Args:
            session_id: The session identifier.
            execution: The ToolExecution to append.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
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
            session = self._get_and_touch(session_id)
            session.observations.append(observation)

    def set_plan(
        self,
        session_id: str,
        plan: list[str],
        sources: list[str] | None = None,
        argument_map: list[dict] | None = None,
    ) -> None:
        """Set the current hybrid plan for the session and reset step counter.

        Args:
            session_id: The session identifier.
            plan: Ordered list of tool names to execute.
            sources: Per-step provenance parallel to ``plan`` ("llm" or
                "deterministic"). Defaults to deterministic for every step:
                an unlabelled plan must not read as engine-chosen.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            session.current_plan = plan
            session.plan_sources = (
                list(sources) if sources else ["deterministic"] * len(plan)
            )
            session.plan_arguments = (
                [dict(argument_map[i]) if i < len(argument_map) else {} for i in range(len(plan))]
                if argument_map
                else [{} for _ in plan]
            )
            session.plan_step = 0

    def set_plan_provenance(self, session_id: str, source: str) -> None:
        """Record the plan's overall provenance: "llm" or "deterministic".

        Informational: the audit trail labels each step from `plan_sources`.
        This is for logs and callers that need a single-word summary of whether
        the engine contributed to the plan at all.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            session.plan_source = source

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
            session = self._get_and_touch(session_id)
            if session.current_plan is not None and session.plan_step < len(
                session.current_plan
            ):
                tool = session.current_plan[session.plan_step]
                session.plan_step += 1
                return tool
        return None

    def advance_plan_with_source(self, session_id: str) -> tuple[str, str] | None:
        """Return the next tool and who chose it, or None if the plan is done.

        Prefer this over ``advance_plan`` when the caller must label the step in
        the audit trail: a plan can mix engine choices with deterministic ones,
        and only the step's own source answers "did the engine choose this?".

        Args:
            session_id: The session identifier.

        Returns:
            ``(tool_name, source)``, or None if all steps have been consumed.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            if session.current_plan is not None and session.plan_step < len(
                session.current_plan
            ):
                index = session.plan_step
                tool = session.current_plan[index]
                source = (
                    session.plan_sources[index]
                    if index < len(session.plan_sources)
                    else "deterministic"
                )
                session.plan_step += 1
                return tool, source
        return None

    def advance_plan_entry(self, session_id: str) -> tuple[str, str, dict] | None:
        """Return the next ``(tool, source, arguments)``, or None if complete.

        Stage 5.1 item 2: the arguments chosen with the tool travel with it.
        A plan stored as names only yields an empty argument map, which the
        caller fills with the session target.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            if session.current_plan is not None and session.plan_step < len(
                session.current_plan
            ):
                index = session.plan_step
                tool = session.current_plan[index]
                source = (
                    session.plan_sources[index]
                    if index < len(session.plan_sources)
                    else "deterministic"
                )
                arguments = (
                    dict(session.plan_arguments[index])
                    if index < len(session.plan_arguments)
                    else {}
                )
                session.plan_step += 1
                return tool, source, arguments
        return None

    def record_action_signature(self, session_id: str, tool: str, signature: str) -> None:
        """Remember an issued action's signature and count the tool's runs."""
        with self._lock:
            session = self._get_and_touch(session_id)
            session.action_signatures[signature] = tool
            session.action_counts[tool] = session.action_counts.get(tool, 0) + 1

    def action_signatures(self, session_id: str) -> dict[str, str]:
        with self._lock:
            session = self._get_and_touch(session_id)
            return dict(session.action_signatures)

    def action_counts(self, session_id: str) -> dict[str, int]:
        with self._lock:
            session = self._get_and_touch(session_id)
            return dict(session.action_counts)

    def record_executed_tool(self, session_id: str, tool: str) -> None:
        with self._lock:
            session = self._get_and_touch(session_id)
            if tool and tool not in session.executed_tools:
                session.executed_tools.append(tool)

    def session_ids_for_engagement(self, engagement_id: str) -> list[str]:
        """Return session ids belonging to an engagement, for budget status."""
        if not engagement_id:
            return []
        with self._lock:
            return [
                session.session_id
                for session in self._sessions.values()
                if getattr(session, "engagement_id", "") == engagement_id
            ]

    def executions_for_engagement(self, engagement_id: str) -> list[ToolExecution]:
        """Return copies of tool executions for every session of an engagement.

        The worker's session ledger is the authoritative record of what hybrid
        actions actually ran; TypeScript checkpoints reconcile against this
        instead of assuming their dispatched count survived intact.
        """
        if not engagement_id:
            return []
        with self._lock:
            executions: list[ToolExecution] = []
            for session in self._sessions.values():
                if getattr(session, "engagement_id", "") == engagement_id:
                    executions.extend(copy.deepcopy(session.tool_history))
            return executions

    def set_required_coverage(self, session_id: str, required: list[str]) -> None:
        with self._lock:
            session = self._get_and_touch(session_id)
            session.required_coverage = [str(item) for item in (required or []) if str(item)]

    def set_stop_requested(self, session_id: str, requested: bool = True) -> None:
        with self._lock:
            session = self._get_and_touch(session_id)
            session.stop_requested = bool(requested)

    def add_structured_observations(self, session_id: str, observations: list[dict]) -> int:
        """Append structured observations to the session, deduplicated by value."""
        added = 0
        with self._lock:
            session = self._get_and_touch(session_id)
            existing = {
                (record.get("kind"), record.get("value"))
                for record in session.structured_observations
            }
            for record in observations or []:
                key = (record.get("kind"), record.get("value"))
                if key in existing:
                    continue
                session.structured_observations.append(dict(record))
                existing.add(key)
                added += 1
        return added

    def record_issued_action(self, session_id: str, tool: str) -> str:
        """Remember the action just issued by `agent_next` and return its id.

        The id is stable for the observation that follows: exactly one
        outstanding action exists per session, so a second `agent_next`
        without an intervening `agent_observe` replaces it and the older
        id becomes unknown.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            session.action_counter += 1
            action_id = f"{session_id[:8]}-{session.action_counter:04d}"
            session.last_action_id = action_id
            session.last_action_tool = tool
            return action_id

    def validate_observed_action(
        self, session_id: str, action_id: str | None, tool: str | None
    ) -> str | None:
        """Return an error message when the observed action is unknown.

        `None` means the observation may be recorded. Callers without an
        `action_id` (pre-protocol drivers) are still accepted so the
        acknowledgement path stays backward compatible; once an id is
        issued, an explicit but mismatched id is rejected.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            if not action_id:
                return None
            if not session.last_action_id:
                return f"Unknown action '{action_id}': no action was issued for this session"
            if action_id != session.last_action_id:
                return (
                    f"Unknown action '{action_id}': expected outstanding "
                    f"action '{session.last_action_id}' (tool '{session.last_action_tool}')"
                )
            if tool and tool != session.last_action_tool:
                return (
                    f"Tool mismatch for action '{action_id}': observed '{tool}' "
                    f"but issued '{session.last_action_tool}'"
                )
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
            session = self._get_and_touch(session_id)
            session.findings.append(finding)

    def increment_iteration(self, session_id: str) -> int:
        """Increment the shared TS/Python iteration counter.

        Returns the new iteration count after incrementing.
        Allows both TS and Python sides to track shared progress
        through the assessment phase (blocker 32).

        Args:
            session_id: The session identifier.

        Returns:
            The new iteration count.

        Raises:
            ValueError: If the session does not exist.
        """
        with self._lock:
            session = self._get_and_touch(session_id)
            session.execution_iteration += 1
            return session.execution_iteration

    def get_iteration(self, session_id: str) -> int:
        """Get the current shared iteration count without modifying it.

        Args:
            session_id: The session identifier.

        Returns:
            The current iteration count, or 0 if session not found.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return 0
        with self._lock:
            self._touch(session)
            return session.execution_iteration

    def cancel(self, session_id: str) -> bool:
        """Signal a session to stop (blocker 38).

        Sets the ``_cancelled`` attribute on the session object so that
        the ReActAgent loop can check it on the next iteration and
        terminate gracefully.

        If the session does not exist, returns False (no-op).

        Args:
            session_id: The session to cancel.

        Returns:
            True if the session was found and cancelled, False otherwise.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            object.__setattr__(session, '_cancelled', True)
            return True

    def set_ts_max_iterations(self, session_id: str, max_iterations: int) -> bool:
        """Set the TS-side max iterations limit on a session (blocker 32).

        The TypeScript executor communicates its ARGUS_HYBRID_MAX_ITERATIONS
        so the Python side can cap the iteration limit with min(). This is
        stored as ``ts_max_iterations`` on the session object.

        If the session does not exist, returns False (no-op).

        Args:
            session_id: The session to configure.
            max_iterations: The max iterations from the TS executor.

        Returns:
            True if the session was found and updated, False otherwise.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            object.__setattr__(session, 'ts_max_iterations', max_iterations)
            return True
