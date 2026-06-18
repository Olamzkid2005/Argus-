"""
TargetProfileService — updates the target profile with findings from an engagement.

Extracted from Orchestrator.run_reporting() second section.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class TargetProfileService:
    """Updates the target profile with findings, recon context, and tool
    accuracy data from the engagement.

    Owns the full profile-update pipeline:

    1. Loads all engagement findings from the DB
    2. Loads recon context from Redis
    3. Loads tool false-positive rates from the DB
    4. Upserts the enriched profile via ``TargetProfileRepository``
    """

    def __init__(
        self,
        engagement_id: str,
        finding_repo: Any,
        get_org_id_fn: Callable[[], str | None],
    ) -> None:
        self.engagement_id = engagement_id
        self.finding_repo = finding_repo
        self._get_org_id = get_org_id_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, job: dict) -> None:
        """Load engagement data and upsert the target profile.

        Uses the profile DB repo and tool accuracy repo; failures are
        caught and logged as warnings (non-fatal).

        Args:
            job: The reporting job dict (expects key ``target``).
        """
        _org_id = self._get_org_id()
        try:
            from urllib.parse import urlparse

            from database.repositories.target_profile_repository import (
                TargetProfileRepository,
            )
            from database.repositories.tool_accuracy_repository import (
                ToolAccuracyRepository,
            )
            from tasks.utils import load_recon_context

            target_url = job.get("target", "")
            target_domain = urlparse(target_url).netloc
            if not target_domain or not _org_id:
                return

            profile_repo = TargetProfileRepository()

            # Load findings from this engagement
            all_findings, _ = (
                self.finding_repo.get_findings_by_engagement(
                    self.engagement_id,
                )
                if self.finding_repo
                else ([], None)
            )

            # Load recon context from Redis
            recon_ctx = load_recon_context(self.engagement_id)
            recon_ctx_dict = (
                recon_ctx.to_dict() if hasattr(recon_ctx, "to_dict") else {}
            )

            # Load tool accuracy for noisy-tool detection
            acc_repo = ToolAccuracyRepository()
            fp_rates = acc_repo.load_fp_rates(_org_id)

            profile_repo.upsert_from_engagement(
                org_id=_org_id,
                target_url=target_url,
                engagement_id=self.engagement_id,
                recon_context=recon_ctx_dict,
                findings=[
                    f.to_dict() if hasattr(f, "to_dict") else dict(f)
                    for f in (all_findings or [])
                ],
                tool_accuracy_fp_rates=fp_rates,
            )
            logger.info(
                "Target profile updated for %s",
                target_domain,
            )
        except Exception as e:
            logger.warning(
                "Target profile update failed (non-fatal): %s",
                e,
            )
