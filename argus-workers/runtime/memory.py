"""
MemoryRetriever — 3-tier memory retrieval for agent prompts.

Architecture:
- Short-term: EngagementState.observations (replaces ReActAgent.history)
- Medium-term: agent_decision_log table (compressed reasoning summaries)
- Long-term: target_profiles table (historical findings and patterns)

The retriever is called by the agent loop before prompt building to inject
relevant context from all three tiers.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemoryRetriever:
    """
    Retrieves relevant context from all three memory tiers.

    Usage:
        retriever = MemoryRetriever(connection_string)
        context = retriever.get_relevant_context(engagement_state)
    """

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string

    def get_relevant_context(self, state: Any) -> dict:
        """
        Retrieve context from all three memory tiers.

        Args:
            state: EngagementState instance

        Returns:
            Dict with short_term, medium_term, long_term sections
        """
        return {
            "short_term": self._get_short_term(state),
            "medium_term": self._get_medium_term(state),
            "long_term": self._get_long_term(state),
        }

    def get_observation_summary(self, state: Any, max_tokens: int = 1500) -> str:
        """
        Build a condensed memory summary for agent prompt injection.
        Latency budget: <50ms per call.

        Works with both EngagementState (state.observations) and
        ReActAgent (state.history) for backward compatibility during migration.
        """
        parts = []

        # Short-term: recent observations (supports EngagementState, ReActAgent,
        # and ReActAgent with engagement_state attribute)
        observations = getattr(state, "observations", None)
        if observations is None or callable(observations):
            # Check if state has an engagement_state attribute
            engagement_state = getattr(state, "engagement_state", None)
            if engagement_state is not None and not callable(engagement_state):
                observations = getattr(engagement_state, "observations", None)
        if observations is None or callable(observations):
            observations = getattr(state, "history", [])
        if callable(observations):
            observations = []
        observations = observations[-6:]
        if observations:
            recent = []
            for obs in observations:
                role = obs.get("role", "?")
                content = obs.get("content", "")[:200]
                recent.append(f"[{role}]: {content}")
            parts.append("=== RECENT OBSERVATIONS ===\n" + "\n".join(recent[-4:]))

        # Medium-term: compressed from decision_snapshots
        medium = self._get_medium_term(state)
        if medium:
            snapshot_summaries = []
            for s in medium[:3]:
                tool = s.get("selected_tool", "?")
                reasoning = s.get("reasoning_hash", "")[:80]
                snapshot_summaries.append(f"  - {tool}: {reasoning}")
            if snapshot_summaries:
                parts.append(
                    "=== PRIOR DECISIONS ===\n" + "\n".join(snapshot_summaries)
                )

        # Long-term: target profile highlights
        long_term = self._get_long_term(state)
        if long_term and long_term.get("total_scans", 0) > 0:
            summary_parts = []
            scans = long_term.get("total_scans", 0)
            summary_parts.append(f"Scanned before: {scans} time(s)")
            confirmed = long_term.get("confirmed_finding_types", [])[:3]
            if confirmed:
                summary_parts.append(f"Past confirmed: {', '.join(confirmed)}")
            hot = long_term.get("high_value_endpoints", [])[:3]
            if hot:
                summary_parts.append(f"Hot endpoints: {', '.join(hot)}")
            if summary_parts:
                parts.append("=== TARGET HISTORY ===\n" + " | ".join(summary_parts))

        combined = "\n\n".join(parts)

        # Token budget enforcement (~4 chars per token)
        max_chars = max_tokens * 4
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n[truncated]"

        return combined

    def _get_short_term(self, state: Any) -> list[dict]:
        """Short-term: recent observations from EngagementState or ReActAgent.

        Resolution order:
        1. state.observations (direct EngagementState instance)
        2. state.engagement_state.observations (when agent holds EngagementState)
        3. state.history (ReActAgent fallback)
        """
        # Direct observations attribute (EngagementState or similar)
        observations = getattr(state, "observations", None)
        if observations is not None and not callable(observations):
            return observations[-10:]

        # Check if state has an engagement_state attribute (e.g. ReActAgent
        # wired with EngagementState). Guard against mock objects by checking
        # that it has actual observations content.
        engagement_state = getattr(state, "engagement_state", None)
        if engagement_state is not None and not callable(engagement_state):
            obs = getattr(engagement_state, "observations", None)
            if obs is not None and not callable(obs):
                return obs[-10:]

        # Fallback to history list
        observations = getattr(state, "history", [])
        if callable(observations):
            observations = []
        return observations[-10:]

    def _get_medium_term(self, state: Any) -> list[dict]:
        """Medium-term: compressed reasoning from decision_snapshots."""
        # Support both EngagementState and bare objects
        engagement_id = getattr(state, "engagement_id", None) or getattr(
            state, "_engagement_id", ""
        )
        if not engagement_id or not self.connection_string:
            return []
        try:
            from database.connection import db_cursor

            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT selected_tool, arguments, reasoning_hash, state_version, created_at
                    FROM agent_decision_log
                    WHERE engagement_id = %s
                    ORDER BY created_at DESC
                    LIMIT 5
                    """,
                    (engagement_id,),
                )
                rows = cursor.fetchall()
                return [
                    {
                        "selected_tool": row[0],
                        "arguments": row[1],
                        "reasoning_hash": row[2][:16] if row[2] else "",
                        "state_version": row[3],
                        "timestamp": str(row[4]) if row[4] else "",
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.debug("Medium-term memory retrieval failed: %s", e)
            return []

    def _get_long_term(self, state: Any) -> dict:
        """Long-term: target profile from target_profiles table.

        Cross-engagement learning: queries by target domain/hostname
        across ALL engagements, not just the current engagement_id.
        This allows the agent to learn from previous scans of the
        same target even when they have different engagement IDs.
        """
        engagement_id = getattr(state, "engagement_id", "")
        if not engagement_id or not self.connection_string:
            return {}
        try:
            from database.repositories.target_profile_repository import (
                TargetProfileRepository,
            )

            repo = TargetProfileRepository()

            # Phase 1: Try strict engagement_id match (fast path)
            profile = repo.get_by_engagement_id(engagement_id)
            if profile and hasattr(profile, "to_dict"):
                profile_dict = profile.to_dict()
                if profile_dict.get("total_scans", 0) > 0:
                    return profile_dict

            # Phase 2: Cross-engagement lookup by target domain/hostname
            # Extract target domain from the engagement state and query
            # across all org engagements for this target.
            org_id = getattr(state, "org_id", None) or getattr(
                getattr(state, "engagement_state", None), "org_id", None
            )
            target_domain = self._extract_target_domain(state, engagement_id)
            if target_domain and org_id:
                cross_profile = repo.get_profile(org_id, target_domain)
                if cross_profile and cross_profile.get("total_scans", 0) > 0:
                    cross_profile["_cross_engagement"] = True
                    cross_profile["_source_engagement"] = engagement_id
                    return cross_profile

            # Phase 3: Fallback to engagement-specific profile
            if isinstance(profile, dict):
                return profile
        except Exception as e:
            logger.debug("Long-term memory retrieval failed: %s", e)
        return {}

    @staticmethod
    def _extract_target_domain(state: Any, engagement_id: str) -> str | None:
        """Extract the target domain from engagement context.

        Resolution order:
        1. recon_context.target_host or target_url (from EngagementState)
        2. engagements table target_url field
        3. Any target_* attribute on state

        Returns:
            Domain string (e.g. "example.com") or None.
        """
        import re
        from urllib.parse import urlparse

        def _parse_domain(url_or_host: str) -> str | None:
            """Extract a clean domain from a URL or hostname."""
            url_or_host = url_or_host.strip().lower()
            # Strip protocol if present
            if "://" in url_or_host:
                parsed = urlparse(url_or_host)
                hostname = parsed.hostname
            else:
                hostname = url_or_host.split("/")[0].split(":")[0]
            if hostname and re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$", hostname):
                return hostname
            return None

        # Check recon_context on state
        recon_ctx = getattr(state, "recon_context", None) or getattr(state, "_recon_context", None)
        if recon_ctx:
            for attr in ("target_host", "target_url", "host", "domain"):
                val = getattr(recon_ctx, attr, None)
                if val:
                    domain = _parse_domain(str(val))
                    if domain:
                        return domain

        # Query engagements table
        if engagement_id:
            try:
                from database.connection import db_cursor
                with db_cursor() as cursor:
                    cursor.execute(
                        "SELECT target_url FROM engagements WHERE id = %s",
                        (engagement_id,),
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        domain = _parse_domain(str(row[0]))
                        if domain:
                            return domain
            except Exception:
                pass

        return None
