"""
Celery tasks for reporting phase

Requirements: 20.1, 20.2, 20.3, 23.4, 23.5, 17.1, 17.2, 17.3, 17.4
"""
import json
import logging
import os
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional
from celery_app import app
from database.connection import connect
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

from utils.validation import validate_uuid
from orchestrator import Orchestrator
from tracing import TracingManager
from distributed_lock import LockContext, DistributedLock
from state_machine import EngagementStateMachine
from compliance_reporting import ComplianceReportGenerator


@app.task(bind=True, name="tasks.report.generate_report")
def generate_report(self, engagement_id: str, trace_id: str = None):
    """
    Generate final report for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
    """
    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "report", trace_id):
        job = {
            "type": "report",
            "engagement_id": engagement_id,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="reporting"
                )

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_reporting(job)

                state_machine.transition("complete", "Report generated")

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.safe_transition("failed", f"Reporting failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.report.get_findings_summary")
def get_findings_summary(self, engagement_id: str, trace_id: str = None):
    """
    Get findings summary for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "findings_summary", trace_id):
        conn = connect(db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT
                    severity,
                    COUNT(*) as count,
                    AVG(confidence) as avg_confidence
                FROM findings
                WHERE engagement_id = %s
                GROUP BY severity
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'LOW' THEN 4
                        WHEN 'INFO' THEN 5
                    END
                """,
                (engagement_id,)
            )

            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()


def _get_engagement_state(engagement_id: str, db_conn_string: str) -> str:
    """
    Query the current engagement state from the database.

    Args:
        engagement_id: Engagement ID
        db_conn_string: Database connection string

    Returns:
        Current engagement status string
    """
    try:
        # Validate UUID before DB query to prevent InvalidTextRepresentation errors
        valid_id = validate_uuid(engagement_id, "engagement_id")
        conn = connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (valid_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "created"
    except Exception:
        return "created"


@app.task(bind=True, name="tasks.report.generate_scheduled_reports")
def generate_scheduled_reports(self):
    """
    Generate all due scheduled reports and send them via email.
    Called by a periodic Celery beat schedule.
    """
    db_conn_string = os.getenv("DATABASE_URL")
    conn = connect(db_conn_string)
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # Find all due scheduled reports
        cursor.execute(
            """
            SELECT id, org_id, created_by, name, report_type, frequency,
                   engagement_ids, email_recipients, next_run_at
            FROM scheduled_reports
            WHERE is_active = true AND next_run_at <= NOW()
            """
        )
        due_reports = cursor.fetchall()

        for report in due_reports:
            try:
                # Generate report data
                report_data = _generate_report_data(
                    report["org_id"],
                    report["engagement_ids"],
                    report["report_type"],
                    cursor,
                )

                # Send email (placeholder for actual email integration)
                _send_report_email(
                    report["email_recipients"],
                    report["name"],
                    report_data,
                )

                # Update next run time
                next_run = _calculate_next_run(report["frequency"])
                cursor.execute(
                    """
                    UPDATE scheduled_reports
                    SET last_run_at = NOW(), next_run_at = %s
                    WHERE id = %s
                    """,
                    (next_run, report["id"]),
                )

                # Log activity
                cursor.execute(
                    """
                    INSERT INTO activity_feed (org_id, user_id, activity_type, entity_type, entity_id, metadata)
                    VALUES (%s, %s, 'scheduled_report_sent', 'report', %s, %s)
                    """,
                    (
                        report["org_id"],
                        report["created_by"],
                        report["id"],
                        str({"recipients": report["email_recipients"], "report_name": report["name"]}),
                    ),
                )

                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Failed to generate scheduled report {report['id']}: {e}")
                continue

        return {"processed": len(due_reports)}
    finally:
        cursor.close()
        conn.close()


def _generate_report_data(org_id: str, engagement_ids: Optional[List[str]], report_type: str, cursor) -> Dict[str, Any]:
    """Generate report data based on type and engagements."""
    engagement_filter = ""
    params = [org_id]

    if engagement_ids:
        engagement_filter = " AND e.id = ANY(%s)"
        params.append(engagement_ids)

    # Findings summary
    cursor.execute(
        f"""
        SELECT
            f.severity,
            COUNT(*) as count,
            AVG(f.confidence) as avg_confidence,
            f.source_tool
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = %s {engagement_filter}
        GROUP BY f.severity, f.source_tool
        ORDER BY
            CASE f.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH' THEN 2
                WHEN 'MEDIUM' THEN 3
                WHEN 'LOW' THEN 4
                ELSE 5
            END
        """,
        params,
    )
    findings = [dict(row) for row in cursor.fetchall()]

    # Engagement stats
    cursor.execute(
        f"""
        SELECT
            e.id,
            e.target_url,
            e.status,
            e.created_at,
            COUNT(f.id) as findings_count
        FROM engagements e
        LEFT JOIN findings f ON f.engagement_id = e.id
        WHERE e.org_id = %s {engagement_filter}
        GROUP BY e.id
        ORDER BY e.created_at DESC
        """,
        params,
    )
    engagements = [dict(row) for row in cursor.fetchall()]

    return {
        "report_type": report_type,
        "generated_at": datetime.now(UTC).isoformat(),
        "findings_summary": findings,
        "engagements": engagements,
    }


def _send_report_email(recipients: List[str], report_name: str, report_data: Dict[str, Any]):
    """Send report via email. Placeholder for actual email service integration."""
    # In production, integrate with SendGrid, AWS SES, or Resend
    logger.warning("Email sending not configured — _send_report_email is a placeholder")
    logger.info("Would send '%s' to %s with %d severity groups, %d engagements",
                report_name, ', '.join(recipients),
                len(report_data.get('findings_summary', [])),
                len(report_data.get('engagements', [])))


def _calculate_next_run(frequency: str) -> datetime:
    """Calculate the next run time based on frequency."""
    now = datetime.now(UTC)
    if frequency == "daily":
        return now + timedelta(days=1)
    elif frequency == "weekly":
        return now + timedelta(weeks=1)
    elif frequency == "monthly":
        return now + timedelta(days=30)
    elif frequency == "quarterly":
        return now + timedelta(days=90)
    return now + timedelta(weeks=1)


@app.task(bind=True, name="tasks.report.generate_compliance_report")
def generate_compliance_report(
    self,
    engagement_id: str,
    standard: str,
    trace_id: str = None,
):
    """
    Generate a compliance report (OWASP Top 10, PCI DSS, or SOC 2)

    Args:
        engagement_id: Engagement ID
        standard: Compliance standard (owasp_top10, pci_dss, soc2)
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, f"compliance_report_{standard}", trace_id):
        conn = connect(db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Fetch findings for the engagement
            cursor.execute(
                """
                SELECT
                    id,
                    type,
                    severity,
                    endpoint,
                    evidence,
                    source_tool,
                    confidence,
                    created_at
                FROM findings
                WHERE engagement_id = %s
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'LOW' THEN 4
                        WHEN 'INFO' THEN 5
                    END
                """,
                (engagement_id,)
            )

            findings = [dict(row) for row in cursor.fetchall()]

            # Generate compliance report
            generator = ComplianceReportGenerator()

            if standard == "owasp_top10":
                report = generator.generate_owasp_report(engagement_id, findings)
            elif standard == "pci_dss":
                report = generator.generate_pci_dss_checklist(engagement_id, findings)
            elif standard == "soc2":
                report = generator.generate_soc2_template(engagement_id, findings)
            else:
                raise ValueError(f"Unknown compliance standard: {standard}")

            html = generator.render_report(report)
            json_data = generator.render_to_json(report)

            # Get org_id for the engagement
            cursor.execute(
                "SELECT org_id FROM engagements WHERE id = %s",
                (engagement_id,)
            )
            org_row = cursor.fetchone()
            org_id = org_row["org_id"] if org_row else None

            # Store report in database
            cursor.execute(
                """
                INSERT INTO compliance_reports (
                    org_id, engagement_id, standard, title, results, html_content, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    org_id,
                    engagement_id,
                    standard,
                    report.title,
                    json.dumps(json_data),
                    html,
                    "ready",
                )
            )

            row = cursor.fetchone()
            report_id = row["id"] if row else None
            conn.commit()

            return {
                "report_id": str(report_id) if report_id else None,
                "standard": standard,
                "engagement_id": engagement_id,
                "findings_count": len(findings),
                "status": "ready",
            }

        except Exception as e:
            logger.error("Compliance report generation failed: %s", e)
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


@app.task(bind=True, name="tasks.report.generate_full_report")
def generate_full_report(
    self,
    engagement_id: str,
    report_id: str,
    trace_id: str = None,
):
    """
    Generate a full security audit report for an engagement

    Args:
        engagement_id: Engagement ID
        report_id: Report ID to update (or None to create new)
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")

    tracing_manager = TracingManager(db_conn_string)

    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    with tracing_manager.trace_execution(engagement_id, "full_report", trace_id):
        conn = connect(db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 1. Query the engagement
            cursor.execute(
                """
                SELECT id, target_url, scan_type, org_id, created_at, completed_at
                FROM engagements WHERE id = %s
                """,
                (engagement_id,)
            )
            engagement = cursor.fetchone()
            if not engagement:
                raise ValueError(f"Engagement {engagement_id} not found")

            org_id = engagement["org_id"]

            # 2. Query all findings (using columns that exist in the table)
            cursor.execute(
                """
                SELECT id, type, severity, endpoint, evidence, source_tool,
                       confidence, created_at
                FROM findings
                WHERE engagement_id = %s
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 1
                        WHEN 'HIGH' THEN 2
                        WHEN 'MEDIUM' THEN 3
                        WHEN 'LOW' THEN 4
                        WHEN 'INFO' THEN 5
                    END
                """,
                (engagement_id,)
            )
            findings = [dict(row) for row in cursor.fetchall()]

            # 3. Count by severity
            critical_count = sum(1 for f in findings if f["severity"] == "CRITICAL")
            high_count = sum(1 for f in findings if f["severity"] == "HIGH")
            medium_count = sum(1 for f in findings if f["severity"] == "MEDIUM")
            low_count = sum(1 for f in findings if f["severity"] == "LOW")

            # 4. Get top categories (group by type)
            type_counts = {}
            for f in findings:
                ftype = f["type"]
                type_counts[ftype] = type_counts.get(ftype, 0) + 1

            top_categories = [
                {"name": t, "count": c}
                for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ]

            # 5. Calculate scan duration
            scan_duration = ""
            if engagement.get("created_at") and engagement.get("completed_at"):
                duration = engagement["completed_at"] - engagement["created_at"]
                total_seconds = int(duration.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                scan_duration = f"{hours}h {minutes}m {seconds}s"

            # 6. Render full report template via ComplianceReportGenerator
            generator = ComplianceReportGenerator()
            template = generator.env.get_template("full_report.html")

            report_context = {
                "title": f"Full Security Audit Report - {engagement_id}",
                "engagement_id": str(engagement_id),
                "target_url": engagement.get("target_url", ""),
                "scan_type": engagement.get("scan_type", ""),
                "summary": {
                    "total_findings": len(findings),
                    "critical_count": critical_count,
                    "high_count": high_count,
                    "medium_count": medium_count,
                    "low_count": low_count,
                    "top_categories": top_categories,
                    "scan_duration": scan_duration,
                },
                "findings": findings,
            }

            generated_at = datetime.now(UTC)
            html = template.render(
                report=report_context,
                generated_at=generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            )

            json_data = {"summary": report_context["summary"]}

            # 7. Store HTML into compliance_reports.html_content
            # 8. Store JSON summary into compliance_reports.results
            if report_id:
                cursor.execute(
                    """
                    UPDATE compliance_reports
                    SET html_content = %s, results = %s, status = %s, updated_at = NOW()
                    WHERE id = %s AND engagement_id = %s
                    """,
                    (html, json.dumps(json_data), "ready", report_id, engagement_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO compliance_reports (
                        org_id, engagement_id, standard, title, results, html_content, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        org_id,
                        engagement_id,
                        "full_report",
                        report_context["title"],
                        json.dumps(json_data),
                        html,
                        "ready",
                    ),
                )
                row = cursor.fetchone()
                report_id = row["id"] if row else None

            conn.commit()

            return {
                "report_id": str(report_id) if report_id else None,
                "engagement_id": engagement_id,
                "findings_count": len(findings),
                "status": "ready",
            }

        except Exception as e:
            logger.error("Full report generation failed: %s", e)
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()


@app.task(bind=True, name="tasks.report.get_compliance_reports")
def get_compliance_reports(
    self,
    engagement_id: str,
    trace_id: str = None,
):
    """
    Get compliance reports for an engagement

    Args:
        engagement_id: Engagement ID
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "get_compliance_reports", trace_id):
        conn = connect(db_conn_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT
                    id,
                    standard,
                    title,
                    status,
                    created_at,
                    updated_at
                FROM compliance_reports
                WHERE engagement_id = %s
                ORDER BY created_at DESC
                """,
                (engagement_id,)
            )

            return [dict(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()
