"""
Evidence Intelligence Engine — screenshot capture, request storage,
artifact hashing, chain of custody, and evidence scoring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class EvidenceIntelligenceEngine(AbstractTool):
    """Collects, hashes, and scores evidence for findings."""

    tool_name: str = "evidence_intelligence_engine"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        input_findings = getattr(ctx, "_evidence_input", None)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        if not input_findings or not isinstance(input_findings, list):
            result.status = ToolStatus.SUCCESS_EMPTY
            result.mark_finished()
            return result

        enriched = []
        for finding in input_findings:
            evidence_package = self._build_evidence_package(finding, ctx.target)
            enriched_finding = {**finding, "evidence_package": evidence_package}
            enriched.append(enriched_finding)

        result.findings = enriched
        result.findings_count = len(enriched)

        builder.info(
            "EVIDENCE_SUMMARY",
            ctx.target,
            {
                "findings_enriched": len(enriched),
                "total_artifacts": sum(
                    len(f.get("evidence_package", {}).get("artifacts", []))
                    for f in enriched
                ),
            },
        )
        result.findings.extend(builder.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _build_evidence_package(self, finding: dict, target: str) -> dict:
        """Build an evidence package for a single finding."""
        artifacts = []
        evidence = finding.get("evidence", {})

        if evidence:
            content = json.dumps(evidence, indent=2, sort_keys=True)
            artifact_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            artifacts.append(
                {
                    "type": "evidence_data",
                    "hash": artifact_hash,
                    "size_bytes": len(content),
                }
            )

        request_data = finding.get("request")
        if request_data:
            content = (
                request_data
                if isinstance(request_data, str)
                else json.dumps(request_data)
            )
            artifact_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            artifacts.append(
                {
                    "type": "http_request",
                    "hash": artifact_hash,
                    "size_bytes": len(content),
                }
            )

        response_data = finding.get("response")
        if response_data:
            content = (
                response_data
                if isinstance(response_data, str)
                else json.dumps(response_data)
            )
            artifact_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            artifacts.append(
                {
                    "type": "http_response",
                    "hash": artifact_hash,
                    "size_bytes": len(content),
                }
            )

        package_hash = hashlib.sha256(
            "".join(a["hash"] for a in artifacts).encode()
        ).hexdigest()[:16]

        return {
            "finding_id": finding.get("id", "unknown"),
            "evidence_score": self._calculate_evidence_score(finding, artifacts),
            "hash": package_hash,
            "artifacts": artifacts,
            "chain_of_custody": {
                "collector": self.tool_name,
                "timestamp": time.time(),
                "target": target,
            },
        }

    def _calculate_evidence_score(self, finding: dict, artifacts: list[dict]) -> int:
        """Calculate evidence reliability score (0-100)."""
        score = 30
        if artifacts:
            score += min(30, len(artifacts) * 10)
        if finding.get("reproduced"):
            score += 25
        if finding.get("confidence", 0) > 0.7:
            score += 15
        return min(100, score)
