"""
Celery task for running scan diff after scheduled scans.

Called as the final link in a Celery chain:
    chain(scan_tasks, analyze_task, report_task, diff_task)()

Handles the first-scan case (no previous engagement to diff against).
Auto-closes fixed findings and fires webhooks for actionable changes.
"""

import contextlib
import json
import logging
import os

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
        profile_repo = TargetProfileRepository(db_url)
        target_url = _get_engagement_target(new_engagement_id)
        domain = (
            TargetProfileRepository._extract_domain(target_url)
            if target_url
            else ""
        )
        profile = (
            profile_repo.get_profile(org_id, domain) if domain else None
        )

        # Compute diff
        diff_result = engine.diff(
            prev_engagement_id, new_engagement_id, profile
        )

        # Auto-close fixed findings
        for finding in diff_result.get(engine.CAT_FIXED, []):
            finding_id = finding.get("id")
            if finding_id:
                engine.mark_fixed(finding_id, new_engagement_id)

        # Update fixed fingerprints for regression tracking
        fixed_findings = diff_result.get(engine.CAT_FIXED, [])
        if fixed_findings:
            _update_fixed_fingerprints(
                profile_repo,
                org_id,
                domain,
                fixed_findings,
            )

        # Store diff in profile
        if domain:
            engine.store_diff_in_profile(org_id, domain, diff_result)

        logger.info(
            "Diff complete for %s: %d new, %d fixed, %d regressed, "
            "%d severity changed",
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
    """Get target_url from engagement.

    Args:
        engagement_id: UUID of the engagement

    Returns:
        target_url string, or None
    """
    from database.connection import connect

    conn = None
    try:
        conn = connect(os.getenv("DATABASE_URL"))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT target_url FROM engagements WHERE id = %s",
            (engagement_id,),
        )
        row = cursor.fetchone()
        return str(row[0]) if row else None
    except Exception:
        return None
    finally:
        if conn:
            with contextlib.suppress(Exception):
                conn.close()


def _update_fixed_fingerprints(
    profile_repo: "TargetProfileRepository",  # noqa: F821
    org_id: str,
    domain: str,
    fixed_findings: list[dict],
) -> None:
    """Append fingerprints of newly fixed findings to the target profile.

    Args:
        profile_repo: TargetProfileRepository instance
        org_id: Organization ID
        domain: Target domain
        fixed_findings: List of findings that were fixed
    """
    from scan_diff_engine import ScanDiffEngine

    fps = [
        ScanDiffEngine._fingerprint(f)
        for f in fixed_findings
    ]
    if not fps:
        return

    conn = None
    try:
        from database.connection import connect

        conn = connect(os.getenv("DATABASE_URL"))
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE target_profiles
            SET fixed_finding_fingerprints =
                COALESCE(fixed_finding_fingerprints, '[]'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE org_id = %s AND target_domain = %s
            """,
            (json.dumps(fps), org_id, domain),
        )
        conn.commit()
    except Exception as e:
        logger.warning(
            "Failed to update fixed fingerprints: %s", e
        )
    finally:
        if conn:
            with contextlib.suppress(Exception):
                conn.close()
