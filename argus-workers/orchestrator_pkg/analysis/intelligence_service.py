"""
IntelligenceService — IntelligenceEngine evaluate + LLM synthesis.

Extracted from Orchestrator.run_analysis() Sections 1b–2:
- Creates IntelligenceEngine and runs evaluate()
- Creates LLMService and runs LLMSynthesizer.synthesize()
- Creates per-engagement LlmCostTracker
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class IntelligenceService:
    """Runs IntelligenceEngine evaluation and LLM synthesis.

    This is the second phase of analysis: evaluating the snapshot to
    produce scored findings, then synthesizing them via LLM.
    """

    def __init__(
        self,
        db_conn: str,
        engagement_id: str,
        llm_client: Any | None,
    ) -> None:
        self.db_conn = db_conn
        self.engagement_id = engagement_id
        self.llm_client = llm_client

    def evaluate(self, snapshot: dict, org_id: str | None) -> dict:
        """Run IntelligenceEngine.evaluate() on the prepared snapshot.

        Args:
            snapshot: The snapshot dict built by SnapshotService.
            org_id: Organisation ID for learned FP rate lookups.

        Returns:
            The evaluation dict from IntelligenceEngine.
        """
        from intelligence_engine import IntelligenceEngine

        engine = IntelligenceEngine(self.db_conn)
        evaluation = engine.evaluate(snapshot, org_id=org_id)
        return evaluation

    def run_synthesis(
        self,
        evaluation: dict,
        snapshot: dict,
    ) -> tuple[dict, Any | None, Any | None, Any | None, list[dict]]:
        """Run LLM synthesis on evaluation results.

        Creates a per-engagement cost tracker, initialises LLMService,
        loads recon context, and runs LLMSynthesizer.synthesize().

        Args:
            evaluation: The evaluation dict from ``evaluate()``.
            snapshot: The original snapshot dict (for attack_graph paths).

        Returns:
            Tuple of (synthesis, llm_svc, engagement_cost_tracker,
                      recon_ctx, scored_findings).
        """
        from config.constants import LLM_MAX_COST_PER_ENGAGEMENT
        from llm_synthesizer import LLMSynthesizer
        from tasks.utils import LlmCostTracker

        engagement_cost_tracker = LlmCostTracker(
            engagement_id=self.engagement_id,
            max_cost=LLM_MAX_COST_PER_ENGAGEMENT,
        )

        synthesis: dict = {}
        llm_svc: Any = None
        recon_ctx: Any = None

        if self.llm_client and self.llm_client.is_available():
            try:
                from llm_service import LLMService
                from tasks.utils import load_recon_context

                llm_svc = LLMService(
                    self.llm_client,
                    cost_tracker=engagement_cost_tracker,
                )
                recon_ctx = load_recon_context(self.engagement_id)
            except Exception as e:
                logger.warning("LLM service init failed (non-fatal): %s", e)

        if llm_svc:
            try:
                synthesizer = LLMSynthesizer(llm_svc)
                synthesis = synthesizer.synthesize(
                    scored_findings=evaluation.get("scored_findings", []),
                    attack_paths=snapshot.get("attack_graph", {}).get("paths", []),
                    recon_context=recon_ctx,
                )
            except Exception as e:
                logger.warning("LLM synthesis failed (non-fatal): %s", e)

        scored: list[dict] = evaluation.get("scored_findings", [])
        return synthesis, llm_svc, engagement_cost_tracker, recon_ctx, scored
