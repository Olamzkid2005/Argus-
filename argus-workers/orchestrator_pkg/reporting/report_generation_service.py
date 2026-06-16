"""
ReportGenerationService — generates LLM security reports and SBOM data.

Extracted from Orchestrator.run_reporting() first section.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from streaming import emit_thinking

logger = logging.getLogger(__name__)


class ReportGenerationService:
    """Generates an LLM-powered security report and an SBOM for an engagement.

    Owns the full report pipeline:

    1. Generates the LLM narrative report via ``LLMReportGenerator``
    2. Generates an SBOM from all engagement findings
    3. Upserts both to the ``ReportRepository``
    """

    def __init__(
        self,
        engagement_id: str,
        llm_client: Any,
        llm_model: str,
    ) -> None:
        self.engagement_id = engagement_id
        self.llm_client = llm_client
        self.llm_model = llm_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, job: dict) -> dict:
        """Generate and persist the LLM report + SBOM.

        Args:
            job: The reporting job dict (expects keys ``scored_findings``,
                 ``synthesis``, ``target``, ``type``, ``repo_url``).

        Returns:
            The report_data dict (may be empty if generation failed).
        """
        if not self.llm_client or not self.llm_client.is_available():
            logger.debug(
                "LLM client not available — skipping report generation for %s",
                self.engagement_id,
            )
            return {}

        report_data: dict = {}
        try:
            from database.repositories.report_repository import ReportRepository
            from llm_report_generator import LLMReportGenerator
            from llm_service import LLMService
            from tasks.utils import load_recon_context

            recon_ctx = load_recon_context(self.engagement_id)
            scored_findings = job.get("scored_findings", [])
            synthesis = job.get("synthesis", {})
            llm_svc = LLMService(self.llm_client)
            generator = LLMReportGenerator(llm_svc)
            engagement_info = {
                "target_url": job.get("target", ""),
                "scan_type": job.get("type", ""),
            }
            report_data = generator.generate_report(
                synthesis=synthesis,
                scored_findings=scored_findings,
                engagement=engagement_info,
                recon_context=recon_ctx,
            )

            # ── SBOM generation (non-fatal) ──
            sbom_json = self._generate_sbom(job)

            repo = ReportRepository()
            repo.upsert_report(
                engagement_id=self.engagement_id,
                report_data=report_data,
                model_used=self.llm_model,
                sbom_json=sbom_json,
            )
            emit_thinking(self.engagement_id, "LLM report generated successfully")
        except Exception as e:
            logger.warning(
                "LLM report generation failed (non-fatal): %s", e,
            )

        return report_data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_sbom(self, job: dict) -> Any:
        """Generate an SBOM from all engagement findings.

        Args:
            job: The reporting job dict.

        Returns:
            SBOM JSON dict, or ``None`` on failure.
        """
        from database.repositories.finding_repository import FindingRepository
        from tools.sbom_generator import generate_sbom_from_findings

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise OSError("DATABASE_URL not set — cannot query findings for SBOM")

        fr = FindingRepository(db_url)
        all_findings, _ = fr.get_findings_by_engagement(self.engagement_id, limit=10000)
        return generate_sbom_from_findings(
            engagement_id=self.engagement_id,
            findings=all_findings,
            target_url=job.get("target", ""),
            repo_url=job.get("repo_url", ""),
        )
