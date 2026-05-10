"""
Multi-Agent Swarm — parallel specialist agents with merging coordinator.

Each agent receives a DEEP COPY of ReconContext (no shared mutable state).
SwarmOrchestrator evaluates activation, runs in parallel, deduplicates.

Specialist agents:
  - IDORAgent: Finds Insecure Direct Object References
  - AuthAgent: Tests authentication and authorization
  - APIAgent: Deep API security testing
"""

import copy
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from streaming import emit_swarm_agent_started, emit_swarm_agent_action, emit_swarm_agent_complete, emit_swarm_merge_complete

logger = logging.getLogger(__name__)


class SpecialistAgent(ABC):
    """Base class for domain-specialist agents. Each gets isolated state.

    Subclasses implement should_activate() and run().
    State isolation via copy.deepcopy() in __init__.
    """

    DOMAIN: str = ""
    PRIORITY_TOOLS: list[str] = []

    def __init__(
        self,
        llm_service: Any,
        tool_runner: Any,
        recon_context: Any,
        engagement_id: str,
        decision_repo: Any = None,
    ):
        # IMPORTANT: deep copy — never share mutable state across agents
        self.recon_context = (
            copy.deepcopy(recon_context) if recon_context else None
        )
        self.llm_service = llm_service
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.decision_repo = decision_repo
        self.findings: list[dict] = []

    @abstractmethod
    def should_activate(self) -> bool:
        """Return True if recon signals suggest this domain is relevant."""

    @abstractmethod
    def run(self) -> list[dict]:
        """Run this specialist's tool suite. Returns raw finding dicts."""

    def _tag_findings(self, findings: list[dict]) -> list[dict]:
        """Tag all findings with this agent's domain for traceability."""
        for f in findings:
            f["source_agent"] = self.DOMAIN
        return findings


class IDORAgent(SpecialistAgent):
    """Finds Insecure Direct Object References in API endpoints."""

    DOMAIN = "idor"
    PRIORITY_TOOLS = ["arjun", "jwt_tool", "web_scanner"]

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        return (
            (hasattr(rc, "parameter_bearing_urls")
             and len(rc.parameter_bearing_urls) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
            or (hasattr(rc, "api_endpoints")
                and len(rc.api_endpoints) > 0)
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        # TODO: Implement IDOR-specific tool execution
        # 1. Arjun parameter discovery on API endpoints
        # 2. jwt_tool for token manipulation
        # 3. web_scanner IDOR-focused checks
        return self._tag_findings([])


class AuthAgent(SpecialistAgent):
    """Tests authentication and authorization mechanisms."""

    DOMAIN = "auth"
    PRIORITY_TOOLS = ["jwt_tool", "web_scanner", "nuclei"]

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        return (
            (hasattr(rc, "has_login_page") and rc.has_login_page)
            or (hasattr(rc, "auth_endpoints")
                and len(rc.auth_endpoints) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        # TODO: Implement auth-specific tool execution
        # 1. jwt_tool checks on auth endpoints
        # 2. nuclei auth-related templates
        # 3. Password reset flow testing
        return self._tag_findings([])


class APIAgent(SpecialistAgent):
    """Deep API security testing for REST and GraphQL endpoints."""

    DOMAIN = "api"
    PRIORITY_TOOLS = ["arjun", "nuclei", "dalfox", "sqlmap"]

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        return (
            (hasattr(rc, "has_api") and rc.has_api)
            or (hasattr(rc, "api_endpoints")
                and len(rc.api_endpoints) > 5)
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        # TODO: Implement API-specific tool execution
        # 1. arjun parameter discovery on API paths
        # 2. nuclei api-* tagged templates
        # 3. dalfox + sqlmap on discovered API params
        return self._tag_findings([])


class SwarmOrchestrator:
    """Runs specialist agents in parallel and merges findings.

    Activation is based on ReconContext signals. Each agent gets a deep
    copy of the context. Merging uses evidence-weighted dedup from
    ScanDiffEngine._fingerprint() for consistent cross-scan matching.
    """

    SPECIALIST_CLASSES = [IDORAgent, AuthAgent, APIAgent]

    def __init__(
        self,
        llm_service: Any,
        tool_runner: Any,
        recon_context: Any,
        engagement_id: str,
        decision_repo: Any = None,
    ):
        # Deep copy happens inside each agent's __init__
        self.agents = [
            cls(
                llm_service=llm_service,
                tool_runner=tool_runner,
                recon_context=recon_context,
                engagement_id=engagement_id,
                decision_repo=decision_repo,
            )
            for cls in self.SPECIALIST_CLASSES
        ]

    def run(self, timeout: int = 1800) -> list[dict]:
        """Run all active specialists in parallel and merge findings.

        Args:
            timeout: Maximum wall-clock time in seconds (default 30 min)

        Returns:
            Deduplicated list of finding dicts
        """
        active = [a for a in self.agents if a.should_activate()]

        if not active:
            logger.info("Swarm: no specialists activated")
            return []

        logger.info(
            "Swarm: activating %d specialist(s): %s",
            len(active),
            [a.DOMAIN for a in active],
        )

        emit_swarm_agent_started(active[0].engagement_id, "swarm_orchestrator")

        all_findings: list[dict] = []

        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            futures = {
                pool.submit(agent.run): agent.DOMAIN
                for agent in active
            }

            for future in as_completed(futures, timeout=timeout):
                domain = futures[future]
                try:
                    findings = future.result()
                    logger.info(
                        "Specialist %s returned %d findings",
                        domain,
                        len(findings),
                    )
                    emit_swarm_agent_complete(
                        active[0].engagement_id,
                        domain,
                        findings_count=len(findings),
                    )
                    all_findings.extend(findings)
                except Exception as e:
                    logger.error(
                        "Specialist %s failed: %s", domain, e
                    )
                    emit_swarm_agent_complete(
                        active[0].engagement_id,
                        domain,
                        findings_count=0,
                    )

        deduped = self._deduplicate(all_findings)
        dedup_removed = len(all_findings) - len(deduped)
        logger.info(
            "Swarm: %d raw findings → %d after dedup",
            len(all_findings),
            len(deduped),
        )
        emit_swarm_merge_complete(
            active[0].engagement_id,
            total_findings=len(deduped),
            dedup_removed=dedup_removed,
        )

        return deduped

    @staticmethod
    def _deduplicate(findings: list[dict]) -> list[dict]:
        """Deduplicate using evidence-weighted merge.

        For findings with same type+endpoint+payload fingerprint,
        the finding with higher confidence (or richer evidence) survives.

        Args:
            findings: List of finding dicts from all agents

        Returns:
            Deduplicated list
        """
        from scan_diff_engine import ScanDiffEngine

        seen: dict[str, dict] = {}
        for f in findings:
            fp = ScanDiffEngine._fingerprint(f)
            if fp not in seen:
                seen[fp] = f
                continue

            existing = seen[fp]
            existing_conf = float(existing.get("confidence", 0))
            new_conf = float(f.get("confidence", 0))

            if new_conf > existing_conf:
                seen[fp] = f
            elif new_conf == existing_conf:
                # Same confidence: prefer richer evidence
                existing_evidence = len(
                    str(existing.get("evidence", {}))
                )
                new_evidence = len(str(f.get("evidence", {})))
                if new_evidence > existing_evidence:
                    seen[fp] = f

        return list(seen.values())
