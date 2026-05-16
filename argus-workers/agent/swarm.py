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
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from streaming import (
    emit_swarm_agent_started,
    emit_swarm_agent_action,
    emit_swarm_agent_complete,
    emit_swarm_merge_complete,
)
from utils.logging_utils import ScanLogger

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
    ):
        # IMPORTANT: deep copy — never share mutable state across agents
        self.recon_context = (
            copy.deepcopy(recon_context) if recon_context else None
        )
        self.llm_service = llm_service
        self.tool_runner = tool_runner
        self.engagement_id = engagement_id
        self.decision_repo = decision_repo
        self.auth_config = auth_config or {}
        self.bug_bounty_mode = bug_bounty_mode
        self.findings: list[dict] = []
        self._parser = None

    @abstractmethod
    def should_activate(self) -> bool:
        """Return True if recon signals suggest this domain is relevant."""

    @abstractmethod
    def run(self) -> list[dict]:
        """Run this specialist's tool suite. Returns raw finding dicts."""

    @property
    def parser(self):
        """Lazy-init parser for tool output parsing."""
        if self._parser is None:
            from parsers.parser import Parser

            self._parser = Parser()
        return self._parser

    def _run_tool(self, tool_name: str, args: list, timeout: int = TOOL_TIMEOUT_DEFAULT) -> list[dict]:
        """Run a single tool and return parsed findings."""
        findings = []
        try:
            emit_swarm_agent_action(
                self.engagement_id, self.DOMAIN, tool_name,
                reasoning=f"Running {tool_name} with args: {' '.join(args[:4])}...",
            )
            result = self.tool_runner.run(tool_name, args, timeout=timeout)
            if result.success and result.stdout:
                parsed = self.parser.parse(tool_name, result.stdout)
                for p in parsed:
                    findings.append(p)
            elif result.stderr:
                logger.debug(f"{self.DOMAIN}/{tool_name} stderr: {result.stderr[:200]}")
        except Exception as e:
            logger.warning(f"{self.DOMAIN}/{tool_name} failed: {e}")
        return findings

    def _get_targets(self) -> list[str]:
        """Extract target URLs from recon context."""
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
            base = rc.target_url.rstrip("/") if rc.target_url else ""
            for path in rc.crawled_paths[:20]:
                if path.startswith("http"):
                    targets.append(path)
                elif base:
                    targets.append(f"{base}{path}" if path.startswith("/") else f"{base}/{path}")
        if not targets and rc.target_url:
            targets = [rc.target_url]
        return targets

    @staticmethod
    def _has_dynamic_surface(rc) -> bool:
        """Check if recon context shows a dynamic webapp with actionable attack surface.

        Returns True when the target has parameter-bearing URLs, auth endpoints,
        or API endpoints — signals that the app processes user input and has
        meaningful attack surface. Raw page count alone is not enough.
        """
        return (
            (hasattr(rc, "parameter_bearing_urls") and len(rc.parameter_bearing_urls) > 0)
            or (hasattr(rc, "auth_endpoints") and len(rc.auth_endpoints) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
        )

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
            (hasattr(rc, "parameter_bearing_urls") and len(rc.parameter_bearing_urls) > 0)
            or (hasattr(rc, "has_api") and rc.has_api)
            or (hasattr(rc, "api_endpoints") and len(rc.api_endpoints) > 0)
        )
        if specific:
            return True
        if hasattr(rc, "crawled_paths") and len(rc.crawled_paths) >= 10 and self._has_dynamic_surface(rc):
            return True
        return False

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []
        targets = self._get_targets()

        for target in targets:
            # 1. Arjun parameter discovery on API endpoints
            logger.info(f"[IDOR] Running arjun on {target}")
            try:
                arjun_out = str(self.tool_runner.sandbox_dir / "tmp" / f"arjun_idor.json")
                arjun_findings = self._run_tool(
                    "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", "20"],
                    timeout=TOOL_TIMEOUT_DEFAULT,
                )
                all_findings.extend(arjun_findings)
            except Exception as e:
                logger.warning(f"[IDOR] arjun failed for {target}: {e}")

            # 2. jwt_tool for token manipulation (IDOR via JWT)
            logger.info(f"[IDOR] Running jwt_tool on {target}")
            try:
                jwt_findings = self._run_tool(
                    "jwt_tool",
                    [target, "-C", "-d"],
                    timeout=120,
                )
                all_findings.extend(jwt_findings)
            except Exception as e:
                logger.warning(f"[IDOR] jwt_tool failed for {target}: {e}")

        # 3. web_scanner IDOR-focused checks on all targets
        if targets:
            try:
                from tools.web_scanner import WebScanner

                logger.info(f"[IDOR] Running web_scanner on {len(targets)} targets")
                scanner = WebScanner()
                for target in targets:
                    try:
                        emit_swarm_agent_action(
                            self.engagement_id, self.DOMAIN, "web_scanner",
                            reasoning=f"IDOR-focused scan of {target}",
                        )
                        web_findings = scanner.scan(target)
                        all_findings.extend(web_findings)
                    except Exception as e:
                        logger.warning(f"[IDOR] web_scanner failed for {target}: {e}")
            except ImportError:
                logger.debug("[IDOR] WebScanner not available, skipping")

        logger.info(f"[IDOR] Total findings: {len(all_findings)}")
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
        if hasattr(rc, "crawled_paths") and len(rc.crawled_paths) >= 10 and self._has_dynamic_surface(rc):
            return True
        return False

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []
        targets = self._get_targets()
        auth_endpoints = (
            self.recon_context.auth_endpoints
            if self.recon_context and hasattr(self.recon_context, "auth_endpoints")
            else []
        )

        scan_targets = list(set(targets + auth_endpoints))
        if not scan_targets and self.recon_context:
            scan_targets = [self.recon_context.target_url]

        for target in scan_targets:
            # 1. jwt_tool checks on auth endpoints
            logger.info(f"[Auth] Running jwt_tool on {target}")
            try:
                jwt_findings = self._run_tool(
                    "jwt_tool",
                    [target, "-C", "-d"],
                    timeout=120,
                )
                all_findings.extend(jwt_findings)
            except Exception as e:
                logger.warning(f"[Auth] jwt_tool failed for {target}: {e}")

            # 2. nuclei auth-related templates
            logger.info(f"[Auth] Running nuclei auth templates on {target}")
            try:
                from orchestrator_pkg.utils import get_nuclei_templates_path

                templates_path = get_nuclei_templates_path()
                nuclei_cmd = [
                    "-u", target,
                    "-jsonl-export", "-",
                    "-silent",
                    "-severity", "medium,high,critical",
                ]
                if templates_path.exists():
                    nuclei_cmd.extend(["-t", str(templates_path)])
                nuclei_cmd.extend([
                    "-tags", "auth,login,jwt,oauth,session,default-login,bruteforce",
                ])
                nuclei_findings = self._run_tool(
                    "nuclei",
                    nuclei_cmd,
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(nuclei_findings)
            except Exception as e:
                logger.warning(f"[Auth] nuclei failed for {target}: {e}")

        # 3. Password reset / login flow testing via web_scanner
        if scan_targets:
            try:
                from tools.web_scanner import WebScanner

                logger.info(f"[Auth] Running web_scanner on {len(scan_targets)} targets")
                scanner = WebScanner()
                for target in scan_targets:
                    try:
                        emit_swarm_agent_action(
                            self.engagement_id, self.DOMAIN, "web_scanner",
                            reasoning=f"Auth-focused scan of {target}",
                        )
                        web_findings = scanner.scan(target)
                        all_findings.extend(web_findings)
                    except Exception as e:
                        logger.warning(f"[Auth] web_scanner failed for {target}: {e}")
            except ImportError:
                logger.debug("[Auth] WebScanner not available, skipping")

        logger.info(f"[Auth] Total findings: {len(all_findings)}")
        return self._tag_findings(all_findings)


class APIAgent(SpecialistAgent):
    """Deep API security testing for REST and GraphQL endpoints."""

    DOMAIN = "api"
    PRIORITY_TOOLS = ["arjun", "nuclei", "dalfox", "sqlmap"]

    def should_activate(self) -> bool:
        if not self.recon_context:
            return False
        rc = self.recon_context
        specific = (
            (hasattr(rc, "has_api") and rc.has_api)
            or (hasattr(rc, "api_endpoints") and len(rc.api_endpoints) > 5)
        )
        if specific:
            return True
        if hasattr(rc, "crawled_paths") and len(rc.crawled_paths) >= 10 and self._has_dynamic_surface(rc):
            return True
        return False

    def run(self) -> list[dict]:
        emit_swarm_agent_started(self.engagement_id, self.DOMAIN)
        all_findings: list[dict] = []
        targets = self._get_targets()
        api_endpoints = (
            self.recon_context.api_endpoints
            if self.recon_context and hasattr(self.recon_context, "api_endpoints")
            else []
        )

        scan_targets = list(set(targets + api_endpoints))
        if not scan_targets and self.recon_context:
            scan_targets = [self.recon_context.target_url]

        for target in scan_targets:
            # 1. arjun parameter discovery on API paths
            logger.info(f"[API] Running arjun on {target}")
            try:
                arjun_out = str(self.tool_runner.sandbox_dir / "tmp" / f"arjun_api.json")
                arjun_findings = self._run_tool(
                    "arjun",
                    ["-u", target, "-m", "GET", "-o", arjun_out, "-t", "20"],
                    timeout=TOOL_TIMEOUT_DEFAULT,
                )
                all_findings.extend(arjun_findings)
            except Exception as e:
                logger.warning(f"[API] arjun failed for {target}: {e}")

            # 2. nuclei API-* tagged templates
            logger.info(f"[API] Running nuclei API templates on {target}")
            try:
                from orchestrator_pkg.utils import get_nuclei_templates_path

                templates_path = get_nuclei_templates_path()
                nuclei_cmd = [
                    "-u", target,
                    "-jsonl-export", "-",
                    "-silent",
                    "-severity", "medium,high,critical",
                ]
                if templates_path.exists():
                    nuclei_cmd.extend(["-t", str(templates_path)])
                nuclei_cmd.extend([
                    "-tags", "api,graphql,swagger,openapi,rest,injection,idor,ssrf",
                ])
                nuclei_findings = self._run_tool(
                    "nuclei",
                    nuclei_cmd,
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(nuclei_findings)
            except Exception as e:
                logger.warning(f"[API] nuclei failed for {target}: {e}")

            # 3. dalfox XSS scanner on API params
            logger.info(f"[API] Running dalfox on {target}")
            try:
                dalfox_findings = self._run_tool(
                    "dalfox",
                    ["url", target, "--json"],
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(dalfox_findings)
            except Exception as e:
                logger.warning(f"[API] dalfox failed for {target}: {e}")

            # 4. sqlmap injection testing on API params
            logger.info(f"[API] Running sqlmap on {target}")
            logger.warning("[API] sqlmap executing against %s — verify target is in authorized scope", target)
            try:
                sqlmap_out = str(self.tool_runner.sandbox_dir / "tmp" / f"sqlmap_api.json")
                sqlmap_findings = self._run_tool(
                    "sqlmap",
                    ["-u", target, "--json-output", sqlmap_out],
                    timeout=TOOL_TIMEOUT_LONG,
                )
                all_findings.extend(sqlmap_findings)
            except Exception as e:
                logger.warning(f"[API] sqlmap failed for {target}: {e}")

        logger.info(f"[API] Total findings: {len(all_findings)}")
        return self._tag_findings(all_findings)


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
        auth_config: dict | None = None,
    ):
        # Deep copy happens inside each agent's __init__
        self.agents = [
            cls(
                llm_service=llm_service,
                tool_runner=tool_runner,
                recon_context=recon_context,
                engagement_id=engagement_id,
                decision_repo=decision_repo,
                auth_config=auth_config,
            )
            for cls in self.SPECIALIST_CLASSES
        ]
        self.auth_config = auth_config or {}

    def run(self, timeout: int = 1800) -> list[dict]:
        """Run all active specialists in parallel and merge findings.

        Args:
            timeout: Maximum wall-clock time in seconds (default 30 min)

        Returns:
            Deduplicated list of finding dicts
        """
        active = [a for a in self.agents if a.should_activate()]
        slog = ScanLogger("swarm", engagement_id=active[0].engagement_id if active else "")

        if not active:
            logger.info("Swarm: no specialists activated")
            slog.info("No specialists activated")
            return []

        slog.swarm_activate([a.DOMAIN for a in active])
        logger.info(
            "Swarm: activating %d specialist(s): %s",
            len(active),
            [a.DOMAIN for a in active],
        )

        emit_swarm_agent_started(active[0].engagement_id, "swarm_orchestrator")

        all_findings: list[dict] = []
        completed: set[str] = set()
        futures_map: dict[concurrent.futures.Future, str] = {}

        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            for agent in active:
                future = pool.submit(agent.run)
                futures_map[future] = agent.DOMAIN

            # Wait with a hard wall-clock timeout — agents that exceed it
            # are cancelled (note: cancel() only stops futures that haven't
            # started; running threads continue but their results are ignored).
            # ALL_COMPLETE ensures one agent's failure doesn't cancel others.
            done, not_done = concurrent.futures.wait(
                futures_map, timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETE,
            )
            for future in not_done:
                domain = futures_map.get(future, "?")
                future.cancel()
                logger.warning("Swarm: agent %s timed out after %ds — cancelled", domain, timeout)
                emit_swarm_agent_complete(
                    active[0].engagement_id, domain, findings_count=0,
                )

            for future in done:
                domain = futures_map.get(future, "?")
                try:
                    findings = future.result(timeout=30)
                    logger.info("Specialist %s returned %d findings", domain, len(findings))
                    emit_swarm_agent_complete(
                        active[0].engagement_id, domain, findings_count=len(findings),
                    )
                    all_findings.extend(findings)
                    completed.add(domain)
                except Exception as e:
                    logger.error("Specialist %s failed: %s", domain, e)
                    emit_swarm_agent_complete(
                        active[0].engagement_id, domain, findings_count=0,
                    )

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

        return deduped

    @staticmethod
    def _deduplicate(findings: list[dict]) -> list[dict]:
        """Deduplicate using evidence-merged merge.

        For findings with same type+endpoint+payload fingerprint,
        evidence from both findings is merged (not discarded).
        The higher-confidence finding's metadata survives as the base.

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

            # Merge evidence from both findings
            existing_ev = existing.get("evidence", {}) or {}
            new_ev = f.get("evidence", {}) or {}
            if isinstance(existing_ev, dict) and isinstance(new_ev, dict):
                merged_evidence = {**existing_ev, **new_ev}
            else:
                merged_evidence = new_ev if len(str(new_ev)) > len(str(existing_ev)) else existing_ev

            if new_conf > existing_conf:
                seen[fp] = f
                seen[fp]["evidence"] = merged_evidence
            elif new_conf == existing_conf:
                existing_evidence_len = len(str(existing_ev))
                new_evidence_len = len(str(new_ev))
                if new_evidence_len > existing_evidence_len:
                    seen[fp] = f
                    seen[fp]["evidence"] = merged_evidence
                else:
                    existing["evidence"] = merged_evidence

        return list(seen.values())
