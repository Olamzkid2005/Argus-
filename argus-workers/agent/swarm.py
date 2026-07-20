"""
Multi-Agent Swarm — parallel specialist agents with merging coordinator.

Each agent receives a DEEP COPY of ReconContext (no shared mutable state).
SwarmOrchestrator evaluates activation, runs in parallel, deduplicates.

Specialist agents:
  - IDORAgent: Finds Insecure Direct Object References
  - AuthAgent: Tests authentication and authorization
  - APIAgent: Deep API security testing
"""

import concurrent.futures
import copy
import logging
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

# In-flight cross-agent learning: thread-safe shared memory for signal exchange
from agent.swarm_memory import SwarmMemory
from scan_diff_engine import ScanDiffEngine
from streaming import (
    emit_swarm_agent_action,
    emit_swarm_agent_complete,
    emit_swarm_agent_started,
    emit_swarm_merge_complete,
    emit_swarm_metrics,
)
from tools.scope_validator import ScopeValidator, validate_target_scope
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_DEFAULT = 180
TOOL_TIMEOUT_LONG = 600

# ── Structured Swarm Metrics ──────────────────────────────────────────────


@dataclass
class SwarmMetrics:
    """Structured metrics collected during a single SwarmOrchestrator.run().

    Automatically emitted as a structured INFO log line + SSE event
    at the end of every swarm run for live-fire observability.
    """

    # Agent activation
    total_agents: int = 0
    activated_agents: list[str] = field(default_factory=list)
    inactive_agents: list[dict] = field(default_factory=list)
    # Inactive agents stored as [{"domain": str, "reason": str}, ...]

    # Per-agent results
    per_agent_findings: dict[str, int] = field(default_factory=dict)
    per_agent_tools: dict[str, list[str]] = field(default_factory=dict)
    per_agent_errors: dict[str, int] = field(default_factory=dict)
    per_agent_timeouts: dict[str, int] = field(default_factory=dict)

    # Dedup
    raw_findings_total: int = 0
    deduped_findings_total: int = 0
    dedup_removed: int = 0
    dedup_ratio: float = 0.0

    # Peer intel
    peer_intel_exchanges: int = 0

    # Orphan cleanup
    orphan_cleanup_ran: bool = False
    orphans_killed: int = 0

    def to_dict(self) -> dict:
        return {
            "total_agents": self.total_agents,
            "activated_agents": self.activated_agents,
            "inactive_agents": self.inactive_agents,
            "per_agent_findings": self.per_agent_findings,
            "per_agent_tools": self.per_agent_tools,
            "per_agent_errors": self.per_agent_errors,
            "per_agent_timeouts": self.per_agent_timeouts,
            "raw_findings_total": self.raw_findings_total,
            "deduped_findings_total": self.deduped_findings_total,
            "dedup_removed": self.dedup_removed,
            "dedup_ratio": round(self.dedup_ratio, 3),
            "peer_intel_exchanges": self.peer_intel_exchanges,
            "orphan_cleanup_ran": self.orphan_cleanup_ran,
            "orphans_killed": self.orphans_killed,
        }


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
        auth_config: dict | None = None,
        bug_bounty_mode: bool = False,
        swarm_memory: SwarmMemory | None = None,
    ):
        # IMPORTANT: deep copy — never share mutable state across agents
        self.recon_context = copy.deepcopy(recon_context) if recon_context else None
        self.llm_service = llm_service
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.decision_repo = decision_repo
        self.auth_config = auth_config or {}
        self.bug_bounty_mode = bug_bounty_mode
        self.findings: list[dict] = []
        self._parser = None
        self.tools_attempted: set[str] = set()
        # In-flight cross-agent learning: shared signal store
        self.swarm_memory = swarm_memory

    @abstractmethod
    def should_activate(self) -> bool:
        """Return True if recon signals suggest this domain is relevant."""
        ...

    @abstractmethod
    def run(self) -> list[dict]:
        """Run this specialist's tool suite. Returns raw finding dicts."""
        ...

    @property
    def parser(self):
        """Lazy-init parser for tool output parsing."""
        if self._parser is None:
            from parsers.parser import Parser

            self._parser = Parser()
        return self._parser

    def _log_decision(
        self, tool_name: str, args: list, findings_count: int, success: bool
    ):
        """Log a tool execution decision to the decision repository."""
        if not self.decision_repo:
            return
        try:
            self.decision_repo.log_decision(
                engagement_id=self.engagement_id,
                phase=f"swarm_{self.DOMAIN}",
                iteration=0,
                tool_selected=tool_name,
                arguments={"args": args},
                reasoning=f"Swarm {self.DOMAIN} running {tool_name} ({'success' if success else 'failed'}, {findings_count} findings)",
                was_fallback=False,
                input_tokens=None,
                output_tokens=None,
            )
        except Exception as e:
            logger.debug("%s/log_decision failed (non-fatal): %s", self.DOMAIN, e)

    def _run_tool(
        self, tool_name: str, args: list, timeout: int = TOOL_TIMEOUT_DEFAULT
    ) -> list[dict]:
        """Run a single tool and return parsed findings."""
        self.tools_attempted.add(tool_name)
        findings = []
        success = False
        try:
            emit_swarm_agent_action(
                self.engagement_id,
                self.DOMAIN,
                tool_name,
                reasoning=f"Running {tool_name} with args: {' '.join(args[:4])}...",
            )
            result = self.tool_runner.run(tool_name, args, timeout=timeout)
            success = result.success
            if result.success and result.stdout:
                parsed = self.parser.parse(tool_name, result.stdout)
                for p in parsed:
                    findings.append(p)
            elif result.stderr:
                logger.debug(
                    "%s/%s stderr: %s", self.DOMAIN, tool_name, result.stderr[:200]
                )
        except ImportError as e:
            logger.error("%s/%s missing dependency: %s", self.DOMAIN, tool_name, e)
        except Exception as e:
            logger.warning("%s/%s failed: %s", self.DOMAIN, tool_name, e)
        finally:
            self._log_decision(tool_name, args, len(findings), success)
        return findings

    def _get_targets(self) -> list[str]:
        """Extract target URLs from recon context, filtered to authorized scope."""
        if not self.recon_context:
            return []
        rc = self.recon_context
        targets = []
        if hasattr(rc, "live_endpoints") and rc.live_endpoints:
            targets.extend(rc.live_endpoints)
        if hasattr(rc, "api_endpoints") and rc.api_endpoints:
            targets.extend(rc.api_endpoints)
        if not targets and hasattr(rc, "crawled_paths") and rc.crawled_paths:
            # Build full URLs from crawled paths
            base = (
                rc.target_url.rstrip("/")
                if hasattr(rc, "target_url") and rc.target_url
                else ""
            )
            for path in rc.crawled_paths[:20]:
                if path.startswith("http"):
                    targets.append(path)
                elif base:
                    targets.append(
                        f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
                    )
        if not targets and hasattr(rc, "target_url") and rc.target_url:
            targets = [rc.target_url]
        # Filter to authorized scope + SSRF prevention
        from urllib.parse import urlparse

        from tools.scope_validator import ScopeValidator, validate_target_scope

        def _safe(t: str) -> bool:
            hostname = urlparse(t).hostname or t.split("/")[0].split(":")[0]
            if hostname and ScopeValidator.is_internal_address(hostname):
                return False
            return validate_target_scope(t, self.engagement_id)

        return [t for t in targets if _safe(t)]

    @staticmethod
    def _has_dynamic_surface(rc) -> bool:
        """Check if recon context shows a dynamic webapp with actionable attack surface.

        Returns True when the target has parameter-bearing URLs, auth endpoints,
        or API endpoints — signals that the app processes user input and has
        meaningful attack surface. Raw page count alone is not enough.
        """
        return (
            (
                hasattr(rc, "parameter_bearing_urls")
                and len(rc.parameter_bearing_urls) > 0
            )
            or (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
        )

    # ── In-flight cross-agent learning ──────────────────────────

    def _gather_peer_intel(self) -> dict:
        """Gather signals from peer agents via shared SwarmMemory.

        Returns dict with:
            endpoints: newly discovered endpoints from peers
            parameters: newly discovered parameters from peers
            tech: tech stack signals from peers
            auth: aggregated auth context from peers
        """
        if not self.swarm_memory:
            return {"endpoints": [], "parameters": [], "tech": [], "auth": {}}
        return {
            "endpoints": self.swarm_memory.get_new_endpoints(self.DOMAIN),
            "parameters": self.swarm_memory.get_new_parameters(self.DOMAIN),
            "tech": self.swarm_memory.get_tech_signals(self.DOMAIN),
            "auth": self.swarm_memory.get_auth_context(),
        }

    def _publish_findings_signals(self, findings: list[dict]) -> None:
        """Extract and publish signals from tool findings to peer agents.

        Published signals:
        - New endpoints (from finding endpoint, url, and evidence fields)
        - Tech stack signals (from tech_stack or framework mentions)
        - Auth context (from auth-related findings)
        - Parameters (from parameter-bearing URLs)
        """
        if not self.swarm_memory or not findings:
            return

        from urllib.parse import urlparse

        endpoints: set[str] = set()
        params: set[str] = set()
        tech_signals: list[tuple[str, str]] = []

        def _extract_urls_from_value(val: object) -> list[str]:
            """Recursively extract http(s) URLs from nested dicts, lists, or strings."""
            results: list[str] = []
            if isinstance(val, str):
                if val.startswith("http"):
                    results.append(val.rstrip("/"))
            elif isinstance(val, dict):
                for v in val.values():
                    results.extend(_extract_urls_from_value(v))
            elif isinstance(val, list):
                for item in val:
                    results.extend(_extract_urls_from_value(item))
            return results

        for f in findings:
            # Extract endpoint from finding
            endpoint = f.get("endpoint", "") or f.get("url", "") or ""
            if endpoint and isinstance(endpoint, str):
                endpoint = endpoint.rstrip("/")
                if endpoint.startswith("http"):
                    endpoints.add(endpoint)
                    # Extract parameters from URL
                    parsed = urlparse(endpoint)
                    if parsed.query:
                        for param in parsed.query.split("&"):
                            if "=" in param:
                                params.add(param.split("=")[0])

            # Recursively extract URLs from evidence (handles nested dicts/lists)
            evidence = f.get("evidence", {}) or {}
            for evidence_url in _extract_urls_from_value(evidence):
                endpoints.add(evidence_url)

            # Extract tech signals from finding metadata
            if "framework" in f:
                tech_signals.append(("framework", str(f["framework"])))
            if "tech_stack" in f:
                for tech in (f["tech_stack"] if isinstance(f["tech_stack"], list) else [str(f["tech_stack"])]):
                    if isinstance(tech, str):
                        tech_signals.append(("library", tech))
            finding_type = (f.get("type", "") or "").upper()
            if finding_type in ("JWT", "OAUTH", "SESSION"):
                self.swarm_memory.publish_auth_context(
                    self.DOMAIN,
                    {"auth_type": finding_type.lower()},
                )

            # Extract source_tool tech info
            tool = f.get("source_tool", "") or ""
            if tool in ("nuclei", "wpscan", "testssl", "jwt_tool"):
                tech_signals.append(("tool_used", tool))

        # Batch publish endpoints
        if endpoints:
            self.swarm_memory.publish_endpoints(self.DOMAIN, list(endpoints))
        if params:
            self.swarm_memory.publish_parameters(self.DOMAIN, list(params))
        for category, value in tech_signals:
            self.swarm_memory.publish_tech_signal(self.DOMAIN, category, value)

    def _enrich_targets_with_peer_intel(
        self, targets: list[str]
    ) -> list[str]:
        """Extend the target list with endpoints discovered by peer agents.

        Merges peer-discovered endpoints with the agent's own targets,
        respecting scope validation and SSRF prevention.
        """
        if not self.swarm_memory:
            return targets
        peer_intel = self._gather_peer_intel()
        new_endpoints = peer_intel.get("endpoints", [])
        if not new_endpoints:
            return targets

        # Deduplicate and merge
        from urllib.parse import urlparse

        existing = {t.rstrip("/") for t in targets}
        # Validate scope for peer-discovered endpoints
        safe_new: list[str] = []
        for ep in new_endpoints:
            ep_clean = ep.rstrip("/")
            if ep_clean in existing:
                continue
            hostname = urlparse(ep_clean).hostname
            if hostname and ScopeValidator.is_internal_address(hostname):
                continue
            if validate_target_scope(ep_clean, self.engagement_id):
                safe_new.append(ep_clean)
                existing.add(ep_clean)

        if safe_new:
            logger.info(
                "%s: enriched with %d peer-discovered endpoint(s) from swarm memory",
                self.DOMAIN,
                len(safe_new),
            )
        return targets + safe_new

    def _collect_peer_tech_context(self) -> str:
        """Build a one-line tech summary from peer signals for logging."""
        if not self.swarm_memory:
            return ""
        return self.swarm_memory.get_tech_summary()

    def _get_new_peer_targets(self, processed: set[str]) -> list[str]:
        """Get peer-discovered endpoints that haven't been processed yet.

        Validates scope and filters out internal/SSRF targets.

        Args:
            processed: Set of endpoint strings already processed by this agent.

        Returns:
            List of new, scope-valid endpoint URLs.
        """
        if not self.swarm_memory:
            return []
        from urllib.parse import urlparse

        peer_eps = self.swarm_memory.get_new_endpoints(self.DOMAIN)
        new_targets: list[str] = []
        for ep in peer_eps:
            if ep in processed:
                continue
            hostname = urlparse(ep).hostname
            if hostname and ScopeValidator.is_internal_address(hostname):
                continue
            if validate_target_scope(ep, self.engagement_id):
                new_targets.append(ep)
        return new_targets

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
        specific = (
            (
                hasattr(rc, "parameter_bearing_urls")
                and len(rc.parameter_bearing_urls) > 0
            )
            or (hasattr(rc, "has_api") and rc.has_api)
            or (hasattr(rc, "api_endpoints") and len(rc.api_endpoints) > 0)
        )
        if specific:
            return True
        return bool(
            hasattr(rc, "crawled_paths")
            and len(rc.crawled_paths) >= 25
            and self._has_dynamic_surface(rc)
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []

        # ── Phase 1: Initial targets ──
        targets = self._get_targets()
        targets = self._enrich_targets_with_peer_intel(targets)
        processed_targets: set[str] = set(targets) if targets else set()

        # Log peer intel summary
        tech_ctx = self._collect_peer_tech_context()
        if tech_ctx:
            logger.info("[IDOR] Peer tech context: %s", tech_ctx)

        for target in targets:
            # 1. Arjun parameter discovery on API endpoints
            logger.info("[IDOR] Running arjun on %s", target)
            try:
                sandbox = (
                    self.tool_runner.sandbox_dir
                    if hasattr(self.tool_runner, "sandbox_dir")
                    and self.tool_runner.sandbox_dir
                    else None
                )
                if sandbox:
                    arjun_out = str(
                        sandbox / "tmp" / f"arjun_idor_{self.engagement_id}.json"
                    )
                else:
                    arjun_out = os.path.join(
                        tempfile.gettempdir(), f"arjun_idor_{self.engagement_id}.json"
                    )
                arjun_findings = self._run_tool(
                    "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", "20"],
                    timeout=TOOL_TIMEOUT_DEFAULT,
                )
                all_findings.extend(arjun_findings)
                self._publish_findings_signals(arjun_findings)
                # M-v5-04: Clean up temp file if not using sandbox (sandbox cleaned by atexit)
                if not sandbox:
                    try:
                        if os.path.exists(arjun_out):
                            os.remove(arjun_out)
                    except Exception:
                        logger.debug("Failed to clean up temp file: %s", arjun_out)
            except Exception as e:
                logger.warning("[IDOR] arjun failed for %s: %s", target, e)

            # 2. jwt_tool for token manipulation (IDOR via JWT)
            logger.info("[IDOR] Running jwt_tool on %s", target)
            try:
                jwt_findings = self._run_tool(
                    "jwt_tool",
                    [target, "-C", "-d"],
                    timeout=120,
                )
                all_findings.extend(jwt_findings)
                self._publish_findings_signals(jwt_findings)
            except Exception as e:
                logger.warning("[IDOR] jwt_tool failed for %s: %s", target, e)

        # ── Phase 2: web_scanner on initial targets ──
        if targets:
            self.tools_attempted.add("web_scanner")
            logger.info("[IDOR] Running web_scanner on %d targets", len(targets))
            for target in targets:
                web_findings = self._run_tool(
                    "web_scanner", [target], timeout=TOOL_TIMEOUT_LONG
                )
                all_findings.extend(web_findings)
                self._publish_findings_signals(web_findings)

        # ── Phase 3: Mid-run peer intel — process peer-discovered endpoints ──
        new_peer_targets = self._get_new_peer_targets(processed_targets)
        if new_peer_targets:
            logger.info(
                "[IDOR] Processing %d mid-run peer-discovered endpoint(s)",
                len(new_peer_targets),
            )
            self.tools_attempted.add("web_scanner")
            for target in new_peer_targets:
                processed_targets.add(target)
                web_findings = self._run_tool(
                    "web_scanner", [target], timeout=TOOL_TIMEOUT_LONG
                )
                all_findings.extend(web_findings)
                self._publish_findings_signals(web_findings)

        # Publish completion summary for peer agents
        if self.swarm_memory:
            summary = (
                f"IDOR: {len(all_findings)} findings across {len(processed_targets)} targets"
            )
            self.swarm_memory.publish_summary(self.DOMAIN, summary)

        logger.info("[IDOR] Total findings: %d", len(all_findings))
        return self._tag_findings(all_findings)


class AuthAgent(SpecialistAgent):
    """Tests authentication and authorization mechanisms."""

    DOMAIN = "auth"
    PRIORITY_TOOLS = ["jwt_tool", "nuclei", "web_scanner"]

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        specific = (
            (hasattr(rc, "has_login_page") and rc.has_login_page)
            or (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
        )
        if specific:
            return True
        return bool(
            hasattr(rc, "crawled_paths")
            and len(rc.crawled_paths) >= 25
            and self._has_dynamic_surface(rc)
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []

        # ── Phase 1: Initial targets ──
        targets = self._get_targets()
        targets = self._enrich_targets_with_peer_intel(targets)
        auth_endpoints = (
            self.recon_context.auth_endpoints
            if self.recon_context and hasattr(self.recon_context, "auth_endpoints")
            else []
        )

        scan_targets = list(set(targets + auth_endpoints))
        if (
            not scan_targets
            and self.recon_context
            and hasattr(self.recon_context, "target_url")
        ):
            scan_targets = [self.recon_context.target_url]

        processed_targets: set[str] = set(scan_targets) if scan_targets else set()

        # Log peer tech context
        tech_ctx = self._collect_peer_tech_context()
        if tech_ctx:
            logger.info("[Auth] Peer tech context: %s", tech_ctx)

        for target in scan_targets:
            # 1. jwt_tool checks on auth endpoints
            logger.info("[Auth] Running jwt_tool on %s", target)
            try:
                jwt_findings = self._run_tool(
                    "jwt_tool",
                    [target, "-C", "-d"],
                    timeout=120,
                )
                all_findings.extend(jwt_findings)
                self._publish_findings_signals(jwt_findings)
            except Exception as e:
                logger.warning("[Auth] jwt_tool failed for %s: %s", target, e)

            # 2. nuclei auth-related templates
            logger.info("[Auth] Running nuclei auth templates on %s", target)
            try:
                from orchestrator_pkg.utils import get_nuclei_templates_path

                templates_path = get_nuclei_templates_path()
                nuclei_cmd = [
                    "-u",
                    target,
                    "-jsonl",
                    "-silent",
                    "-severity",
                    "medium,high,critical",
                ]
                if templates_path.exists():
                    nuclei_cmd.extend(["-t", str(templates_path)])
                nuclei_cmd.extend(
                    [
                        "-tags",
                        "auth,login,jwt,oauth,session,default-login,bruteforce",
                    ]
                )
                nuclei_findings = self._run_tool(
                    "nuclei",
                    nuclei_cmd,
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(nuclei_findings)
                self._publish_findings_signals(nuclei_findings)
            except Exception as e:
                logger.warning("[Auth] nuclei failed for %s: %s", target, e)

        # ── Phase 2: web_scanner on initial targets ──
        if scan_targets:
            self.tools_attempted.add("web_scanner")
            logger.info("[Auth] Running web_scanner on %d targets", len(scan_targets))
            for target in scan_targets:
                web_findings = self._run_tool(
                    "web_scanner", [target], timeout=TOOL_TIMEOUT_LONG
                )
                all_findings.extend(web_findings)
                self._publish_findings_signals(web_findings)

        # ── Phase 3: Mid-run peer intel — process peer-discovered endpoints ──
        new_peer_targets = self._get_new_peer_targets(processed_targets)
        if new_peer_targets:
            logger.info(
                "[Auth] Processing %d mid-run peer-discovered endpoint(s)",
                len(new_peer_targets),
            )
            self.tools_attempted.add("web_scanner")
            for target in new_peer_targets:
                processed_targets.add(target)
                web_findings = self._run_tool(
                    "web_scanner", [target], timeout=TOOL_TIMEOUT_LONG
                )
                all_findings.extend(web_findings)
                self._publish_findings_signals(web_findings)

        # Publish auth context to peers
        if self.swarm_memory:
            self.swarm_memory.publish_auth_context(
                self.DOMAIN, {"auth_type": "jwt" if any(
                    f.get("type", "") == "JWT" for f in all_findings
                ) else "session"}
            )
            summary = (
                f"Auth: {len(all_findings)} findings across {len(processed_targets)} targets"
            )
            self.swarm_memory.publish_summary(self.DOMAIN, summary)

        logger.info("[Auth] Total findings: %d", len(all_findings))
        return self._tag_findings(all_findings)


class APIAgent(SpecialistAgent):
    """Deep API security testing for REST and GraphQL endpoints."""

    DOMAIN = "api"
    PRIORITY_TOOLS = ["arjun", "nuclei", "dalfox", "sqlmap"]

    @staticmethod
    def _has_api_signals(rc) -> bool:
        """Check for actual API signals, not just crawled paths."""
        if not hasattr(rc, "live_endpoints"):
            return False
        api_paths = [
            ep for ep in (rc.live_endpoints or []) if "/api/" in (ep or "").lower()
        ]
        return len(api_paths) >= 2

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        specific = (
            hasattr(rc, "has_api")
            and rc.has_api
            and hasattr(rc, "api_endpoints")
            and len(rc.api_endpoints) > 1
        ) or (hasattr(rc, "api_endpoints") and len(rc.api_endpoints) > 5)
        if specific:
            return True
        return bool(
            self._has_api_signals(rc)
            and hasattr(rc, "crawled_paths")
            and len(rc.crawled_paths) >= 5
        )

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []

        # ── Phase 1: Initial targets ──
        targets = self._get_targets()
        targets = self._enrich_targets_with_peer_intel(targets)

        # Log peer tech context summary
        tech_ctx = self._collect_peer_tech_context()
        if tech_ctx:
            logger.info("[API] Peer tech context: %s", tech_ctx)
        api_endpoints = (
            self.recon_context.api_endpoints
            if self.recon_context and hasattr(self.recon_context, "api_endpoints")
            else []
        )

        scan_targets = list(set(targets + api_endpoints))
        if (
            not scan_targets
            and self.recon_context
            and hasattr(self.recon_context, "target_url")
        ):
            scan_targets = [self.recon_context.target_url]

        processed_targets: set[str] = set(scan_targets) if scan_targets else set()

        for target in scan_targets:
            # 1. arjun parameter discovery on API paths
            logger.info("[API] Running arjun on %s", target)
            try:
                sandbox = (
                    self.tool_runner.sandbox_dir
                    if hasattr(self.tool_runner, "sandbox_dir")
                    and self.tool_runner.sandbox_dir
                    else None
                )
                if sandbox:
                    arjun_out = str(
                        sandbox / "tmp" / f"arjun_api_{self.engagement_id}.json"
                    )
                else:
                    arjun_out = os.path.join(
                        tempfile.gettempdir(), f"arjun_api_{self.engagement_id}.json"
                    )
                arjun_findings = self._run_tool(
                    "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", "20"],
                    timeout=TOOL_TIMEOUT_DEFAULT,
                )
                all_findings.extend(arjun_findings)
                self._publish_findings_signals(arjun_findings)
                # M-v5-04: Clean up temp file if not using sandbox
                if not sandbox:
                    try:
                        if os.path.exists(arjun_out):
                            os.remove(arjun_out)
                    except Exception:
                        logger.debug("Failed to clean up temp file: %s", arjun_out)
            except Exception as e:
                logger.warning("[API] arjun failed for %s: %s", target, e)

            # 2. nuclei API-* tagged templates
            logger.info("[API] Running nuclei API templates on %s", target)
            try:
                from orchestrator_pkg.utils import get_nuclei_templates_path

                templates_path = get_nuclei_templates_path()
                nuclei_cmd = [
                    "-u",
                    target,
                    "-jsonl",
                    "-silent",
                    "-severity",
                    "medium,high,critical",
                ]
                if templates_path.exists():
                    nuclei_cmd.extend(["-t", str(templates_path)])
                nuclei_cmd.extend(
                    [
                        "-tags",
                        "api,graphql,swagger,openapi,rest,injection,idor,ssrf",
                    ]
                )
                nuclei_findings = self._run_tool(
                    "nuclei",
                    nuclei_cmd,
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(nuclei_findings)
                self._publish_findings_signals(nuclei_findings)
            except Exception as e:
                logger.warning("[API] nuclei failed for %s: %s", target, e)

            # 3. dalfox XSS scanner on API params
            logger.info("[API] Running dalfox on %s", target)
            try:
                dalfox_findings = self._run_tool(
                    "dalfox",
                    ["url", target, "--json"],
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(dalfox_findings)
                self._publish_findings_signals(dalfox_findings)
            except Exception as e:
                logger.warning("[API] dalfox failed for %s: %s", target, e)

            # 4. sqlmap injection testing on API params
            # Re-validate target (SSRF + scope) before sqlmap execution
            from urllib.parse import urlparse

            hostname = urlparse(target).hostname or target.split("/")[0].split(":")[0]
            if hostname and ScopeValidator.is_internal_address(hostname):
                logger.warning(
                    "[API] Skipping sqlmap for %s — blocked internal/SSRF target", target
                )
                continue
            if not validate_target_scope(target, self.engagement_id):
                logger.warning(
                    "[API] Skipping sqlmap for %s — not in authorized scope", target
                )
                continue

            logger.info("[API] Running sqlmap on %s", target)
            try:
                sandbox = (
                    self.tool_runner.sandbox_dir
                    if hasattr(self.tool_runner, "sandbox_dir")
                    and self.tool_runner.sandbox_dir
                    else None
                )
                if sandbox:
                    sqlmap_out = str(
                        sandbox / "tmp" / f"sqlmap_api_{self.engagement_id}.json"
                    )
                else:
                    sqlmap_out = os.path.join(
                        tempfile.gettempdir(), f"sqlmap_api_{self.engagement_id}.json"
                    )
                sqlmap_findings = self._run_tool(
                    "sqlmap",
                    ["-u", target, "--batch", "--json-output", sqlmap_out],
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(sqlmap_findings)
                self._publish_findings_signals(sqlmap_findings)
                # M-v5-04: Clean up temp file if not using sandbox
                if not sandbox:
                    try:
                        if os.path.exists(sqlmap_out):
                            os.remove(sqlmap_out)
                    except Exception:
                        logger.debug("Failed to clean up temp file: %s", sqlmap_out)
            except Exception as e:
                logger.warning("[API] sqlmap failed for %s: %s", target, e)

        # ── Phase 2: Mid-run peer intel — process peer-discovered endpoints ──
        new_peer_targets = self._get_new_peer_targets(processed_targets)
        if new_peer_targets:
            logger.info(
                "[API] Processing %d mid-run peer-discovered endpoint(s)",
                len(new_peer_targets),
            )
            for target in new_peer_targets:
                processed_targets.add(target)

                # Run remaining tools (nuclei, dalfox, sqlmap) against new target
                # Re-validate target before tool runs
                from urllib.parse import urlparse
                hostname = urlparse(target).hostname or target.split("/")[0].split(":")[0]
                if hostname and ScopeValidator.is_internal_address(hostname):
                    continue
                if not validate_target_scope(target, self.engagement_id):
                    continue

                # Nuclei
                try:
                    from orchestrator_pkg.utils import get_nuclei_templates_path
                    templates_path = get_nuclei_templates_path()
                    nuclei_cmd = ["-u", target, "-jsonl", "-silent", "-severity", "medium,high,critical"]
                    if templates_path.exists():
                        nuclei_cmd.extend(["-t", str(templates_path)])
                    nuclei_cmd.extend(["-tags", "api,graphql,swagger,openapi,rest,injection,idor,ssrf"])
                    nuclei_findings = self._run_tool("nuclei", nuclei_cmd, timeout=TOOL_TIMEOUT_LONG)
                    all_findings.extend(nuclei_findings)
                    self._publish_findings_signals(nuclei_findings)
                except Exception as e:
                    logger.warning("[API] nuclei on peer target %s failed: %s", target, e)

                # Dalfox
                try:
                    dalfox_findings = self._run_tool("dalfox", ["url", target, "--json"], timeout=TOOL_TIMEOUT_LONG)
                    all_findings.extend(dalfox_findings)
                    self._publish_findings_signals(dalfox_findings)
                except Exception as e:
                    logger.warning("[API] dalfox on peer target %s failed: %s", target, e)

                # Sqlmap
                try:
                    sandbox = (
                        self.tool_runner.sandbox_dir
                        if hasattr(self.tool_runner, "sandbox_dir") and self.tool_runner.sandbox_dir
                        else None
                    )
                    if sandbox:
                        sqlmap_out = str(sandbox / "tmp" / f"sqlmap_api_peer_{self.engagement_id}.json")
                    else:
                        sqlmap_out = os.path.join(tempfile.gettempdir(), f"sqlmap_api_peer_{self.engagement_id}.json")
                    sqlmap_findings = self._run_tool(
                        "sqlmap", ["-u", target, "--batch", "--json-output", sqlmap_out],
                        timeout=TOOL_TIMEOUT_LONG,
                    )
                    all_findings.extend(sqlmap_findings)
                    self._publish_findings_signals(sqlmap_findings)
                    if not sandbox:
                        try:
                            if os.path.exists(sqlmap_out):
                                os.remove(sqlmap_out)
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("[API] sqlmap on peer target %s failed: %s", target, e)

        # Publish completion summary for peer agents
        if self.swarm_memory:
            summary = (
                f"API: {len(all_findings)} findings across {len(processed_targets)} targets"
            )
            self.swarm_memory.publish_summary(self.DOMAIN, summary)

        logger.info("[API] Total findings: %d", len(all_findings))
        return self._tag_findings(all_findings)


class SwarmOrchestrator:
    """Runs specialist agents in parallel and merges findings.

    Activation is based on ReconContext signals. Each agent gets a deep
    copy of the context. Merging uses evidence-weighted dedup with
    fallback (type+endpoint) fingerprint for consistent cross-agent merging.
    """

    SPECIALIST_CLASSES = [IDORAgent, AuthAgent, APIAgent]

    def __init__(
        self,
        llm_service: Any,
        tool_runner: Any,
        recon_context: Any,
        engagement_id: str,
        decision_repo: Any = None,
        auth_config: dict | None = None,
        bug_bounty_mode: bool = False,
    ):
        self.bug_bounty_mode = bug_bounty_mode
        # In-flight cross-agent learning: shared memory for signal exchange
        self.swarm_memory = SwarmMemory()
        # Deep copy happens inside each agent's __init__
        self.agents = [
            cls(  # type: ignore[abstract]
                llm_service=llm_service,
                tool_runner=tool_runner,
                recon_context=recon_context,
                engagement_id=engagement_id,
                decision_repo=decision_repo,
                auth_config=auth_config,
                bug_bounty_mode=self.bug_bounty_mode,
                swarm_memory=self.swarm_memory,
            )
            for cls in self.SPECIALIST_CLASSES
        ]
        self.auth_config = auth_config or {}

    def run(self, timeout: int = 1800) -> tuple[list[dict], set[str]]:
        """Run all active specialists in parallel and merge findings.

        Args:
            timeout: Maximum wall-clock time in seconds (default 30 min)

        Returns:
            (deduplicated findings list, set of all tools executed)
        """
        # ── Metrics initialization ──
        metrics = SwarmMetrics()
        engagement_id = self.agents[0].engagement_id if self.agents else ""

        active = [a for a in self.agents if a.should_activate()]
        slog = ScanLogger(
            "swarm", engagement_id=active[0].engagement_id if active else ""
        )

        # Record activation / inactivity
        metrics.total_agents = len(self.agents)
        for agent in self.agents:
            if agent in active:
                metrics.activated_agents.append(agent.DOMAIN)
            else:
                rc = agent.recon_context
                reason = _diagnose_inactivity(agent.DOMAIN, rc)
                metrics.inactive_agents.append({
                    "domain": agent.DOMAIN,
                    "reason": reason,
                })

        if not active:
            logger.info("Swarm: no specialists activated")
            logger.info("[SWARM_METRICS] %s", metrics.to_dict())
            slog.info("No specialists activated")
            if engagement_id:
                emit_swarm_metrics(engagement_id, metrics.to_dict())
            return [], set()

        slog.swarm_activate([a.DOMAIN for a in active])
        logger.info(
            "Swarm: activating %d specialist(s): %s",
            len(active),
            [a.DOMAIN for a in active],
        )

        emit_swarm_agent_started(active[0].engagement_id, "swarm_orchestrator")

        all_findings: list[dict] = []
        all_findings_lock = threading.Lock()
        completed: set[str] = set()
        # Track per-agent findings/errors/timeouts for metrics
        # (tools_attempted is extracted from agent.tools_attempted after completion)
        agent_findings_count: dict[str, int] = {}
        agent_errors: dict[str, int] = {}
        agent_timeouts: dict[str, int] = {}

        per_agent_timeout = max(
            timeout // max(len(active), 1), 300
        )  # at least 5 min per agent

        pool = ThreadPoolExecutor(max_workers=len(active))
        try:
            futures_map: dict[concurrent.futures.Future, str] = {}
            for agent in active:
                future = pool.submit(agent.run)
                futures_map[future] = agent.DOMAIN

            try:
                for future in concurrent.futures.as_completed(
                    futures_map,
                    timeout=timeout,
                ):
                    domain = futures_map.get(future, "?")
                    try:
                        result = future.result()  # future is already done (returned by as_completed); per-agent timeout is dead code here
                        if result:
                            logger.info(
                                "Specialist %s returned %d findings",
                                domain,
                                len(result),
                            )
                            emit_swarm_agent_complete(
                                active[0].engagement_id,
                                domain,
                                findings_count=len(result),
                            )
                            agent_findings_count[domain] = len(result)
                            with all_findings_lock:
                                all_findings.extend(result)
                            completed.add(domain)
                        else:
                            logger.info("Specialist %s returned no findings", domain)
                            emit_swarm_agent_complete(
                                active[0].engagement_id,
                                domain,
                                findings_count=0,
                            )
                            agent_findings_count[domain] = 0
                            completed.add(domain)
                    # Mark domain as completed even on error.
                    # Without this, the kill-loop guard (len(completed) < len(futures_map))
                    # would be True on normal completion with empty findings, causing
                    # the orphan-subprocess cleanup to run unnecessarily (and potentially
                    # kill subprocesses from concurrent tasks in the same worker).
                    except concurrent.futures.TimeoutError:
                        logger.warning(
                            "Swarm: agent %s timed out per-task (%ds)",
                            domain,
                            per_agent_timeout,
                        )
                        emit_swarm_agent_complete(
                            active[0].engagement_id, domain, findings_count=0
                        )
                        agent_findings_count[domain] = 0
                        agent_timeouts[domain] = agent_timeouts.get(domain, 0) + 1
                        completed.add(domain)
                    except Exception as e:
                        logger.warning("Swarm agent %s failed: %s", domain, e)
                        emit_swarm_agent_complete(
                            active[0].engagement_id, domain, findings_count=0
                        )
                        agent_findings_count[domain] = 0
                        agent_errors[domain] = agent_errors.get(domain, 0) + 1
                        completed.add(domain)
            except concurrent.futures.TimeoutError:
                remaining = set(futures_map.values()) - completed
                for domain in remaining:
                    logger.warning(
                        "Swarm: agent %s timed out — global timeout reached", domain
                    )
                    emit_swarm_agent_complete(
                        active[0].engagement_id, domain, findings_count=0
                    )
                    agent_findings_count[domain] = 0
                    agent_timeouts[domain] = agent_timeouts.get(domain, 0) + 1

            # Cancel remaining futures and actively terminate any running tool subprocesses.
            for future, domain in futures_map.items():
                if domain not in completed:
                    logger.warning(
                        "Swarm: agent %s timed out — terminating running subprocesses",
                        domain,
                    )
                    future.cancel()

            # Kill orphaned tool subprocesses spawned by timed-out agents.
            # GUARD: Only run cleanup when there were actual timeouts (agents not in
            # `completed`). Without this guard, the kill loop would run on EVERY swarm
            # completion and could kill subprocesses belonging to CONCURRENT tasks in
            # the same Celery worker process (e.g., a nuclei running for another
            # engagement would be killed by this swarm's cleanup).
            metrics.orphan_cleanup_ran = len(completed) < len(futures_map)
            if len(completed) < len(futures_map):
                _KNOWN_TOOL_PROCS = {
                    "nuclei",
                    "sqlmap",
                    "dalfox",
                    "nikto",
                    "nmap",
                    "arjun",
                    "jwt_tool",
                    "ffuf",
                    "commix",
                    "testssl",
                }
                try:
                    from contextlib import suppress

                    import psutil

                    current_process = psutil.Process()
                    for child in current_process.children(recursive=True):
                        with suppress(psutil.NoSuchProcess):
                            try:
                                child_name = child.name().lower()
                                if any(tool in child_name for tool in _KNOWN_TOOL_PROCS):
                                    logger.info(
                                        "Swarm cleanup: killing orphaned %s (pid=%d)",
                                        child_name,
                                        child.pid,
                                    )
                                    child.kill()
                                    metrics.orphans_killed += 1
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                except ImportError:
                    logger.warning(
                        "psutil not installed — cannot kill orphaned tool subprocesses. "
                        "Install psutil to prevent resource leaks from timed-out swarm agents."
                    )
                except Exception:
                    logger.debug("Could not kill orphaned tool processes", exc_info=True)
        finally:
            # Shut down the pool with wait=False to avoid blocking on hung threads.
            # Using a manual pool (not `with ThreadPoolExecutor()`) because __exit__
            # calls shutdown(wait=True) which blocks indefinitely on hung threads.
            pool.shutdown(wait=False, cancel_futures=True)

        deduped = self._deduplicate(all_findings)
        dedup_removed = len(all_findings) - len(deduped)
        logger.info(
            "Swarm: %d raw findings → %d after dedup",
            len(all_findings),
            len(deduped),
        )
        slog.swarm_complete(len(all_findings), len(deduped))
        emit_swarm_merge_complete(
            active[0].engagement_id,
            total_findings=len(deduped),
            dedup_removed=dedup_removed,
        )

        # Collect per-agent tool usage
        for agent in self.agents:
            tools: set[str] = getattr(agent, "tools_attempted", set())
            metrics.per_agent_tools[agent.DOMAIN] = sorted(tools)

        # Populate metrics struct
        metrics.per_agent_findings = agent_findings_count
        metrics.per_agent_errors = agent_errors
        metrics.per_agent_timeouts = agent_timeouts
        metrics.raw_findings_total = len(all_findings)
        metrics.deduped_findings_total = len(deduped)
        metrics.dedup_removed = dedup_removed
        metrics.dedup_ratio = (
            dedup_removed / max(len(all_findings), 1)
            if len(all_findings) > 0
            else 0.0
        )

        # Emit structured metrics
        logger.info("[SWARM_METRICS] %s", metrics.to_dict())
        emit_swarm_metrics(active[0].engagement_id, metrics.to_dict())

        all_tools_attempted: set[str] = set()
        for agent in self.agents:
            tools: set[str] = getattr(agent, "tools_attempted", set())
            all_tools_attempted.update(tools)

        return deduped, all_tools_attempted


    @staticmethod
    def _deduplicate(findings: list[dict]) -> list[dict]:
        """Deduplicate findings by type + endpoint (fallback fingerprint).

        Uses ScanDiffEngine._fallback_fingerprint() which only considers
        type and endpoint (not payload), so the same vulnerability detected
        with different payload examples gets merged into one finding.
        The finding with richer evidence or higher confidence wins.
        """
        seen: dict[str, dict] = {}
        for f in findings:
            fp = ScanDiffEngine._fallback_fingerprint(f)
            if fp not in seen:
                seen[fp] = {**f}  # shallow copy to avoid mutating caller's findings
                continue

            existing = seen[fp]
            existing_conf = float(existing.get("confidence", 0))
            new_conf = float(f.get("confidence", 0))

            # Merge source_agents
            existing_agents = set()
            if existing.get("source_agent"):
                existing_agents.add(existing["source_agent"])
            if existing.get("source_agents"):
                existing_agents.update(existing["source_agents"])
            if f.get("source_agent"):
                existing_agents.add(f["source_agent"])
            if f.get("source_agents"):
                existing_agents.update(f["source_agents"])

            # Merge evidence
            existing_ev = existing.get("evidence", {}) or {}
            new_ev = f.get("evidence", {}) or {}
            if isinstance(existing_ev, dict) and isinstance(new_ev, dict):
                merged_evidence = {**existing_ev, **new_ev}
            else:
                merged_evidence = (
                    new_ev if len(str(new_ev)) > len(str(existing_ev)) else existing_ev
                )

            # Keys that should NOT be carried over from the existing finding
            # (the new finding's values take priority).
            _overwrite_keys = {
                "confidence",
                "evidence",
                "source_agent",
                "source_agents",
                "source_tool",
            }

            if new_conf > existing_conf:
                # Merge: use higher-confidence finding as base but preserve
                # all metadata from the existing finding that the new one lacks.
                merged = {**f}
                merged["evidence"] = merged_evidence
                merged["source_agents"] = list(existing_agents)
                for key, value in existing.items():
                    if key not in _overwrite_keys and not merged.get(key):
                        merged[key] = value
                seen[fp] = merged
            elif new_conf == existing_conf:
                existing_evidence_len = len(str(existing_ev))
                new_evidence_len = len(str(new_ev))
                if new_evidence_len > existing_evidence_len:
                    merged = {**f}
                    merged["evidence"] = merged_evidence
                    merged["source_agents"] = list(existing_agents)
                    for key, value in existing.items():
                        if key not in _overwrite_keys and not merged.get(key):
                            merged[key] = value
                    seen[fp] = merged
                else:
                    existing["evidence"] = merged_evidence
                    existing["source_agents"] = list(existing_agents)

        return list(seen.values())


# ── Helper: diagnose why an agent did not activate ──


def _diagnose_inactivity(domain: str, rc) -> str:
    """Return a human-readable reason why a specialist agent did not activate.

    Checks domain-specific signal fields on ReconContext and returns the
    first missing prerequisite.
    """
    if rc is None:
        return "no recon_context (None)"

    if domain == "idor":
        if not (hasattr(rc, "parameter_bearing_urls") and len(rc.parameter_bearing_urls) > 0):
            if not (hasattr(rc, "has_api") and rc.has_api):
                if not (hasattr(rc, "api_endpoints") and len(rc.api_endpoints) > 0):
                    crawled = len(rc.crawled_paths) if hasattr(rc, "crawled_paths") and rc.crawled_paths else 0
                    dynamic = (
                        (hasattr(rc, "parameter_bearing_urls") and len(rc.parameter_bearing_urls) > 0)
                        or (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0)
                        or (hasattr(rc, "has_api") and rc.has_api)
                    )
                    if crawled < 25:
                        return f"insufficient crawled_paths ({crawled}/25)"
                    if not dynamic:
                        return "no dynamic surface (params, auth, or API)"
                    return "thresholds not met"
        return "activated (IDOR)"  # fallthrough shouldn't happen

    if domain == "auth":
        if not (hasattr(rc, "has_login_page") and rc.has_login_page):
            if not (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0):
                if not (hasattr(rc, "has_api") and rc.has_api):
                    crawled = len(rc.crawled_paths) if hasattr(rc, "crawled_paths") and rc.crawled_paths else 0
                    dynamic = (
                        (hasattr(rc, "parameter_bearing_urls") and len(rc.parameter_bearing_urls) > 0)
                        or (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0)
                        or (hasattr(rc, "has_api") and rc.has_api)
                    )
                    if crawled < 25:
                        return f"insufficient crawled_paths ({crawled}/25)"
                    if not dynamic:
                        return "no dynamic surface (auth or API)"
                    return "thresholds not met"
        return "activated (Auth)"

    if domain == "api":
        api_endpoints = len(rc.api_endpoints) if hasattr(rc, "api_endpoints") and rc.api_endpoints else 0
        has_api = hasattr(rc, "has_api") and rc.has_api
        if not (has_api and api_endpoints > 1) and not (api_endpoints > 5):
            live = [ep for ep in (rc.live_endpoints or []) if "/api/" in (ep or "").lower()]
            crawled = len(rc.crawled_paths) if hasattr(rc, "crawled_paths") and rc.crawled_paths else 0
            if len(live) < 2:
                return f"insufficient API signal (has_api={has_api}, api_endpoints={api_endpoints}, live_api_paths={len(live)})"
            if crawled < 5:
                return f"insufficient crawled_paths ({crawled}/5)"
            return "thresholds not met"
        return "activated (API)"

    return "unknown domain"
