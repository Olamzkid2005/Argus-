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
from typing import Any

from scan_diff_engine import ScanDiffEngine
from streaming import (
    emit_swarm_agent_action,
    emit_swarm_agent_complete,
    emit_swarm_agent_started,
    emit_swarm_merge_complete,
)
from tools.scope_validator import ScopeValidator, validate_target_scope
from utils.logging_utils import ScanLogger

# In-flight cross-agent learning: thread-safe shared memory for signal exchange
from agent.swarm_memory import SwarmMemory

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_DEFAULT = 180
TOOL_TIMEOUT_LONG = 600


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
        - New endpoints (from finding endpoint fields)
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

            # Extract evidence-based endpoints
            evidence = f.get("evidence", {}) or {}
            if isinstance(evidence, dict):
                for val in evidence.values():
                    if isinstance(val, str) and val.startswith("http"):
                        endpoints.add(val.rstrip("/"))

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
        existing = {t.rstrip("/") for t in targets}
        # Validate scope for peer-discovered endpoints
        safe_new: list[str] = []
        for ep in new_endpoints:
            ep_clean = ep.rstrip("/")
            if ep_clean in existing:
                continue
            from urllib.parse import urlparse
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

        # In-flight cross-agent learning: check what peers have discovered
        targets = self._get_targets()
        targets = self._enrich_targets_with_peer_intel(targets)

        # Log peer intel summary (enrich_targets_with_peer_intel already calls
        # _gather_peer_intel internally)
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
                # Publish arjun-discovered endpoints/params to peers
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

        # 3. web_scanner IDOR-focused checks on all targets
        if targets:
            self.tools_attempted.add("web_scanner")
            logger.info("[IDOR] Running web_scanner on %d targets", len(targets))
            for target in targets:
                web_findings = self._run_tool(
                    "web_scanner", [target], timeout=TOOL_TIMEOUT_LONG
                )
                all_findings.extend(web_findings)
                self._publish_findings_signals(web_findings)

        # Publish completion summary for peer agents
        if self.swarm_memory:
            summary = (
                f"IDOR: {len(all_findings)} findings across {len(targets)} targets"
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

        # In-flight cross-agent learning: incorporate peer-discovered endpoints
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

        # 3. Password reset / login flow testing via web_scanner
        if scan_targets:
            self.tools_attempted.add("web_scanner")
            logger.info("[Auth] Running web_scanner on %d targets", len(scan_targets))
            for target in scan_targets:
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
                f"Auth: {len(all_findings)} findings across {len(scan_targets)} targets"
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

        # In-flight cross-agent learning: incorporate peer-discovered endpoints
        targets = self._get_targets()
        targets = self._enrich_targets_with_peer_intel(targets)

        # Log peer tech context summary (enrich_targets_with_peer_intel already
        # calls _gather_peer_intel internally for endpoint enrichment)
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

        # Publish completion summary for peer agents
        if self.swarm_memory:
            summary = (
                f"API: {len(all_findings)} findings across {len(scan_targets)} targets"
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
        active = [a for a in self.agents if a.should_activate()]
        slog = ScanLogger(
            "swarm", engagement_id=active[0].engagement_id if active else ""
        )

        if not active:
            logger.info("Swarm: no specialists activated")
            slog.info("No specialists activated")
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
                        completed.add(domain)
                    except Exception as e:
                        logger.warning("Swarm agent %s failed: %s", domain, e)
                        emit_swarm_agent_complete(
                            active[0].engagement_id, domain, findings_count=0
                        )
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
