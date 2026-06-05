"""
Executive Report Generator — generates professional security reports.

Combines findings aggregation, executive summary, attack path visualization,
and multi-format rendering (PDF, Markdown, HTML).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


class ExecutiveReportGenerator(AbstractTool):
    """Generates executive security assessment reports."""

    tool_name: str = "executive_report_generator"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        input_findings = getattr(ctx, "_report_input", None)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        report = self._generate_report(input_findings, ctx.target, ctx.engagement_id)

        builder.info(
            "REPORT_GENERATED",
            ctx.target,
            {
                "format": "markdown",
                "finding_count": len(input_findings),
                "severity_breakdown": report.get("severity_breakdown", {}),
            },
        )

        result.findings = [report] + builder.findings
        result.findings_count = len(result.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _generate_report(self, findings: list[dict], target: str, engagement_id: str) -> dict:
        """Generate a complete executive report."""
        severity_breakdown = self._count_by_severity(findings)
        top_findings = self._get_top_findings(findings, 10)

        report = {
            "report_type": "executive_security_report",
            "target": target,
            "engagement_id": engagement_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "executive_summary": self._generate_executive_summary(findings, target, severity_breakdown),
            "severity_breakdown": severity_breakdown,
            "finding_count": len(findings),
            "top_findings": top_findings,
            "remediation": self._generate_remediation(findings),
            "markdown": self._render_markdown(findings, target, severity_breakdown, top_findings),
        }

        return report

    def _count_by_severity(self, findings: list[dict]) -> dict:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for f in findings:
            sev = (f.get("severity") or "INFO").upper()
            if sev in counts:
                counts[sev] += 1
        return counts

    def _get_top_findings(self, findings: list[dict], limit: int) -> list[dict]:
        sorted_findings = sorted(
            findings,
            key=lambda f: _SEVERITY_ORDER.get((f.get("severity") or "INFO").upper(), 4),
        )
        return sorted_findings[:limit]

    def _generate_executive_summary(
        self, findings: list[dict], target: str, severity_breakdown: dict
    ) -> str:
        total = len(findings)
        critical_high = severity_breakdown.get("CRITICAL", 0) + severity_breakdown.get("HIGH", 0)

        if critical_high > 0:
            risk_level = "HIGH"
            intro = f"The security assessment of {target} identified {total} findings, including {critical_high} critical/high severity issues that require immediate attention."
        elif severity_breakdown.get("MEDIUM", 0) > 0:
            risk_level = "MEDIUM"
            intro = f"The security assessment of {target} identified {total} findings. While no critical issues were found, there are medium-severity issues that should be addressed."
        else:
            risk_level = "LOW"
            intro = f"The security assessment of {target} identified {total} findings, all of low or informational severity."

        return f"Overall Risk Level: {risk_level}\n\n{intro}"

    def _generate_remediation(self, findings: list[dict]) -> list[dict]:
        remediation_map = {
            "SQL_INJECTION": "Use parameterized queries. Never concatenate user input into SQL statements.",
            "XSS": "Encode all output contextually. Implement Content-Security-Policy headers.",
            "CSRF": "Implement anti-CSRF tokens on all state-changing operations.",
            "COMMAND_INJECTION": "Never pass user input to system commands. Use parameterized APIs.",
            "SSRF": "Validate and whitelist URLs. Block access to internal IP ranges.",
            "MISCONFIGURATION": "Review security configuration against CIS benchmarks.",
            "WEAK_AUTHENTICATION": "Enforce strong password policies. Implement MFA.",
            "SECRET_EXPOSURE": "Remove secrets from code. Use environment variables or secret managers.",
        }

        remediation = []
        seen_types = set()
        for f in findings:
            ftype = (f.get("type") or "").upper().replace(" ", "_").replace("-", "_")
            if ftype in remediation_map and ftype not in seen_types:
                seen_types.add(ftype)
                remediation.append({
                    "finding_type": ftype,
                    "recommendation": remediation_map[ftype],
                })

        return remediation

    def _render_markdown(
        self, findings: list[dict], target: str, severity_breakdown: dict, top_findings: list[dict]
    ) -> str:
        lines = [
            f"# Security Assessment Report: {target}",
            "",
            f"**Date:** {datetime.now(UTC).strftime('%Y-%m-%d')}",
            f"**Total Findings:** {len(findings)}",
            "",
            "## Severity Breakdown",
            "",
        ]

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = severity_breakdown.get(sev, 0)
            if count > 0:
                lines.append(f"- **{sev}:** {count}")

        lines.extend([
            "",
            "## Top Findings",
            "",
        ])

        for i, f in enumerate(top_findings, 1):
            lines.append(f"{i}. **[{f.get('severity', 'INFO')}]** {f.get('type', f.get('title', 'Unknown'))} — {f.get('endpoint', 'N/A')}")

        lines.extend(["", "---", "*Report generated by Argus Security Assessment Platform*"])
        return "\n".join(lines)
