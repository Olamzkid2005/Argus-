"""
Intelligence Engine - THE ONLY decision-maker
Analyzes findings and generates recommended actions

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 20.6, 21.1, 21.2, 18.1, 18.2, 18.3, 18.4
"""
import json
import logging
import os
import re
import time as _time
from collections import defaultdict
from urllib.parse import urlparse

import httpx

from tracing import ExecutionSpan, StructuredLogger, get_trace_id

logger = logging.getLogger(__name__)


class IntelligenceEngine:
    """
    Decision-making core that analyzes findings and generates actions.
    Uses ONLY frozen snapshot data, never live DB reads.
    """

    def __init__(self, connection_string: str = None):
        """
        Initialize Intelligence Engine.

        Args:
            connection_string: Database connection string for tracing
        """
        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

    QUALITY_ORDER = {"confirmed": 0, "probable": 1, "candidate": 2}

    @staticmethod
    def _sort_findings_by_signal_quality(findings: list[dict]) -> list[dict]:
        """Sort findings so confirmed → probable → candidate.

        When time is short, confirmed findings (nuclei CVE, web_scanner verified)
        get analysis budget first. Noisy candidates (nikto, ffuf) processed last.
        """
        if not findings or not isinstance(findings, list):
            return findings or []

        from tool_definitions import TOOLS, SignalQuality

        def priority(f: dict) -> int:
            tool_name = f.get("source_tool", "")
            tool_def = TOOLS.get(tool_name)
            quality = tool_def.signal_quality if tool_def else SignalQuality.CANDIDATE
            return IntelligenceEngine.QUALITY_ORDER.get(quality, 2)

        return sorted(findings, key=priority)

    def evaluate(self, snapshot: dict, org_id: str | None = None) -> dict:
        """
        Evaluate snapshot and return analysis for the agent loop.
        Uses ONLY frozen snapshot data, never live DB reads.

        Args:
            snapshot: Immutable snapshot containing:
                - findings: List of findings
                - attack_graph: Attack graph data
                - loop_budget: Current loop budget status
                - engagement_state: Current engagement state
            org_id: Optional org ID for loading learned tool FP rates

        Returns:
            Dictionary with:
                - scored_findings: Findings with updated confidence scores
                - analysis: Analysis dict from analyze_state()
                - reasoning: Explanation of decisions
        """
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("intelligence_engine")
        slog.phase_header("INTELLIGENCE EVALUATION")
        start = _time.time()

        findings = snapshot.get("findings", [])
        slog.info(f"Evaluating {len(findings)} findings")

        # Sort findings by signal quality so confirmed findings get analysis
        # budget first — candidates get processed last when time is short.
        findings = self._sort_findings_by_signal_quality(findings)

        # Execute with span tracing
        with self.span_recorder.span(
            ExecutionSpan.SPAN_INTELLIGENCE_EVALUATION,
            {"findings_count": len(findings)}
        ):
            # Assign confidence scores (with learned FP rates if org_id provided)
            scored_findings = self.assign_confidence_scores(findings, org_id=org_id)

            # Enrich findings with threat intelligence (CVE data, EPSS scores,
            # threat feed hits, FP assessment) before analysis so
            # high-exploitability CVEs can influence risk assessment.
            enriched_findings = self.enrich_findings_with_threat_intel(scored_findings)

            # Build and persist attack graph for snapshot consumption
            self._build_and_persist_attack_graph(enriched_findings, snapshot)

            # Use analyze_state() for agent-loop consumption.
            # Pass enriched_findings to avoid redundant scoring/enrichment.
            analysis = self.analyze_state(snapshot, enriched_findings=enriched_findings)
            reasoning = self._generate_reasoning(enriched_findings, [])

            duration_ms = int((_time.time() - start) * 1000)
            slog.info(
                f"Evaluation complete: "
                f"{len(enriched_findings)} enriched findings, "
                f"risk={analysis.get('risk_level', 'unknown')} "
                f"({duration_ms}ms)"
            )
            self.logger.log_intelligence_decision(
                actions=[],
                findings_analyzed=len(findings),
                reasoning=reasoning,
            )
            return {
                "scored_findings": enriched_findings,
                "analysis": analysis,
                "reasoning": reasoning,
                "trace_id": get_trace_id(),
            }

    def assign_confidence_scores(
        self,
        findings: list[dict],
        org_id: str | None = None,
    ) -> list[dict]:
        """
        Calculate confidence using formula:
        confidence = (tool_agreement × evidence_strength) / (1 + fp_likelihood)

        When org_id is provided, loads per-tool FP rates from tool_accuracy table.
        Uses a weighted blend: 60% historical + 40% current scanner metadata.
        Falls back to 0.2 when no data exists.

        Args:
            findings: List of findings
            org_id: Optional org ID for loading learned tool FP rates

        Returns:
            Findings with updated confidence scores
        """
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("intelligence_engine")
        slog.info(f"Assigning confidence scores to {len(findings)} findings")

        # Load learned FP rates for this org (if available)
        tool_fp_rates: dict[str, float] = {}
        if org_id:
            try:
                from database.repositories.tool_accuracy_repository import (
                    ToolAccuracyRepository,
                )
                repo = ToolAccuracyRepository(self.connection_string)
                tool_fp_rates = repo.load_fp_rates(org_id)
                slog.info(f"Loaded FP rates for {len(tool_fp_rates)} tools")
            except Exception as e:
                logger.warning(
                    "Could not load tool_accuracy for org %s: %s", org_id, e,
                )
                # Fallback: empty dict — every lookup falls through to default 0.2

        # Group findings by normalized vulnerability family for tool agreement
        finding_groups = self._group_findings_for_agreement(findings)
        slog.info(f"Grouped into {len(finding_groups)} vulnerability families")

        scored_findings = []

        for group in finding_groups.values():
            # Calculate tool agreement once per group
            tool_agreement = self._calculate_tool_agreement(group)

            for finding in group:
                # Get evidence strength
                evidence_strength = self._get_evidence_strength(finding)

                # --- Learned FP rate resolution ---
                source_tool = finding.get("source_tool", "")
                learned_fp = tool_fp_rates.get(source_tool)   # from tool_accuracy DB
                stored_fp = finding.get("fp_likelihood")

                # ── Robust type coercion and validation ──
                # Validate learned_fp is a numeric float in [0.0, 1.0]
                _learned_fp_valid: float | None = None
                if learned_fp is not None:
                    try:
                        _val = float(learned_fp)
                        if 0.0 <= _val <= 1.0:
                            _learned_fp_valid = _val
                        else:
                            logger.debug("learned_fp out of range for tool %s: %s", source_tool, _val)
                    except (ValueError, TypeError):
                        logger.debug("learned_fp non-numeric for tool %s: %s", source_tool, learned_fp)

                # Validate stored_fp is a numeric float in [0.0, 1.0]
                _stored_fp_valid: float | None = None
                if stored_fp is not None and not isinstance(stored_fp, bool):
                    try:
                        _val = float(stored_fp)
                        if 0.0 <= _val <= 1.0:
                            _stored_fp_valid = _val
                        else:
                            logger.debug("stored_fp out of range: %s", _val)
                    except (ValueError, TypeError):
                        logger.debug("stored_fp non-numeric: %s (type=%s)", stored_fp, type(stored_fp).__name__)

                # Weighted blend: 60% historical (DB) + 40% scanner metadata
                if _learned_fp_valid is not None and _stored_fp_valid is not None:
                    fp_likelihood = 0.6 * _learned_fp_valid + 0.4 * _stored_fp_valid
                elif _learned_fp_valid is not None:
                    fp_likelihood = _learned_fp_valid
                elif _stored_fp_valid is not None:
                    fp_likelihood = _stored_fp_valid
                else:
                    fp_likelihood = 0.2

                # Clamp fp_likelihood to prevent division instability
                fp_likelihood = max(0.001, min(1.0, fp_likelihood))

                # Calculate confidence using shared formula
                from models.confidence_scorer import ConfidenceScorer
                confidence = ConfidenceScorer.compute(tool_agreement, evidence_strength, fp_likelihood)

                # Bug-Reaper integration: cap confidence at 0.7 for unvalidated findings.
                # Two paths:
                # 1. Custom rules with requires_validation and source="bugbounty" — remain
                #    "Theoretical" until validated.
                # 2. All findings tagged by the orchestrator (bugbounty_source=True) when
                #    bug bounty mode is active — these lack explicit validation metadata
                #    and should be treated conservatively.
                if finding.get("bugbounty_source") or finding.get("source") == "bugbounty" or (
                    finding.get("requires_validation") and finding.get("source") == "bugbounty"
                ):
                    confidence = min(confidence, 0.70)

                # Update finding
                scored_finding = finding.copy()
                scored_finding["confidence"] = confidence
                scored_finding["tool_agreement_level"] = self._get_agreement_level(len(group))
                # Tag fp_rate source for auditability
                scored_finding["fp_rate_source"] = (
                    "learned" if _learned_fp_valid is not None
                    else "scanner_metadata" if _stored_fp_valid is not None
                    else "default_0.2"
                )

                # Propagate Bug-Reaper validation flag
                if finding.get("requires_validation"):
                    scored_finding["needs_validation"] = True

                scored_findings.append(scored_finding)

        return scored_findings

    def _calculate_tool_agreement(self, findings_group: list[dict]) -> float:
        """
        Calculate tool agreement score

        Args:
            findings_group: Group of findings for same endpoint/type

        Returns:
            Tool agreement score
        """
        num_tools = len({f.get("source_tool") or "" for f in findings_group})

        if num_tools >= 3:
            return 1.0
        elif num_tools == 2:
            return 0.85
        else:
            return 0.7

    def _get_agreement_level(self, num_tools: int) -> str:
        """Get agreement level string"""
        if num_tools >= 3:
            return "high"
        elif num_tools == 2:
            return "medium"
        else:
            return "single_tool"

    def _get_evidence_strength(self, finding: dict) -> float:
        """
        Get evidence strength score

        Args:
            finding: Finding dictionary

        Returns:
            Evidence strength score (0.6-1.0)
        """
        evidence_strength = finding.get("evidence_strength")
        if evidence_strength is None or evidence_strength == "":
            evidence_strength = "MINIMAL"
        evidence_strength = str(evidence_strength).upper()

        scores = {
            "VERIFIED": 1.0,
            "REQUEST_RESPONSE": 0.9,
            "PAYLOAD": 0.8,
            "MINIMAL": 0.6,
        }

        return scores.get(evidence_strength, 0.6)

    def _group_findings_for_agreement(self, findings: list[dict]) -> dict:
        """Group findings that represent the same vulnerability family for tool agreement."""
        type_families = {
            "XSS": ["XSS", "REFLECTED_XSS", "STORED_XSS", "DOM_XSS", "BLIND_XSS", "CROSS_SITE_SCRIPTING"],
            "SQLI": ["SQL_INJECTION", "BLIND_SQLI", "TIME_BASED_SQLI", "TIME_BASED_SQL_INJECTION", "ERROR_SQLI"],
            "RCE": ["RCE", "COMMAND_INJECTION", "SSTI"],
            "LFI": ["LFI", "PATH_TRAVERSAL", "DIRECTORY_TRAVERSAL"],
            "SSRF": ["SSRF", "OPEN_REDIRECT"],
            "INFO": ["INFO", "INFORMATION_DISCLOSURE", "DIRECTORY_LISTING"],
        }

        groups = {}
        for finding in findings:
            endpoint = finding.get("endpoint") or ""
            finding_type = (finding.get("type") or "").upper()

            # Skip empty-type findings to prevent inflated tool agreement
            if not finding_type:
                continue

            parsed = urlparse(endpoint)
            normalized_endpoint = f"{parsed.netloc}{parsed.path}" if endpoint else ""

            # If endpoint is empty, derive a more specific key from evidence
            # to prevent unrelated findings (e.g., different packages) from
            # sharing the same group key and inflating tool agreement.
            if not normalized_endpoint:
                evidence = finding.get("evidence") or {}
                if isinstance(evidence, dict):
                    pkg = evidence.get("package") or evidence.get("name") or evidence.get("module") or evidence.get("cve_id")
                    if pkg:
                        normalized_endpoint = f"_pkg_{pkg}"
                    else:
                        normalized_endpoint = f"_no_endpoint_{finding_type}"
                else:
                    normalized_endpoint = f"_no_endpoint_{finding_type}"

            normalized_type = finding_type
            for family, members in type_families.items():
                if normalized_type in members:
                    normalized_type = family
                    break

            key = f"{normalized_type}:{normalized_endpoint}"
            if key not in groups:
                groups[key] = []
            groups[key].append(finding)

        return groups

    def _build_and_persist_attack_graph(self, enriched_findings: list[dict], context: dict) -> tuple[dict, Any]:
        """
        Build AttackGraph from scored findings and persist to database.

        Converts finding dicts to VulnerabilityFinding objects, builds the
        attack graph, and persists it to the attack_paths table via
        AttackGraphRepository so SnapshotManager can read it.

        When ATTACK_GRAPH_V2 is enabled and context contains an
        EngagementState reference (``_engagement_state``), attaches the
        AttackGraph instance so build_observation() includes live paths.

        Args:
            scored_findings: Findings with confidence scores
            context: Snapshot context (must include engagement_id)

        Returns:
            Tuple of (snapshot_dict, graph_instance)
        """
        from attack_graph import AttackGraph
        from models.finding import VulnerabilityFinding, Severity

        engagement_id = context.get("engagement_id", "") or ""
        if not engagement_id:
            logger.warning("No engagement_id in context, skipping attack graph build")
            return {"paths": []}, None

        graph = AttackGraph(engagement_id)

        for finding_dict in enriched_findings:
            try:
                severity_str = finding_dict.get("severity", "MEDIUM")
                if isinstance(severity_str, str):
                    try:
                        severity = Severity[severity_str.upper()]
                    except (KeyError, ValueError):
                        severity = Severity.MEDIUM
                else:
                    severity = Severity.MEDIUM

                evidence = finding_dict.get("evidence", {})
                if isinstance(evidence, str):
                    import json
                    try:
                        evidence = json.loads(evidence)
                    except (json.JSONDecodeError, TypeError):
                        evidence = {"raw": evidence}

                finding = VulnerabilityFinding(
                    type=finding_dict.get("type", "UNKNOWN"),
                    severity=severity,
                    confidence=finding_dict.get("confidence", 0.5),
                    endpoint=finding_dict.get("endpoint", "unknown"),
                    evidence=evidence,
                    source_tool=finding_dict.get("source_tool", "unknown"),
                    cvss_score=finding_dict.get("cvss_score"),
                )
                graph.add_finding(finding)
            except Exception as e:
                logger.warning(
                    "Could not add finding to attack graph: %s", e,
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )
                continue

        # Persist to database so SnapshotManager can read it
        saved_count = 0
        try:
            from attack_graph_db import AttackGraphRepository
            repo = AttackGraphRepository(self.connection_string)
            saved_count = repo.save_paths(engagement_id, graph)
            logger.info(
                "Persisted %d attack paths for engagement %s",
                saved_count, engagement_id,
            )
        except Exception as e:
            logger.warning("Could not persist attack graph: %s", e)

        snapshot_dict = graph.to_snapshot_dict()
        snapshot_dict["paths_saved"] = saved_count

        # Step 11: When ATTACK_GRAPH_V2 is enabled, attach the graph instance
        # to the state so build_observation() includes live attack paths.
        try:
            from feature_flags import is_enabled as _ff_enabled
            if _ff_enabled("ATTACK_GRAPH_V2", default=False):
                _state = context.get("_engagement_state")
                if _state is not None and hasattr(_state, "set_attack_graph_instance"):
                    try:
                        _state.set_attack_graph_instance(graph)
                        logger.debug(
                            "Attached AttackGraph instance to state for engagement %s",
                            engagement_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Could not attach AttackGraph to state: %s", e,
                        )
        except ImportError:
            logger.debug("feature_flags module not available — skipping AttackGraph attachment")

        return snapshot_dict, graph

    def analyze_state(self, state: Any, enriched_findings: list[dict] | None = None) -> dict:
        """
        Analyze engagement state and return analysis for the agent loop.

        When called from evaluate(), pass pre-enriched findings to avoid
        redundant scoring/threat-intel work. When called independently,
        enriched_findings can be None and the method does its own enrichment.

        Args:
            state: EngagementState or snapshot dict
            enriched_findings: Optional pre-enriched findings (from evaluate())

        Returns:
            Analysis dict with:
                - risk_level: Overall risk assessment
                - coverage_gaps: List of areas with insufficient coverage
                - high_value_targets: Endpoints warranting deeper inspection
                - weak_auth_signals: Authentication-related signals
                - threat_intel_summary: Threat intelligence overview
                - reasoning: Analysis reasoning text
        """
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("intelligence_engine")

        # If enriched_findings not provided, do our own scoring/enrichment
        if enriched_findings is None:
            findings = getattr(state, "findings", [])
            slog.info(f"Analyzing state: {len(findings)} findings")
            # Sort by signal quality
            findings = self._sort_findings_by_signal_quality(findings)
            # Assign confidence scores
            scored_findings = self.assign_confidence_scores(findings)
            # Enrich with threat intel
            enriched_findings = self.enrich_findings_with_threat_intel(scored_findings)
        else:
            slog.info(f"Analyzing state with {len(enriched_findings)} pre-enriched findings")

        # Build analysis
        coverage_gaps = []
        high_value_targets = []
        weak_auth_signals = []

        if self.detect_low_coverage(enriched_findings):
            coverage_gaps = self.suggest_new_targets(enriched_findings)

        if self.detect_high_value_targets(enriched_findings):
            high_value_targets = self.get_priority_endpoints(enriched_findings)

        if self.detect_weak_auth_signals(enriched_findings):
            weak_auth_signals = self.get_auth_endpoints(enriched_findings)

        risk_level = self._calculate_overall_risk(enriched_findings)

        return {
            "risk_level": risk_level,
            "coverage_gaps": coverage_gaps,
            "high_value_targets": high_value_targets,
            "weak_auth_signals": weak_auth_signals,
            "threat_intel_summary": self.get_threat_summary(enriched_findings),
            "reasoning": self._generate_reasoning(enriched_findings, []),
        }

    def detect_low_coverage(self, findings: list[dict]) -> bool:
        """
        Detect if coverage is insufficient

        Args:
            findings: List of findings

        Returns:
            True if low coverage detected
        """
        endpoints = {f.get("endpoint") for f in findings if f.get("endpoint")}

        if not endpoints:
            return False

        return len(endpoints) < 5

    def suggest_new_targets(self, findings: list[dict]) -> list[str]:
        """
        Suggest new targets for reconnaissance

        Args:
            findings: List of findings

        Returns:
            List of suggested targets
        """
        # Extract domains from existing findings
        domains = set()
        for finding in findings:
            endpoint = finding.get("endpoint", "")
            if "://" in endpoint:
                domain = endpoint.split("://")[1].split("/")[0]
                domains.add(domain)

        # Suggest common subdomains
        suggestions = []
        for domain in domains:
            suggestions.extend([
                f"https://api.{domain}",
                f"https://admin.{domain}",
                f"https://dev.{domain}",
            ])

        return suggestions[:5]  # Limit to 5 suggestions

    def detect_high_value_targets(self, findings: list[dict]) -> bool:
        """
        Detect high-value targets for deep scanning

        Args:
            findings: List of findings

        Returns:
            True if high-value targets found
        """
        # High-value if any CRITICAL or HIGH severity findings
        for finding in findings:
            severity = finding.get("severity", "INFO")
            if severity in ["CRITICAL", "HIGH"]:
                return True

        return False

    def get_priority_endpoints(self, findings: list[dict]) -> list[str]:
        """
        Get priority endpoints for deep scanning

        Args:
            findings: List of findings

        Returns:
            List of priority endpoints
        """
        priority_endpoints = []

        for finding in findings:
            severity = finding.get("severity", "INFO")
            if severity in ["CRITICAL", "HIGH"]:
                endpoint = finding.get("endpoint")
                if endpoint and endpoint not in priority_endpoints:
                    priority_endpoints.append(endpoint)

        return priority_endpoints[:10]  # Limit to top 10

    def detect_weak_auth_signals(self, findings: list[dict]) -> bool:
        """
        Detect weak authentication signals

        Args:
            findings: List of findings

        Returns:
            True if weak auth signals detected
        """
        auth_keywords = [
            "authentication",
            "authorization",
            "login",
            "auth",
            "session",
            "token",
            "jwt",
        ]

        for finding in findings:
            finding_type = finding.get("type", "").lower()
            endpoint = finding.get("endpoint", "").lower()

            # Check if finding relates to authentication
            for keyword in auth_keywords:
                if keyword in finding_type or keyword in endpoint:
                    return True

        return False

    def get_auth_endpoints(self, findings: list[dict]) -> list[str]:
        """
        Get authentication-related endpoints

        Args:
            findings: List of findings

        Returns:
            List of auth endpoints
        """
        auth_keywords = [
            "authentication",
            "authorization",
            "login",
            "auth",
            "session",
            "token",
            "jwt",
        ]

        auth_endpoints = []

        for finding in findings:
            endpoint = finding.get("endpoint", "").lower()

            for keyword in auth_keywords:
                if keyword in endpoint and endpoint not in auth_endpoints:
                    auth_endpoints.append(finding.get("endpoint"))
                    break

        return auth_endpoints[:10]  # Limit to top 10

    def _generate_reasoning(self, findings: list[dict], actions: list[dict]) -> str:
        """
        Generate reasoning explanation

        Args:
            findings: Scored findings
            actions: Generated actions

        Returns:
            Reasoning text
        """
        reasoning_parts = []

        reasoning_parts.append(f"Analyzed {len(findings)} findings.")

        # Count by severity
        severity_counts = defaultdict(int)
        for finding in findings:
            severity_counts[finding.get("severity", "INFO")] += 1

        reasoning_parts.append(
            f"Severity distribution: "
            f"Critical={severity_counts['CRITICAL']}, "
            f"High={severity_counts['HIGH']}, "
            f"Medium={severity_counts['MEDIUM']}, "
            f"Low={severity_counts['LOW']}, "
            f"Info={severity_counts['INFO']}"
        )

        reasoning_parts.append(f"Generated {len(actions)} recommended actions.")

        for action in actions:
            reasoning_parts.append(f"- {action['type']}: {action['description']}")

        return " ".join(reasoning_parts)

    # ── AI-Powered Threat Intelligence (Step 18) ──

    def enrich_findings_with_threat_intel(self, findings: list[dict]) -> list[dict]:
        """
        Enrich findings with CVE data, EPSS scores, and threat intelligence.

        Parallelizes CVE/EPSS lookups across findings to reduce total
        wall-clock time when many findings have CVE references.

        Args:
            findings: List of findings to enrich

        Returns:
            Enriched findings with threat intel metadata
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _enrich_one(finding: dict) -> dict:
            enriched_finding = finding.copy()
            threat_intel = {}

            # Extract potential CVE IDs from evidence or type
            cve_ids = self._extract_cve_ids(finding)
            if cve_ids:
                threat_intel["cve_ids"] = cve_ids
                nvd_data = self._fetch_nvd_cve_data(cve_ids)
                threat_intel["cve_details"] = nvd_data
                threat_intel["epss_scores"] = self._fetch_epss_scores(cve_ids)

            # Local-only lookups (fast, no I/O)
            threat_intel["threat_feed_hits"] = self._check_threat_feeds(finding)
            threat_intel["fp_assessment"] = self._detect_false_positive(finding)

            enriched_finding["threat_intel"] = threat_intel
            return enriched_finding

        with ThreadPoolExecutor(max_workers=min(len(findings) or 1, 10)) as pool:
            futures = [pool.submit(_enrich_one, f) for f in findings]
            enriched = [future.result() for future in as_completed(futures)]

        return enriched

    def _extract_cve_ids(self, finding: dict) -> list[str]:
        """
        Extract CVE IDs from finding evidence or description

        Args:
            finding: Finding dictionary

        Returns:
            List of CVE IDs
        """
        cve_ids = []

        # Check evidence for CVE references
        evidence = finding.get("evidence", {})
        evidence_str = json.dumps(evidence) if isinstance(evidence, dict) else str(evidence)

        # Also check type and any description fields
        text_to_search = f"{finding.get('type', '')} {evidence_str}"

        # CVE pattern matching
        cve_pattern = r'CVE-\d{4}-\d{4,}'
        matches = re.findall(cve_pattern, text_to_search, re.IGNORECASE)
        cve_ids.extend([m.upper() for m in matches])

        # Deduplicate
        return list(set(cve_ids))[:5]  # Limit to 5 CVEs

    def _fetch_nvd_cve_data(self, cve_ids: list[str]) -> dict[str, dict]:
        """
        Fetch CVE details from NVD (National Vulnerability Database) API

        Args:
            cve_ids: List of CVE IDs

        Returns:
            Dictionary mapping CVE ID to details
        """
        results = {}
        if not cve_ids:
            return results

        def _fetch_single(cve_id: str) -> tuple[str, dict | None]:
            try:
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(
                        f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={cve_id}",
                        headers={"User-Agent": "Argus-Platform/1.0"}
                    )

                    if response.status_code == 200:
                        data = response.json()
                        vulnerabilities = data.get("vulnerabilities", [])

                        if vulnerabilities:
                            vuln = vulnerabilities[0].get("cve", {})
                            metrics = vuln.get("metrics", {})
                            cvss_data = None

                            # Prefer CVSS v3.1, fallback to v3.0, then v2
                            if "cvssMetricV31" in metrics:
                                cvss_data = metrics["cvssMetricV31"][0].get("cvssData", {})
                            elif "cvssMetricV30" in metrics:
                                cvss_data = metrics["cvssMetricV30"][0].get("cvssData", {})
                            elif "cvssMetricV2" in metrics:
                                cvss_data = metrics["cvssMetricV2"][0].get("cvssData", {})

                            return cve_id, {
                                "description": vuln.get("descriptions", [{}])[0].get("value", ""),
                                "cvss_score": cvss_data.get("baseScore") if cvss_data else None,
                                "severity": cvss_data.get("baseSeverity") if cvss_data else None,
                                "published": vuln.get("published", ""),
                                "last_modified": vuln.get("lastModified", ""),
                                "references": [ref.get("url", "") for ref in vuln.get("references", [])[:3]],
                            }
            except Exception as e:
                logger.warning(f"Failed to fetch NVD data for {cve_id}: {e}")
            return cve_id, None

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(len(cve_ids), 5)) as pool:
                futures = {pool.submit(_fetch_single, cve_id): cve_id for cve_id in cve_ids}
                for future in as_completed(futures):
                    cve_id, result = future.result()
                    if result:
                        results[cve_id] = result
        except Exception as e:
            logger.warning(f"NVD API parallel fetch failed: {e}")

        return results

    def _fetch_epss_scores(self, cve_ids: list[str]) -> dict[str, float]:
        """
        Fetch EPSS (Exploit Prediction Scoring System) scores

        Args:
            cve_ids: List of CVE IDs

        Returns:
            Dictionary mapping CVE ID to EPSS score (0.0-1.0)
        """
        scores = {}

        if not cve_ids:
            return scores

        try:
            with httpx.Client(timeout=10.0) as client:
                # EPSS API accepts comma-separated CVE IDs
                cve_param = ",".join(cve_ids)
                response = client.get(
                    f"https://api.first.org/data/v1/epss?cve={cve_param}",
                    headers={"User-Agent": "Argus-Platform/1.0"}
                )

                if response.status_code == 200:
                    data = response.json()
                    for item in data.get("data", []):
                        cve = item.get("cve", "").upper()
                        epss_score = item.get("epss")
                        if cve and epss_score is not None:
                            try:
                                scores[cve] = float(epss_score)
                            except (ValueError, TypeError):
                                continue
        except Exception as e:
            logger.warning(f"EPSS API fetch failed: {e}")

        return scores

    def _check_threat_feeds(self, finding: dict) -> list[dict]:
        """
        Check basic threat intelligence feeds for related indicators

        Args:
            finding: Finding dictionary

        Returns:
            List of threat feed hits
        """
        hits = []
        finding_type = finding.get("type", "").upper()
        endpoint = finding.get("endpoint", "")

        # Map subtypes to canonical families so REFLECTED_XSS → XSS etc.
        _type_families = {
            "XSS": ["XSS", "REFLECTED_XSS", "STORED_XSS", "DOM_XSS", "BLIND_XSS", "CROSS_SITE_SCRIPTING"],
            "SQLI": ["SQL_INJECTION", "BLIND_SQLI", "TIME_BASED_SQLI", "TIME_BASED_SQL_INJECTION", "ERROR_SQLI"],
            "RCE": ["RCE", "COMMAND_INJECTION", "SSTI"],
            "LFI": ["LFI", "PATH_TRAVERSAL", "DIRECTORY_TRAVERSAL"],
            "SSRF": ["SSRF", "OPEN_REDIRECT"],
            "INFO": ["INFO", "INFORMATION_DISCLOSURE", "DIRECTORY_LISTING"],
        }
        _type_to_family = {}
        for family, subtypes in _type_families.items():
            for st in subtypes:
                _type_to_family[st] = family

        normalized_type = _type_to_family.get(finding_type, finding_type)

        threat_indicators = {
            "SQL_INJECTION": {"feed": "exploitdb", "risk": "high", "description": "SQL injection commonly exploited in the wild"},
            "COMMAND_INJECTION": {"feed": "exploitdb", "risk": "critical", "description": "Command injection frequently exploited"},
            "XSS": {"feed": "cisa_kev", "risk": "medium", "description": "XSS present in known vulnerability catalogs"},
            "BROKEN_ACCESS_CONTROL": {"feed": "owasp_top10", "risk": "high", "description": "Access control issues ranked #1 in OWASP Top 10"},
            "AUTH_FAILURE": {"feed": "cisa_kev", "risk": "high", "description": "Authentication failures frequently targeted"},
            "WEAK_TLS": {"feed": "cisa_kev", "risk": "medium", "description": "Weak TLS configurations in security advisories"},
        }

        matched_key = None
        if finding_type in threat_indicators:
            matched_key = finding_type
        elif normalized_type in threat_indicators:
            matched_key = normalized_type
        else:
            # Normalized type may be a family name (e.g. "SQLI") not in
            # threat_indicators directly — check if any family subtype matches.
            subtypes = _type_families.get(normalized_type, [])
            for st in subtypes:
                if st in threat_indicators:
                    matched_key = st
                    break
        if matched_key:
            indicator = threat_indicators[matched_key].copy()
            indicator["matched_type"] = finding_type
            indicator["endpoint"] = endpoint
            hits.append(indicator)

        return hits

    def _detect_false_positive(self, finding: dict) -> dict:
        """
        ML-based false positive detection using simple heuristics

        Uses a weighted scoring model based on:
        - Evidence quality (verified > payload > minimal)
        - Tool agreement (multi-tool confirmation)
        - Endpoint characteristics (common vs unusual targets)
        - Historical FP patterns (known noisy tools/findings)

        Args:
            finding: Finding dictionary

        Returns:
            FP assessment with score and verdict
        """
        scores = []
        reasons = []

        # 1. Evidence quality heuristic
        evidence = finding.get("evidence", {})
        evidence_str = json.dumps(evidence) if isinstance(evidence, dict) else str(evidence)
        evidence_len = len(evidence_str)

        if evidence_len > 500:
            scores.append(0.85)
            reasons.append("rich_evidence")
        elif evidence_len > 100:
            scores.append(0.70)
            reasons.append("moderate_evidence")
        else:
            scores.append(0.45)
            reasons.append("minimal_evidence")

        # 2. Tool agreement heuristic
        source_tool = finding.get("source_tool", "unknown")
        tool_agreement = finding.get("tool_agreement_level", "single_tool")

        if tool_agreement == "high":
            scores.append(0.90)
            reasons.append("multi_tool_confirmed")
        elif tool_agreement == "medium":
            scores.append(0.75)
            reasons.append("dual_tool_confirmed")
        else:
            scores.append(0.60)
            reasons.append("single_tool")

        # 3. Known noisy tools/finding types
        noisy_tools = {"whatweb", "gau", "waybackurls"}
        noisy_types = {"INFO_DISCLOSURE", "TECHNOLOGY_DETECTION"}

        if source_tool.lower() in noisy_tools or finding.get("type", "").upper() in noisy_types:
            scores.append(0.40)
            reasons.append("known_noisy_source")
        else:
            scores.append(0.80)
            reasons.append("reliable_source")

        # 4. Endpoint characteristics
        endpoint = finding.get("endpoint", "")
        if endpoint.endswith((".js", ".css", ".png", ".jpg", ".gif")):
            scores.append(0.35)
            reasons.append("static_asset_endpoint")
        elif "/api/" in endpoint.lower() or "/admin/" in endpoint.lower():
            scores.append(0.85)
            reasons.append("high_value_endpoint")
        else:
            scores.append(0.65)
            reasons.append("standard_endpoint")

        # 5. Severity alignment check
        severity = finding.get("severity", "INFO")
        if severity == "CRITICAL" and evidence_len < 50:
            scores.append(0.30)
            reasons.append("severity_evidence_mismatch")
        else:
            scores.append(0.75)
            reasons.append("severity_aligned")

        # Calculate overall confidence (not FP likelihood)
        # Higher score = more likely to be TRUE positive
        avg_score = sum(scores) / len(scores) if scores else 0.5

        # Determine verdict
        if avg_score >= 0.75:
            verdict = "true_positive"
            confidence = avg_score
        elif avg_score >= 0.50:
            verdict = "likely_true_positive"
            confidence = avg_score
        elif avg_score >= 0.30:
            verdict = "likely_false_positive"
            confidence = 1.0 - avg_score
        else:
            verdict = "false_positive"
            confidence = 1.0 - avg_score

        return {
            "verdict": verdict,
            "confidence": round(confidence, 3),
            "true_positive_score": round(avg_score, 3),
            "factors": reasons,
            "factor_scores": {reason: round(score, 3) for reason, score in zip(reasons, scores)},
        }

    def get_threat_summary(self, findings: list[dict]) -> dict:
        """
        Generate a threat intelligence summary for all findings

        Args:
            findings: List of enriched findings

        Returns:
            Threat summary dictionary
        """
        total_cves = 0
        high_epss_count = 0
        threat_feed_hits = 0
        fp_likely_count = 0

        for finding in findings:
            intel = finding.get("threat_intel", {})

            cve_details = intel.get("cve_details", {})
            total_cves += len(cve_details)

            epss_scores = intel.get("epss_scores", {})
            for score in epss_scores.values():
                if score > 0.5:
                    high_epss_count += 1

            threat_feed_hits += len(intel.get("threat_feed_hits", []))

            fp_assessment = intel.get("fp_assessment", {})
            if fp_assessment.get("verdict") in ["likely_false_positive", "false_positive"]:
                fp_likely_count += 1

        return {
            "total_findings": len(findings),
            "findings_with_cves": total_cves,
            "high_exploitability_count": high_epss_count,
            "threat_feed_hits": threat_feed_hits,
            "likely_false_positives": fp_likely_count,
            "risk_level": self._calculate_overall_risk(findings),
        }

    def _calculate_overall_risk(self, findings: list[dict]) -> str:
        """
        Calculate overall risk level based on findings and threat intel.

        Uses a weighted approach: CRITICAL/HIGH severity findings dominate,
        with EPSS acting as a tiebreaker / amplifier rather than overriding
        severity counts. This prevents low-severity findings with high EPSS
        scores from driving the risk level unreasonably high.

        Args:
            findings: List of enriched findings

        Returns:
            Risk level string (critical, high, medium, low)
        """
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")
        medium_count = sum(1 for f in findings if f.get("severity") == "MEDIUM")

        # Adjust for EPSS scores — only amplify when paired with relevant severity.
        # A MEDIUM+ finding with EPSS > 0.5 counts as a bonus high.
        high_epss_count = 0
        for f in findings:
            intel = f.get("threat_intel", {})
            epss = intel.get("epss_scores", {})
            if any(score > 0.5 for score in epss.values()):
                sev = f.get("severity", "INFO")
                if sev in ("CRITICAL", "HIGH"):
                    high_epss_count += 1  # amplifier for already-significant findings
                elif sev == "MEDIUM":
                    high_epss_count += 0.5  # partial amplifier

        effective_high = high_count + high_epss_count

        if critical_count >= 3:
            return "critical"
        elif critical_count >= 1 and effective_high >= 2:
            return "critical"
        elif critical_count >= 1:
            return "high"
        elif effective_high >= 3:
            return "critical" if high_epss_count >= 2 else "high"
        elif high_count >= 1:
            return "high"
        elif medium_count >= 3 or effective_high >= 1:
            return "medium"
        else:
            return "low"



