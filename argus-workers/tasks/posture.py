"""
Compliance posture scoring tasks for on-demand and scheduled re-scoring.
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    name="tasks.posture.recompute_posture",
    queue="analyze",
)
def recompute_posture(self, engagement_id: str, org_id: str | None = None):
    """
    Recompute compliance posture score for an engagement on-demand.

    Loads all findings from the DB, computes composite + per-framework scores,
    persists a new snapshot, and updates per-control compliance_scores.

    This can be called from the API or scheduled to run after scans complete.
    """
    from compliance_posture_scorer import CompliancePostureScorer
    from database.connection import db_cursor
    from database.repositories.finding_repository import FindingRepository

    logger.info("Recomputing compliance posture for %s", engagement_id)

    try:
        # Resolve org_id from engagement if not provided
        if not org_id:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT org_id FROM engagements WHERE id = %s",
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if row:
                    org_id = str(row[0])

        # Load all findings for the engagement
        finding_repo = FindingRepository()
        all_findings, total = finding_repo.get_findings_by_engagement(
            engagement_id, limit=100000,
        )

        # Convert to dicts
        finding_dicts = []
        for f in all_findings:
            if hasattr(f, 'to_dict'):
                finding_dicts.append(f.to_dict())
            elif isinstance(f, dict):
                finding_dicts.append(f)
            elif isinstance(f, (list, tuple)):
                finding_dicts.append(dict(zip(
                    ['id', 'type', 'severity', 'endpoint'], f[:4], strict=False
                )))

        if not finding_dicts:
            logger.info("No findings for %s — posture stays at 100", engagement_id)
            # Still save a clean snapshot
            scorer = CompliancePostureScorer(engagement_id)
            snapshot = scorer.compute_and_save([], org_id=org_id)
            return {"engagement_id": engagement_id, "composite_score": 100.0, "findings_count": 0}

        # Compute and save
        scorer = CompliancePostureScorer(engagement_id)
        snapshot = scorer.compute_and_save(finding_dicts, org_id=org_id)

        logger.info(
            "Posture recomputed for %s: composite=%.1f, trend=%s, findings=%d",
            engagement_id, snapshot.composite_score, snapshot.trend, len(finding_dicts),
        )

        # Check for compliance alerts (score drops below thresholds)
        _check_compliance_alerts(engagement_id, snapshot, org_id)

        return {
            "engagement_id": engagement_id,
            "composite_score": snapshot.composite_score,
            "trend": snapshot.trend,
            "findings_count": len(finding_dicts),
        }

    except Exception as e:
        logger.error(
            "Failed to recompute posture for %s: %s", engagement_id, e, exc_info=True,
        )
        raise self.retry(exc=e)


def _check_compliance_alerts(
    engagement_id: str,
    snapshot,
    org_id: str | None,
):
    """Check if posture score dropped below alerting thresholds and emit events."""
    try:
        thresholds = {"CRITICAL": 30.0, "WARNING": 50.0, "INFO": 70.0}
        score = snapshot.composite_score

        if score < thresholds["CRITICAL"]:
            level = "CRITICAL"
        elif score < thresholds["WARNING"]:
            level = "WARNING"
        elif score < thresholds["INFO"]:
            level = "INFO"
        else:
            return  # No alert needed

        # Emit compliance alert event via WebSocket
        try:
            from websocket_events import get_websocket_publisher
            publisher = get_websocket_publisher()
            publisher.publish_error(
                engagement_id=engagement_id,
                error_message=(
                    f"Compliance posture alert ({level}): "
                    f"score dropped to {score:.1f} (trend: {snapshot.trend})"
                ),
                error_code="compliance_alert",
                context={
                    "composite_score": score,
                    "trend": snapshot.trend,
                    "alert_level": level,
                    "threshold": thresholds.get(level, 0),
                },
            )
            logger.info(
                "Compliance alert emitted for %s: %s (score=%.1f)",
                engagement_id, level, score,
            )
        except Exception as ws_err:
            logger.debug("Failed to emit compliance alert (non-fatal): %s", ws_err)

    except Exception as e:
        logger.warning("Compliance alert check failed (non-fatal): %s", e)
