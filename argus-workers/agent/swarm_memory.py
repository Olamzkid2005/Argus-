"""
SwarmMemory — thread-safe in-flight signal sharing for parallel specialist agents.

Each SwarmOrchestrator creates one SwarmMemory instance and passes it to all
SpecialistAgent instances. Agents can publish lightweight signals (discovered
endpoints, tech stack hints, auth context) and consume signals discovered by
peer agents — all without shared mutable state violations.

Design:
- Thread-safe: all public methods use threading.Lock()
- Non-blocking: publishes are fire-and-forget, reads return empty defaults
- Minimal: only high-value signals that change agent behaviour
- Idempotent: repeated publishes of the same signal are deduplicated
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class SwarmMemory:
    """Thread-safe in-flight memory for cross-agent signal sharing.

    Usage:
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "/api/v2/users/123")
        memory.publish_tech_signal("api", "framework", "Express")
        endpoints = memory.get_new_endpoints("idor")
    """

    def __init__(self):
        self._lock = threading.Lock()
        # agent_domain -> set of endpoint strings
        self._discovered_endpoints: dict[str, set[str]] = {}
        # agent_domain -> list of tech signals
        self._tech_signals: dict[str, list[dict]] = {}
        # agent_domain -> auth context dict
        self._auth_context: dict[str, dict] = {}
        # agent_domain -> set of discovered parameter names
        self._discovered_parameters: dict[str, set[str]] = {}
        # agent_domain -> summary string from completed agents
        self._agent_summaries: dict[str, str] = {}
        # Set of all known endpoints (across all agents) for dedup
        self._all_endpoints: set[str] = set()
        # Set of all known tech signals (canonical form) for dedup
        self._all_tech_fingerprints: set[str] = set()

    # ── Endpoint discovery ──────────────────────────────────────────

    def publish_endpoint(self, source_agent: str, endpoint: str) -> None:
        """Publish a newly discovered endpoint from a specialist agent.

        Thread-safe. Deduplicated by endpoint string across all agents.
        """
        if not endpoint or not isinstance(endpoint, str):
            return
        endpoint = endpoint.rstrip("/")
        with self._lock:
            if endpoint in self._all_endpoints:
                return
            self._all_endpoints.add(endpoint)
            if source_agent not in self._discovered_endpoints:
                self._discovered_endpoints[source_agent] = set()
            self._discovered_endpoints[source_agent].add(endpoint)

    def publish_endpoints(self, source_agent: str, endpoints: list[str]) -> None:
        """Publish multiple newly discovered endpoints."""
        for ep in endpoints:
            self.publish_endpoint(source_agent, ep)

    def get_new_endpoints(self, consuming_agent: str) -> list[str]:
        """Get all endpoints discovered by agents OTHER than the consumer.

        Returns:
            List of endpoint strings (newest first by insertion order).
        """
        with self._lock:
            others = {
                ep
                for agent, eps in self._discovered_endpoints.items()
                if agent != consuming_agent
                for ep in eps
            }
            return sorted(others)

    def get_all_endpoints(self) -> list[str]:
        """Get all discovered endpoints across all agents."""
        with self._lock:
            return sorted(self._all_endpoints)

    def get_endpoint_count(self) -> int:
        """Total unique endpoints discovered across all agents."""
        with self._lock:
            return len(self._all_endpoints)

    # ── Tech signals ────────────────────────────────────────────────

    def publish_tech_signal(
        self, source_agent: str, category: str, value: str
    ) -> None:
        """Publish a technology discovery (framework, library, version, etc.).

        Args:
            source_agent: Domain of the discovering agent (e.g. "api").
            category: Signal category (e.g. "framework", "library", "server").
            value: The discovered value (e.g. "Express", "React 18").
        """
        if not category or not value:
            return
        fingerprint = f"{category}::{value.lower().strip()}"
        with self._lock:
            if fingerprint in self._all_tech_fingerprints:
                return
            self._all_tech_fingerprints.add(fingerprint)
            signal = {"category": category, "value": value, "source": source_agent}
            if source_agent not in self._tech_signals:
                self._tech_signals[source_agent] = []
            self._tech_signals[source_agent].append(signal)

    def get_tech_signals(self, consuming_agent: str) -> list[dict]:
        """Get tech signals from agents OTHER than the consumer.

        Returns:
            List of signal dicts with category, value, source.
        """
        with self._lock:
            return [
                signal
                for agent, signals in self._tech_signals.items()
                if agent != consuming_agent
                for signal in signals
            ]

    def get_tech_summary(self) -> str:
        """Build a compact tech stack summary from all signals.

        Returns:
            String like "Express | React 18 | PostgreSQL" or empty string.
        """
        with self._lock:
            if not self._all_tech_fingerprints:
                return ""
            categories: dict[str, list[str]] = {}
            for agent, signals in self._tech_signals.items():
                for s in signals:
                    cat = s["category"]
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(s["value"])
            parts = []
            for cat in sorted(categories.keys()):
                values = categories[cat]
                if len(values) == 1:
                    parts.append(f"{cat}={values[0]}")
                else:
                    parts.append(f"{cat}=[{', '.join(values)}]")
            return " | ".join(parts)

    # ── Auth context ────────────────────────────────────────────────

    def publish_auth_context(self, source_agent: str, context: dict) -> None:
        """Publish authentication context discovered by an agent.

        Context keys (all optional):
            auth_type: str — "jwt", "oauth", "session", "basic", "none"
            token_location: str — "header", "cookie", "body"
            jwt_algorithm: str — "HS256", "RS256", "none" (if JWT)
            has_login_page: bool
            has_mfa: bool
            session_in_cookie: bool
        """
        if not context:
            return
        with self._lock:
            # Merge: newer agent's context fills gaps without overwriting
            existing = self._auth_context.get(source_agent, {})
            merged = {**existing, **context}
            self._auth_context[source_agent] = merged

    def get_auth_context(self) -> dict:
        """Get aggregated auth context from all agents."""
        with self._lock:
            merged: dict = {}
            for ctx in self._auth_context.values():
                merged.update(ctx)
            return merged

    # ── Parameter discovery ─────────────────────────────────────────

    def publish_parameter(self, source_agent: str, param: str) -> None:
        """Publish a newly discovered parameter name."""
        if not param or not isinstance(param, str):
            return
        with self._lock:
            if source_agent not in self._discovered_parameters:
                self._discovered_parameters[source_agent] = set()
            self._discovered_parameters[source_agent].add(param)

    def publish_parameters(self, source_agent: str, params: list[str]) -> None:
        """Publish multiple newly discovered parameter names."""
        for p in params:
            self.publish_parameter(source_agent, p)

    def get_new_parameters(self, consuming_agent: str) -> list[str]:
        """Get parameters discovered by agents OTHER than the consumer."""
        with self._lock:
            others: set[str] = set()
            for agent, params in self._discovered_parameters.items():
                if agent != consuming_agent:
                    others.update(params)
            return sorted(others)

    # ── Agent summaries ─────────────────────────────────────────────

    def publish_summary(self, agent_domain: str, summary: str) -> None:
        """Publish a completion summary from a finished agent.

        Other agents can check this to know what peers have already
        covered and avoid redundant work.
        """
        if not agent_domain or not summary:
            return
        with self._lock:
            self._agent_summaries[agent_domain] = summary
            logger.debug(
                "SwarmMemory: agent %s published summary (%d chars)",
                agent_domain,
                len(summary),
            )

    def get_peer_summaries(self, consuming_agent: str) -> dict[str, str]:
        """Get summaries from all agents EXCEPT the consumer."""
        with self._lock:
            return {
                agent: summary
                for agent, summary in self._agent_summaries.items()
                if agent != consuming_agent
            }

    def get_completed_agents(self) -> list[str]:
        """Get list of agent domains that have published summaries."""
        with self._lock:
            return list(self._agent_summaries.keys())

    # ── Snapshot (for orchestrator) ─────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot of all shared state.

        Used by SwarmOrchestrator for logging/metrics after swarm completes.
        """
        with self._lock:
            return {
                "endpoint_count": len(self._all_endpoints),
                "tech_fingerprints": len(self._all_tech_fingerprints),
                "agents_with_signals": list(
                    set(
                        list(self._discovered_endpoints.keys())
                        + list(self._tech_signals.keys())
                        + list(self._auth_context.keys())
                    )
                ),
                "completed_agents": list(self._agent_summaries.keys()),
            }
