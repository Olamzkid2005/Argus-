"""
Intelligence Engine - THE ONLY decision-maker
Analyzes findings and generates recommended actions

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 20.6, 21.1, 21.2, 18.1, 18.2, 18.3, 18.4
"""
import asyncio
import json
import logging
import os
import re
from collections import defaultdict

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

    def evaluate(self, snapshot: dict) -> dict:
        """
        Evaluate snapshot and generate actions.
        Uses ONLY frozen snapshot data, never live DB reads.

        Args:
            snapshot: Immutable snapshot containing:
                - findings: List of findings
                - attack_graph: Attack graph data
                - loop_budget: Current loop budget status
                - engagement_state: Current engagement state

        Returns:
            Dictionary with:
                - scored_findings: Findings with updated confidence scores
                - actions: List of recommended actions
                - reasoning: Explanation of decisions
        """
        findings = snapshot.get("findings", [])

        # Execute with span tracing
        with self.span_recorder.span(
            ExecutionSpan.SPAN_INTELLIGENCE_EVALUATION,
            {"findings_count": len(findings)}
        ):
            # Assign confidence scores
            scored_findings = self.assign_confidence_scores(findings)

            # Generate actions based on intelligence
            actions = self.generate_actions(scored_findings, snapshot)

            # Generate reasoning
            reasoning = self._generate_reasoning(scored_findings, actions)

            # Log intelligence decision
            self.logger.log_intelligence_decision(
                actions=actions,
                findings_analyzed=len(findings),
                reasoning=reasoning
            )

            return {
                "scored_findings": scored_findings,
                "actions": actions,
                "reasoning": reasoning,
                "trace_id": get_trace_id(),
            }

    def assign_confidence_scores(self, findings: list[dict]) -> list[dict]:
        """
        Calculate confidence using formula:
        confidence = (tool_agreement × evidence_strength) / (1 + fp_likelihood)

        Args:
            findings: List of findings

        Returns:
            Findings with updated confidence scores
        """
        # Group findings by endpoint and type to detect tool agreement
        finding_groups = defaultdict(list)

        for finding in findings:
            key = (finding.get("endpoint"), finding.get("type"))
            finding_groups[key].append(finding)

        scored_findings = []

        for finding in findings:
            key = (finding.get("endpoint"), finding.get("type"))
            group = finding_groups[key]

            # Calculate tool agreement
            tool_agreement = self._calculate_tool_agreement(group)

            # Get evidence strength
            evidence_strength = self._get_evidence_strength(finding)

            # Get FP likelihood
            fp_likelihood = finding.get("fp_likelihood", 0.2)
            if fp_likelihood is None:
                fp_likelihood = 0.2
            try:
                fp_likelihood = float(fp_likelihood)
            except (TypeError, ValueError):
                fp_likelihood = 0.2

            # Calculate confidence
            confidence = (tool_agreement * evidence_strength) / (1 + fp_likelihood)
            confidence = max(0.0, min(1.0, confidence))

            # Update finding
            scored_finding = finding.copy()
            scored_finding["confidence"] = confidence
            scored_finding["tool_agreement_level"] = self._get_agreement_level(len(group))

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
        num_tools = len({f.get("source_tool") for f in findings_group})

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
        evidence_strength = finding.get("evidence_strength") or "MINIMAL"
        evidence_strength = str(evidence_strength).upper()

        scores = {
            "VERIFIED": 1.0,
            "REQUEST_RESPONSE": 0.9,
            "PAYLOAD": 0.8,
            "MINIMAL": 0.6,
        }

        return scores.get(evidence_strength, 0.6)

    def generate_actions(self, scored_findings: list[dict], context: dict) -> list[dict]:
        """
        Generate recommended actions based on intelligence

        Args:
            scored_findings: Findings with confidence scores
            context: Snapshot context

        Returns:
            List of recommended actions
        """
        actions = []

        # Pattern: Low coverage detected
        if self.detect_low_coverage(scored_findings):
            actions.append({
                "type": "recon_expand",
                "scope": self.suggest_new_targets(scored_findings),
                "reason": "low_coverage_detected",
                "description": "Insufficient endpoint coverage detected. Expanding reconnaissance to discover more attack surface.",
            })

        # Pattern: High-value targets found
        if self.detect_high_value_targets(scored_findings):
            actions.append({
                "type": "deep_scan",
                "targets": self.get_priority_endpoints(scored_findings),
                "reason": "high_value_targets_identified",
                "description": "High-value targets with potential vulnerabilities identified. Performing deep scan.",
            })

        # Pattern: Weak authentication signals
        if self.detect_weak_auth_signals(scored_findings):
            # Extract budget from context for auth_focused_scan
            loop_budget = context.get("loop_budget", {})
            budget = {
                "max_cycles": loop_budget.get("max_cycles", 5),
                "max_depth": loop_budget.get("max_depth", 3),
            }
            actions.append({
                "type": "auth_focused_scan",
                "endpoints": self.get_auth_endpoints(scored_findings),
                "budget": budget,
                "reason": "weak_auth_signals",
                "description": "Weak authentication signals detected. Focusing on authentication mechanisms.",
            })

        return actions

    def detect_low_coverage(self, findings: list[dict]) -> bool:
        """
        Detect if coverage is insufficient

        Args:
            findings: List of findings

        Returns:
            True if low coverage detected
        """
        # Count unique endpoints
        endpoints = {f.get("endpoint") for f in findings}

        # Low coverage if fewer than 5 unique endpoints
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

        Args:
            findings: List of findings to enrich

        Returns:
            Enriched findings with threat intel metadata
        """
        enriched = []

        for finding in findings:
            enriched_finding = finding.copy()
            threat_intel = {}

            # Extract potential CVE IDs from evidence or type
            cve_ids = self._extract_cve_ids(finding)
            if cve_ids:
                threat_intel["cve_ids"] = cve_ids
                # Fetch CVE details from NVD
                threat_intel["cve_details"] = asyncio.run(self._fetch_nvd_cve_data_async(cve_ids))

            # Get EPSS scores for exploitability prediction
            if cve_ids:
                threat_intel["epss_scores"] = self._fetch_epss_scores(cve_ids)

            # Check threat intelligence feeds
            threat_intel["threat_feed_hits"] = self._check_threat_feeds(finding)

            # Run false positive detection
            fp_result = self._detect_false_positive(finding)
            threat_intel["fp_assessment"] = fp_result

            enriched_finding["threat_intel"] = threat_intel
            enriched.append(enriched_finding)

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

        try:
            with httpx.Client(timeout=10.0) as client:
                for cve_id in cve_ids:
                    try:
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

                                results[cve_id] = {
                                    "description": vuln.get("descriptions", [{}])[0].get("value", ""),
                                    "cvss_score": cvss_data.get("baseScore") if cvss_data else None,
                                    "severity": cvss_data.get("baseSeverity") if cvss_data else None,
                                    "published": vuln.get("published", ""),
                                    "last_modified": vuln.get("lastModified", ""),
                                    "references": [ref.get("url", "") for ref in vuln.get("references", [])[:3]],
                                }
                    except Exception as e:
                        logger.warning(f"Failed to fetch NVD data for {cve_id}: {e}")
                        continue
        except Exception as e:
            logger.warning(f"NVD API client failed: {e}")

        return results

    async def _fetch_nvd_cve_data_async(self, cve_ids: list[str]) -> dict[str, dict]:
        """Fetch NVD data for multiple CVEs concurrently using async HTTP.

        Args:
            cve_ids: List of CVE IDs

        Returns:
            Dictionary mapping CVE ID to details
        """
        results = {}
        if not cve_ids:
            return results
        try:
            sem = asyncio.Semaphore(5)
            async with httpx.AsyncClient(timeout=10.0) as client:
                async def fetch_one(cve_id: str) -> tuple[str, dict | None]:
                    async with sem:
                        try:
                            response = await client.get(
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
                            return cve_id, None
                        except Exception as e:
                            logger.warning(f"Failed to fetch NVD data for {cve_id}: {e}")
                            return cve_id, None

                tasks = [fetch_one(cve_id) for cve_id in cve_ids]
                for cve_id, data in await asyncio.gather(*tasks):
                    if data:
                        results[cve_id] = data
        except Exception as e:
            logger.warning(f"NVD async client failed: {e}")
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

        # Simple keyword-based threat feed simulation
        # In production, this would query MISP, AlienVault OTX, etc.
        threat_indicators = {
            "SQL_INJECTION": {"feed": "exploitdb", "risk": "high", "description": "SQL injection commonly exploited in the wild"},
            "COMMAND_INJECTION": {"feed": "exploitdb", "risk": "critical", "description": "Command injection frequently exploited"},
            "XSS": {"feed": "cisa_kev", "risk": "medium", "description": "XSS present in known vulnerability catalogs"},
            "BROKEN_ACCESS_CONTROL": {"feed": "owasp_top10", "risk": "high", "description": "Access control issues ranked #1 in OWASP Top 10"},
            "AUTH_FAILURE": {"feed": "cisa_kev", "risk": "high", "description": "Authentication failures frequently targeted"},
            "WEAK_TLS": {"feed": "cisa_kev", "risk": "medium", "description": "Weak TLS configurations in security advisories"},
        }

        if finding_type in threat_indicators:
            indicator = threat_indicators[finding_type].copy()
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
            "factor_scores": {reason: round(score, 3) for reason, score in zip(reasons, scores, strict=False)},
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
        Calculate overall risk level based on findings and threat intel

        Args:
            findings: List of enriched findings

        Returns:
            Risk level string (critical, high, medium, low)
        """
        critical_count = sum(1 for f in findings if f.get("severity") == "CRITICAL")
        high_count = sum(1 for f in findings if f.get("severity") == "HIGH")

        # Adjust for EPSS scores
        high_epss_findings = 0
        for f in findings:
            intel = f.get("threat_intel", {})
            epss = intel.get("epss_scores", {})
            if any(score > 0.5 for score in epss.values()):
                high_epss_findings += 1

        if critical_count >= 3 or high_epss_findings >= 3:
            return "critical"
        elif critical_count >= 1 or high_count >= 3 or high_epss_findings >= 1:
            return "high"
        elif high_count >= 1:
            return "medium"
        else:
            return "low"
