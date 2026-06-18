"""
LlmBatchService — PoC generation, chain exploit generation, developer fix generation.

Extracted from Orchestrator.run_analysis() Sections 3–5:
- PoC generation for HIGH/CRITICAL findings (ThreadPoolExecutor)
- Chain exploit generation for CRITICAL/HIGH attack paths
- Developer fix generation for MEDIUM+ findings (ThreadPoolExecutor)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)


class LlmBatchService:
    """Runs LLM batch operations: PoC, chain exploits, and developer fixes.

    All three operations use ThreadPoolExecutor for parallel execution
    and share the same ``llm_client`` and ``engagement_id``.
    """

    def __init__(
        self,
        llm_client: Any,
        engagement_id: str,
        save_poc_fn: Callable[[str, dict], bool],
        save_remediation_fn: Callable[[str, dict], bool],
    ) -> None:
        self.llm_client = llm_client
        self.engagement_id = engagement_id
        self._save_poc = save_poc_fn
        self._save_remediation = save_remediation_fn

    def generate_pocs(
        self,
        scored_findings: list[dict],
        llm_svc: Any,
        cost_tracker: Any,
    ) -> None:
        """Generate PoCs for up to 10 scored findings.

        Args:
            scored_findings: List of scored finding dicts from IntelligenceService.
            llm_svc: LLMService instance for API calls.
            cost_tracker: LlmCostTracker for cost limits.
        """
        if not scored_findings:
            return

        try:
            from poc_generator import PoCGenerator

            poc_gen = PoCGenerator(llm_client=self.llm_client)

            if cost_tracker and llm_svc:
                poc_futures = []
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for finding in scored_findings[:10]:
                        future = pool.submit(
                            poc_gen.generate,
                            finding,
                            llm_svc,
                            cost_tracker,
                        )
                        poc_futures.append((finding, future))

                    for finding, future in poc_futures:
                        try:
                            poc = future.result(timeout=30)
                            if poc and finding.get("id"):
                                self._save_poc(finding["id"], poc)
                        except Exception as e:
                            logger.debug(
                                "PoC for finding %s failed: %s",
                                finding.get("id", "?"),
                                e,
                            )
        except Exception as e:
            logger.warning("PoC generation batch failed (non-fatal): %s", e)

    def generate_chain_exploits(
        self,
        llm_svc: Any,
        cost_tracker: Any,
    ) -> None:
        """Generate chain exploit scripts for CRITICAL/HIGH attack paths.

        Args:
            llm_svc: LLMService instance.
            cost_tracker: LlmCostTracker for cost limits.
        """
        if not cost_tracker or not llm_svc:
            logger.debug(
                "Skipping chain exploit generation — no cost tracker or LLM service"
            )
            return

        try:
            from chain_exploit_generator import ChainExploitGenerator

            chain_gen = ChainExploitGenerator(llm_client=self.llm_client)

            # Load attack paths and build findings map
            attack_paths: list[dict] = []
            findings_map: dict[str, dict] = {}
            conn = None
            cursor = None
            db = None

            try:
                from database.connection import get_db

                db = get_db()
                conn = db.get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    "SELECT id, path_nodes, risk_score, normalized_severity "
                    "FROM attack_paths WHERE engagement_id = %s",
                    (self.engagement_id,),
                )
                cols = ["id", "path_nodes", "risk_score", "normalized_severity"]
                for row in cursor.fetchall():
                    attack_paths.append(dict(zip(cols, row, strict=False)))

                cursor.execute(
                    "SELECT id, type, endpoint, evidence, poc_generated "
                    "FROM findings WHERE engagement_id = %s",
                    (self.engagement_id,),
                )
                fcols = ["id", "type", "endpoint", "evidence", "poc_generated"]
                for row in cursor.fetchall():
                    f = dict(zip(fcols, row, strict=False))
                    findings_map[f["id"]] = f

            except Exception:
                logger.debug(
                    "Failed to load attack paths for chain exploit gen",
                    exc_info=True,
                )
            finally:
                if cursor:
                    cursor.close()
                if conn and db:
                    db.release_connection(conn)

            if attack_paths and findings_map:
                scripts = chain_gen.generate_for_engagement(
                    engagement_id=self.engagement_id,
                    attack_paths=attack_paths,
                    findings_map=findings_map,
                    llm_service=llm_svc,
                    cost_tracker=cost_tracker,
                    max_chains=3,
                )
                if scripts:
                    saved = ChainExploitGenerator.save_scripts_to_db(
                        self.engagement_id,
                        scripts,
                    )
                    logger.info(
                        "Generated %d chain exploit scripts for engagement %s",
                        saved,
                        self.engagement_id,
                    )
        except Exception as e:
            logger.warning(
                "Chain exploit generation failed (non-fatal): %s",
                e,
            )

    def generate_fixes(
        self,
        scored_findings: list[dict],
        recon_ctx: Any,
        llm_svc: Any,
        cost_tracker: Any,
    ) -> None:
        """Generate developer fixes for up to 15 scored findings.

        Args:
            scored_findings: List of scored finding dicts from IntelligenceService.
            recon_ctx: ReconContext (for tech_stack).
            llm_svc: LLMService instance.
            cost_tracker: LlmCostTracker for cost limits.
        """
        if not cost_tracker or not llm_svc:
            return

        try:
            from developer_fix_assistant import DeveloperFixAssistant

            fix_assistant = DeveloperFixAssistant(llm_client=self.llm_client)

            # Get tech stack from recon context
            tech_stack: list[str] = []
            if recon_ctx is not None:
                tech_stack = (
                    recon_ctx.tech_stack if hasattr(recon_ctx, "tech_stack") else []
                ) or []

            fix_futures = []
            with ThreadPoolExecutor(max_workers=4) as pool:
                for finding in scored_findings[:15]:
                    future = pool.submit(
                        fix_assistant.generate,
                        finding,
                        tech_stack,
                        llm_svc,
                        cost_tracker,
                    )
                    fix_futures.append((finding, future))

                for finding, future in fix_futures:
                    try:
                        fix = future.result(timeout=45)
                        if fix and finding.get("id"):
                            self._save_remediation(finding["id"], fix)
                    except Exception as e:
                        logger.debug(
                            "Fix for finding %s failed: %s",
                            finding.get("id", "?"),
                            e,
                        )
        except Exception as e:
            logger.warning("Fix generation batch failed (non-fatal): %s", e)
