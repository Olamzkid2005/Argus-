"""
Celery task for running scan diff after scheduled scans.

Called as the final link in a Celery chain:
    chain(scan_tasks, analyze_task, report_task, diff_task)()

Handles the first-scan case (no previous engagement to diff against).
Auto-closes fixed findings and fires webhooks for actionable changes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from celery_app import app
from tasks.base import task_error_boundary

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="tasks.diff.run_scan_diff",
    soft_time_limit=120,
    time_limit=300,
)
def run_scan_diff(
    self,
    prev_engagement_id: str | None,
    new_engagement_id: str,
    org_id: str,
):
    """Run diff between the previous and current scan of a target.

    Args:
        prev_engagement_id: Previous engagement ID (None on first scan)
        new_engagement_id: Just-completed engagement ID
        org_id: Organization ID for profile lookup

    Returns:
        Dict with status and diff_summary
    """
    with task_error_boundary(self, new_engagement_id, "scan_diff"):
        if not prev_engagement_id:
            logger.info(
                "First scan of target — no diff for %s",
                new_engagement_id,
            )
            return {"status": "skipped", "reason": "first_scan"}

        from database.repositories.target_profile_repository import (
            TargetProfileRepository,
        )
        from scan_diff_engine import ScanDiffEngine

        db_url = os.getenv("DATABASE_URL")
        engine = ScanDiffEngine(db_url)

        # Load target profile for fixed-finding fingerprints
        profile_repo = TargetProfileRepository()
        target_url = _get_engagement_target(new_engagement_id)
        domain = (
            TargetProfileRepository.extract_domain(target_url) if target_url else ""
        )
        profile = profile_repo.get_profile(org_id, domain) if domain else None

        # Compute diff
        diff_result = engine.diff(prev_engagement_id, new_engagement_id, profile)

        # Auto-close fixed findings via batch UPDATE (1 query vs N queries)
        fixed_ids = [
            f["id"] for f in diff_result.get(engine.CAT_FIXED, []) if f.get("id")
        ]
        # L-09: Use atomic batch_mark_fixed_with_fps to mark findings fixed
        # and update the profile's fingerprint list in a single transaction.
        # This prevents the race condition where batch_mark_fixed succeeds
        # but the fingerprint update fails (or vice versa).
        fixed_findings = diff_result.get(engine.CAT_FIXED, [])
        if fixed_ids and domain:
            updated = engine.batch_mark_fixed_with_fps(
                fixed_ids,
                fixed_findings,
                new_engagement_id,
                org_id,
                domain,
            )
            logger.info(
                "Batch-marked %d findings as fixed (with fps) for engagement %s",
                updated,
                new_engagement_id,
            )
        elif fixed_ids:
            # No domain — can't update profile, just mark fixed
            updated = engine.batch_mark_fixed(fixed_ids, new_engagement_id)
            logger.info(
                "Batch-marked %d findings as fixed for engagement %s",
                updated,
                new_engagement_id,
            )

        # Store diff in profile
        if domain:
            engine.store_diff_in_profile(org_id, domain, diff_result)

        logger.info(
            "Diff complete for %s: %d new, %d fixed, %d regressed, %d severity changed",
            domain or new_engagement_id,
            diff_result["summary"]["new_count"],
            diff_result["summary"]["fixed_count"],
            diff_result["summary"]["regressed_count"],
            diff_result["summary"]["severity_changed_count"],
        )

        return {
            "status": "completed",
            "diff_summary": diff_result["summary"],
        }


def _get_engagement_target(engagement_id: str) -> str | None:
    """Get target_url from engagement using the connection pool.

    Args:
        engagement_id: UUID of the engagement

    Returns:
        target_url string, or None
    """
    from database.connection import db_cursor

    try:
        with db_cursor() as cursor:
            cursor.execute(
                "SELECT target_url FROM engagements WHERE id = %s",
                (engagement_id,),
            )
            row = cursor.fetchone()
            return str(row[0]) if row else None
    except Exception as e:
        logger.warning("Failed to get engagement target for %s: %s", engagement_id, e)
        return None


def _update_fixed_fingerprints(
    profile_repo: Any,
    org_id: str,
    domain: str,
    fixed_findings: list[dict],
) -> None:
    """Append fingerprints of newly fixed findings to the target profile.

    Deduplicates the list and caps it at 1000 entries to prevent
    unbounded JSONB column growth (L-03 fix).

    Uses the connection pool.

    Args:
        profile_repo: TargetProfileRepository instance
        org_id: Organization ID
        domain: Target domain
        fixed_findings: List of findings that were fixed
    """
    from scan_diff_engine import ScanDiffEngine

    fps = [ScanDiffEngine._fingerprint(f) for f in fixed_findings]
    if not fps:
        return

    # Deduplicate new fingerprints before storing
    fps = list(set(fps))

    try:
        from database.connection import db_connection

        with db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE target_profiles
                    SET fixed_finding_fingerprints = (
                        SELECT jsonb_agg(elem ORDER BY elem)
                        FROM (
                            SELECT DISTINCT elem
                            FROM jsonb_array_elements(
                                COALESCE(fixed_finding_fingerprints, '[]'::jsonb) || %s::jsonb
                            ) AS elem
                            ORDER BY elem DESC
                            LIMIT 1000
                        ) deduped
                    ),
                    updated_at = NOW()
                    WHERE org_id = %s AND target_domain = %s
                    """,
                    (json.dumps(fps), org_id, domain),
                )
    except Exception as e:
        logger.warning("Failed to update fixed fingerprints: %s", e)
