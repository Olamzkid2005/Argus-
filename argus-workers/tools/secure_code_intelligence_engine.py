"""
Secure Code Intelligence Engine — unified SAST/SCA/secret scanning.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class SecureCodeIntelligenceEngine(AbstractTool):
    """Unified code security analysis combining multiple scanners."""

    tool_name: str = "secure_code_intelligence_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        tool_runner = getattr(ctx, "_tool_runner", None)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        scanners = {
            "secrets": lambda: self._scan_secrets(ctx.target, tool_runner),
            "sast": lambda: self._scan_sast(ctx.target, tool_runner),
            "sca": lambda: self._scan_sca(ctx.target, tool_runner),
        }

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fn): name for name, fn in scanners.items()}
            for future in as_completed(futures):
                category = futures[future]
                try:
                    for finding in future.result():
                        builder.add(finding.get("type", f"CODE_{category.upper()}"), finding.get("severity", "MEDIUM"), finding.get("endpoint", ctx.target), finding.get("evidence", {}), confidence=finding.get("confidence", 0.7), category=category)
                except Exception as e:
                    logger.warning("Scanner %s failed: %s", category, e)

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _scan_secrets(self, target: str, tool_runner) -> list[dict]:
        if not tool_runner:
            return []
        try:
            result = tool_runner.run("gitleaks", ["detect", "--source", target, "--report-format", "json", "--no-banner"], timeout=300)
            if not result.status.is_ok:
                return []
            findings = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    findings.append({"type": "SECRET_EXPOSURE", "severity": "HIGH", "endpoint": data.get("File", target), "evidence": {"rule": data.get("RuleID", "")}, "confidence": 0.9})
                except json.JSONDecodeError:
                    pass
            return findings
        except Exception:
            return []

    def _scan_sast(self, target: str, tool_runner) -> list[dict]:
        if not tool_runner:
            return []
        try:
            result = tool_runner.run("semgrep", ["--json", "--config=auto", target], timeout=600)
            if not result.status.is_ok and result.exit_code != 1:
                return []
            findings = []
            try:
                data = json.loads(result.stdout)
                for r in data.get("results", []):
                    severity = r.get("extra", {}).get("severity", "WARNING").upper()
                    sev_map = {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}
                    findings.append({"type": "SASTFinding", "severity": sev_map.get(severity, "MEDIUM"), "endpoint": r.get("path", target), "evidence": {"rule": r.get("check_id", "")}, "confidence": 0.8})
            except json.JSONDecodeError:
                pass
            return findings
        except Exception:
            return []

    def _scan_sca(self, target: str, tool_runner) -> list[dict]:
        if not tool_runner:
            return []
        try:
            result = tool_runner.run("trivy", ["fs", "--format", "json", "--scanners", "vuln", target], timeout=600)
            if not result.status.is_ok:
                return []
            findings = []
            try:
                data = json.loads(result.stdout)
                for r in data.get("Results", []):
                    for vuln in r.get("Vulnerabilities", []):
                        severity = vuln.get("Severity", "UNKNOWN").upper()
                        if severity in ("CRITICAL", "HIGH", "MEDIUM"):
                            findings.append({"type": "DEPENDENCY_VULNERABILITY", "severity": severity, "endpoint": vuln.get("PkgName", target), "evidence": {"cve": vuln.get("VulnerabilityID", "")}, "confidence": 0.85})
            except json.JSONDecodeError:
                pass
            return findings
        except Exception:
            return []
