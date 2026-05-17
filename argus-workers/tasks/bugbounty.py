"""
Bug Bounty Report Celery Task — Generates platform-specific bounty reports.

Uses BugBountyReportGenerator (imported from tools.bugbounty_report_generator)
to convert Argus findings into submission-ready bug bounty reports for
HackerOne, Bugcrowd, Intigriti, and YesWeHack.
"""
import json
import logging
import os
import random
from pathlib import Path

from celery_app import app
from tools.bugbounty_report_generator import BugBountyReportGenerator

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="tasks.bugbounty.generate_bugbounty_report",
    max_retries=2,
    acks_late=True,
    track_started=True,
)
def generate_bugbounty_report(
    self,
    engagement_id: str,
    platform: str,
    output_path: str = "",
    trace_id: str = None,
):
    """
    Generate a bug bounty report for an engagement.

    Fetches findings from PostgreSQL, applies Bug-Reaper audit rules,
    generates platform-specific markdown, and writes to output_path.

    Args:
        engagement_id: UUID of the engagement
        platform: Target platform (hackerone, bugcrowd, intigriti, yeswehack)
        output_path: Path to write the report markdown file
        trace_id: Optional trace ID for logging
    """
    logger.info(
        f"Generating bug bounty report for engagement {engagement_id}, "
        f"platform={platform}"
    )

    # Fetch findings from database
    try:
        findings = _fetch_findings(engagement_id)
        engagement = _fetch_engagement(engagement_id)
    except Exception as e:
        logger.error(f"Failed to fetch data for engagement {engagement_id}: {e}")
        # Exponential backoff with jitter to prevent retry storms
        countdown = min(30 * (2 ** self.request.retries), 300) + random.uniform(0, 10)
        raise self.retry(exc=e, countdown=countdown) from e

    if not findings:
        logger.warning(f"No findings found for engagement {engagement_id}")
        return {
            "engagement_id": engagement_id,
            "platform": platform,
            "status": "no_findings",
            "message": "No findings found for this engagement.",
        }

    # Generate the report
    generator = BugBountyReportGenerator()
    try:
        report_md = generator.generate(
            findings=findings,
            platform=platform,
            engagement=engagement,
        )
    except ValueError as e:
        logger.error(f"Report generation failed: {e}")
        return {
            "engagement_id": engagement_id,
            "platform": platform,
            "status": "failed",
            "error": str(e),
        }

    # Write to output file or default location
    if not output_path:
        reports_dir = Path(os.path.dirname(__file__)).parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        output_path = str(
            reports_dir / f"bugbounty_{platform}_{engagement_id[:8]}.md"
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(report_md, encoding="utf-8")
    logger.info(f"Bug bounty report written to {output_path}")

    return {
        "engagement_id": engagement_id,
        "platform": platform,
        "status": "completed",
        "output_path": output_path,
        "findings_count": len(findings),
        "report_length": len(report_md),
    }


def _fetch_findings(engagement_id: str) -> list[dict]:
    """Fetch findings for an engagement from PostgreSQL."""
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise OSError("DATABASE_URL not set — cannot fetch findings")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, engagement_id, type, severity, confidence, endpoint,
                       source_tool, description, remediation, evidence, repro_steps,
                       cvss_score, cwe_id, verified, created_at, embedding,
                       llm_analysis, fp_likelihood, evidence_strength,
                       tool_agreement_level, needs_validation
                FROM findings
                WHERE engagement_id = %s
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 0
                        WHEN 'HIGH' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        WHEN 'LOW' THEN 3
                        ELSE 4
                    END,
                    confidence DESC
                """,
                (engagement_id,),
            )
            rows = cur.fetchall()
            findings = []
            for row in rows:
                finding = dict(row)
                # Parse evidence JSON if it's a string
                if isinstance(finding.get("evidence"), str):
                    try:
                        finding["evidence"] = json.loads(finding["evidence"])
                    except (json.JSONDecodeError, TypeError):
                        finding["evidence"] = {"raw": finding["evidence"]}
                findings.append(finding)
            return findings
    finally:
        conn.close()


def _fetch_engagement(engagement_id: str) -> dict | None:
    """Fetch engagement metadata from PostgreSQL."""
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise OSError("DATABASE_URL not set — cannot fetch engagement")

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, target_url, status, scan_type, created_at, completed_at
                FROM engagements
                WHERE id = %s
                """,
                (engagement_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()
