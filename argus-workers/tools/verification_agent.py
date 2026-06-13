"""
Verification Agent — attempts to reproduce and verify security findings.

Receives findings from scanners, attempts reproduction, collects evidence,
scores confidence, and promotes or rejects findings.
"""

from __future__ import annotations

import logging
from typing import Any

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class VerificationAgent(AbstractTool):
    """Verifies findings by attempting reproduction and collecting evidence."""

    tool_name: str = "verification_agent"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        input_findings = getattr(ctx, "_verification_input", None)
        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)
        # Lazy imports for verification subpackage (L5)
        from .verification.confidence_scorer import score_confidence
        from .verification.evidence_collector import VerificationEvidenceCollector
        from .verification.finding_promoter import promote_finding
        from .verification.reproduction_engine import ReproductionEngine

        engine = ReproductionEngine()
        collector = VerificationEvidenceCollector()

        verified_findings = []
        confirmed = 0
        rejected = 0
        pending = 0

        for finding in input_findings:
            reproduction = engine.reproduce(finding, ctx.target)
            evidence = collector.collect(finding, reproduction)
            confidence = score_confidence(finding, reproduction, evidence)
            promoted = promote_finding(finding, confidence, reproduction.get("reproduced", False))

            # Normalize promoted findings to standard FindingBuilder format (M3)
            normalized = {
                "type": promoted.get("type", finding.get("type", "UNKNOWN")),
                "severity": promoted.get("severity", finding.get("severity", "INFO")),
                "endpoint": promoted.get("endpoint", finding.get("endpoint", ctx.target)),
                "evidence": promoted.get("evidence", evidence),
                "confidence": promoted.get("confidence", confidence),
                "source_tool": self.tool_name,
                "verification_status": promoted.get("status", "PENDING"),
                "verification_reason": promoted.get("reason", ""),
            }
            verified_findings.append(normalized)

            status = promoted.get("status", "PENDING")
            if status == "CONFIRMED":
                confirmed += 1
            elif status == "REJECTED":
                rejected += 1
            else:
                pending += 1

        result.findings = verified_findings
        result.findings_count = len(verified_findings)

        builder.info(
            "VERIFICATION_SUMMARY",
            ctx.target,
            {
                "total": len(input_findings),
                "confirmed": confirmed,
                "rejected": rejected,
                "pending": pending,
            },
        )
        result.findings.extend(builder.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
