"""
Verification Agent — attempts to reproduce and verify security findings.

Receives findings from scanners, attempts reproduction, collects evidence,
scores confidence, and promotes or rejects findings.
"""

from __future__ import annotations

import logging

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
        from .verification.proof_status import evidence_with_proof
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
            # Promotion is decided on the proof itself (Stage 4.1): only a
            # completed reproduction with captured, non-error evidence may
            # confirm. Error artifacts and placeholder "requires a live HTTP
            # client" runs are not evidence, so they stay PENDING/INCONCLUSIVE.
            proof_artifacts = [
                artifact["path"]
                for artifact in evidence.get("artifacts", [])
                if artifact.get("type") != "error_log" and artifact.get("path")
            ]
            promoted = promote_finding(
                finding,
                confidence,
                reproduction.get("reproduced", False),
                # A placeholder strategy (no live replay yet) is *unsupported*,
                # which is a different claim from a failed attempt — and it can
                # never be promoted (Stage 4.1 item 3).
                supported=reproduction.get("supported", True),
                completed=not reproduction.get("error"),
                evidence_refs=proof_artifacts,
                error=reproduction.get("error"),
            )

            # Attribution comes from the finding itself when its producer knew
            # it, otherwise from the worker context (a claimed intent carries
            # the goal it serves).
            attribution = {
                key: finding[key]
                for key in ("goal_node_id", "proves_goal_ids")
                if finding.get(key)
            }
            if not attribution.get("goal_node_id"):
                ctx_goal = getattr(ctx, "goal_node_id", "")
                if ctx_goal:
                    attribution["goal_node_id"] = ctx_goal

            # Normalize promoted findings to standard FindingBuilder format (M3)
            normalized = {
                "type": promoted.get("type", finding.get("type", "UNKNOWN")),
                "severity": promoted.get("severity", finding.get("severity", "INFO")),
                "endpoint": promoted.get(
                    "endpoint", finding.get("endpoint", ctx.target)
                ),
                # The proof vocabulary and captured artifacts travel with the
                # finding so the stored row can prove a goal later on. If the
                # producer attributed the finding to a goal, that attribution is
                # kept too — it is what the save hook proves against.
                "evidence": evidence_with_proof(
                    promoted,
                    base={
                        **(promoted.get("evidence") or evidence or {}),
                        **attribution,
                    },
                ),
                "confidence": promoted.get("confidence", confidence),
                "source_tool": self.tool_name,
                "verification_status": promoted.get("status", "PENDING"),
                "verification_reason": promoted.get("reason", ""),
                # Carry the attribution at the top level as well, so any
                # persistence path can read it without unwrapping evidence.
                "goal_node_id": attribution.get("goal_node_id", ""),
                "proves_goal_ids": attribution.get("proves_goal_ids", []),
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
