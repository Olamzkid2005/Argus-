"""
FindingPersistenceService — saves findings to the database with enrichment,
batching, secret-entity upsert, compliance posture scoring, and webhook dispatch.

Extracted from Orchestrator._save_findings().
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class FindingPersistenceService:
    """Persists findings to the database with pre-processing, batch writing,
    compliance posture updates, and post-save webhook dispatch.

    Owns the full save pipeline:

    1. Normalise heterogeneous inputs to plain dicts
    2. Pre-process each finding (bug bounty tagging, CVSS estimation,
       OWASP/CWE classification, tool attribution)
    3. Split into secret / non-secret groups
    4. Compute compliance posture from ALL engagement findings in DB
    5. Batch-save non-secret findings (single transaction)
    6. Upsert secret findings individually (different conflict key)
    7. Fire webhooks for HIGH / CRITICAL findings
    """

    # Tools whose results are treated as secrets (different upsert path)
    SECRET_TOOLS: set[str] = {"gitleaks", "trufflehog", "secret-scan"}

    def __init__(
        self,
        engagement_id: str,
        finding_repo: Any,
        bug_bounty_mode: bool = False,
        classify_finding_type_fn: Callable[[str], dict[str, str | None]] = None,
        get_org_id_fn: Callable[[], str | None] = None,
    ) -> None:
        self.engagement_id = engagement_id
        self.finding_repo = finding_repo
        self.bug_bounty_mode = bug_bounty_mode
        self._classify_finding_type = classify_finding_type_fn or (lambda _: {"owasp": "N/A", "cwe": "N/A"})
        self._get_org_id = get_org_id_fn or (lambda: None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, findings: list[dict]) -> int:
        """Save findings to the database.

        Args:
            findings: Raw findings list (dicts or objects with ``.to_dict()`` /
                      ``vars()`` support).

        Returns:
            Number of findings that failed to save. 0 means all succeeded.
        """
        if not self.finding_repo:
            logger.error(
                "No finding repository configured — DATABASE_URL not set, "
                "cannot persist findings",
            )
            return len(findings)
        if not findings:
            return 0

        # Phase 0 — normalise heterogeneous inputs to plain dicts
        findings = self._normalise_inputs(findings)
        if not findings:
            return 0

        self._init_embedding_service()

        # Phase 1 — pre-process without touching the database
        findings_to_save = self._preprocess(findings)
        if not findings_to_save:
            return 0

        non_secret, secret = self._split_secret(findings_to_save)

        failed_count = 0
        from streaming import StreamingFindingEmitter
        _finding_emitter = StreamingFindingEmitter(self.engagement_id)

        # Phase 2 — update compliance posture (reads ALL engagement findings)
        self._update_compliance_posture()

        # Phase 3 — batch-save non-secret findings
        failed_count += self._batch_save_non_secret(
            non_secret, _finding_emitter,
        )

        # Phase 4 — upsert secret findings individually
        failed_count += self._upsert_secrets(secret, _finding_emitter)

        # Phase 5 — fire webhooks for HIGH / CRITICAL findings
        self._fire_webhooks(findings_to_save)

        if failed_count > 0:
            logger.error(
                "_save_findings: %d of %d findings failed to save for "
                "engagement %s",
                failed_count, len(findings), self.engagement_id,
            )
        return failed_count

    # ------------------------------------------------------------------
    # Internal phases
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_inputs(findings: list) -> list[dict]:
        """Coerce heterogeneous finding objects to plain dicts."""
        normalized: list[dict] = []
        for item in findings:
            if isinstance(item, dict):
                normalized.append(item)
                continue
            if hasattr(item, "tool") and hasattr(item, "output"):
                logger.warning(
                    "_save_findings received unparsed tool result for tool "
                    "'%s' — skipping.",
                    getattr(item, "tool", "unknown"),
                )
                continue
            if hasattr(item, "findings") and isinstance(item.findings, list):
                for f in item.findings:
                    if isinstance(f, dict):
                        normalized.append(f)
                continue
            try:
                normalized.append(vars(item))
            except TypeError:
                logger.warning(
                    "_save_findings: cannot coerce %s to dict, skipping",
                    type(item),
                )
        return normalized

    def _init_embedding_service(self) -> None:
        """Initialise the embedding service for this engagement."""
        try:
            from database.services.embedding_service import EmbeddingService
            EmbeddingService(self.engagement_id)
        except Exception:
            logger.debug("EmbeddingService init skipped (non-fatal)")

    def _preprocess(self, findings: list[dict]) -> list[dict]:
        """Enrich every finding with metadata before persistence.

        - Tags bug-bounty findings if ``bug_bounty_mode`` is set.
        - Estimates CVSS score when missing.
        - Assigns OWASP category and CWE ID when missing.
        - Ensures ``source_tool`` is set.
        """
        secret_tools = self.SECRET_TOOLS
        processed: list[dict] = []

        for finding in findings:
            if self.bug_bounty_mode:
                finding["bugbounty_source"] = True
                if "source" not in finding or finding["source"] == "bugbounty":
                    finding["source"] = "bugbounty"

            if finding.get("cvss_score") is None:
                try:
                    from cvss_calculator import estimate_cvss
                    finding["cvss_score"] = estimate_cvss(
                        finding_type=finding.get("type", ""),
                        severity=finding.get("severity", "MEDIUM"),
                        evidence_strength=finding.get("evidence_strength", "moderate"),
                    )
                except Exception as cvss_err:
                    logger.warning("CVSS estimation failed (non-fatal): %s", cvss_err)

            if not finding.get("owasp_category") or not finding.get("cwe_id"):
                ftype = finding.get("type", "")
                classification = self._classify_finding_type(ftype)
                if not finding.get("owasp_category"):
                    finding["owasp_category"] = classification.get("owasp")
                if not finding.get("cwe_id"):
                    finding["cwe_id"] = classification.get("cwe")

            st = finding.get("tool") or finding.get("source_tool") or "unknown"
            if not finding.get("source_tool"):
                finding["source_tool"] = st

            processed.append(finding)

        return processed

    def _split_secret(
        self,
        findings: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """Separate findings into secret (individual upsert) and non-secret (batch)."""
        non_secret = [
            f for f in findings
            if f.get("source_tool") not in self.SECRET_TOOLS
            and not f.get("type", "").startswith("COMMITTED_SECRET")
        ]
        secret = [
            f for f in findings
            if f.get("source_tool") in self.SECRET_TOOLS
            or f.get("type", "").startswith("COMMITTED_SECRET")
        ]
        return non_secret, secret

    def _update_compliance_posture(self) -> None:
        """Query all engagement findings from DB and compute compliance posture."""
        try:
            from compliance_posture_scorer import CompliancePostureScorer

            posture_scorer = CompliancePostureScorer(self.engagement_id)
            all_db_findings, _ = self.finding_repo.get_findings_by_engagement(
                self.engagement_id, limit=100000,
            )
            finding_dicts = []
            for f in all_db_findings:
                if hasattr(f, "to_dict"):
                    finding_dicts.append(f.to_dict())
                elif isinstance(f, dict):
                    finding_dicts.append(f)
                elif isinstance(f, (list, tuple)):
                    finding_dicts.append(dict(
                        zip(["id", "type", "severity", "endpoint"], f[:4], strict=False),
                    ))
            if finding_dicts:
                org_id = self._get_org_id()
                snapshot = posture_scorer.compute_and_save(
                    finding_dicts, org_id=org_id,
                )
                logger.info(
                    "Compliance posture updated for %s: composite=%s, trend=%s",
                    self.engagement_id, snapshot.composite_score, snapshot.trend,
                )
        except Exception as posture_err:
            logger.warning(
                "Failed to update compliance posture (non-fatal): %s",
                posture_err,
            )

    def _batch_save_non_secret(
        self,
        non_secret: list[dict],
        finding_emitter: Any,
    ) -> int:
        """Batch-save non-secret findings in a single transaction.

        Returns the number of failures.
        """
        if not non_secret:
            return 0

        from database.repositories.finding_repository import FindingCapExceededError

        try:
            inserted, updated = self.finding_repo.batch_create_or_update_findings(
                self.engagement_id, non_secret,
            )
            logger.info(
                "_save_findings: batch saved %d (inserted=%d, updated=%d) "
                "findings for %s",
                inserted + updated, inserted, updated, self.engagement_id,
            )
            for f in non_secret:
                if f.get("_saved_id"):
                    try:
                        finding_emitter.emit_finding(f)
                    except Exception as emit_err:
                        logger.warning(
                            "Failed to emit finding event (non-fatal): %s",
                            emit_err,
                        )
            return 0
        except FindingCapExceededError:
            logger.error(
                "Finding cap exceeded for engagement %s during batch save",
                self.engagement_id,
            )
            return len(non_secret)
        except Exception as e:
            logger.error(
                "_save_findings: batch save failed for %s: %s",
                self.engagement_id, e, exc_info=True,
            )
            return len(non_secret)

    def _upsert_secrets(
        self,
        secret: list[dict],
        finding_emitter: Any,
    ) -> int:
        """Upsert secret findings individually (different conflict key).

        Returns the number of failures.
        """
        failed = 0
        for f in secret:
            try:
                saved_id = self.finding_repo.upsert_secret_finding(
                    engagement_id=self.engagement_id,
                    finding_type=f.get("type", "UNKNOWN"),
                    severity=f.get("severity", "INFO"),
                    endpoint=f.get("endpoint", ""),
                    evidence=f.get("evidence", {}),
                    confidence=f.get("confidence", 0.5),
                    source_tool=f.get("source_tool", "unknown"),
                    cvss_score=f.get("cvss_score"),
                )
                if saved_id:
                    f["_saved_id"] = saved_id
                    try:
                        finding_emitter.emit_finding(f)
                    except Exception as emit_err:
                        logger.warning(
                            "Failed to emit finding event (non-fatal): %s",
                            emit_err,
                        )
            except (ValueError, OSError, KeyError) as e:
                failed += 1
                logger.warning("Failed to save secret finding: %s", e)
        return failed

    # ------------------------------------------------------------------
    # JSONB persistence (PoC / remediation fix)
    # ------------------------------------------------------------------

    def save_poc(self, finding_id: str, poc_data: dict) -> bool:
        """Save PoC data to findings.poc_generated column."""
        return self._update_finding_jsonb(
            finding_id, "poc_generated", poc_data, log_label="PoC",
        )

    def save_remediation(self, finding_id: str, fix_data: dict) -> bool:
        """Save remediation fix to findings.remediation_fix column."""
        return self._update_finding_jsonb(
            finding_id, "remediation_fix", fix_data, log_label="remediation fix",
        )

    def _update_finding_jsonb(
        self,
        finding_id: str,
        column: str,
        data: dict,
        log_label: str = "update",
    ) -> bool:
        """Save a JSONB dict to a findings column with an auto-timestamp column.

        Args:
            finding_id: UUID of the finding
            column: Column name to update (e.g. 'poc_generated', 'remediation_fix')
            data: Dict to store as JSONB
            log_label: Human-readable label for log messages

        Returns:
            True if saved successfully
        """
        from psycopg2.sql import Identifier, SQL

        from database.connection import db_cursor

        try:
            with db_cursor() as cursor:
                cursor.execute(
                    SQL("UPDATE findings SET {col} = %s::jsonb, {col_at} = NOW() WHERE id = %s").format(
                        col=Identifier(column),
                        col_at=Identifier(f"{column}_at"),
                    ),
                    (json.dumps(data), finding_id),
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.warning(
                "Failed to save %s for finding %s: %s",
                log_label, finding_id, e,
            )
            return False

    def _fire_webhooks(self, findings_to_save: list[dict]) -> None:
        """Fire webhooks for HIGH / CRITICAL findings."""
        for f in findings_to_save:
            if f.get("_saved_id") and f.get("severity", "").upper() in ("CRITICAL", "HIGH"):
                try:
                    from post_finding_hooks import fire_finding_webhooks
                    fire_finding_webhooks({
                        "id": f["_saved_id"],
                        "engagement_id": self.engagement_id,
                        "type": f.get("type"),
                        "severity": f.get("severity"),
                        "endpoint": f.get("endpoint"),
                        "source_tool": f.get("source_tool", ""),
                        "confidence": f.get("confidence", 0),
                    })
                except Exception as hook_err:
                    logger.warning(
                        "Webhook dispatch failed (non-fatal): %s", hook_err,
                    )
