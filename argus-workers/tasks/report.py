"""
Celery tasks for reporting phase

Requirements: 20.1, 20.2, 20.3, 23.4, 23.5, 17.1, 17.2, 17.3, 17.4
"""
from celery_app import app
import os
import sys
import json
import importlib.util
from datetime import datetime, timedelta, UTC
from typing import List, Dict, Any, Optional

_workers_dir = "/Users/mac/Documents/Argus-/argus-workers"

# Robust module loader — avoids sys.path issues in Celery fork pool workers
def _load_module(module_name: str, rel_path: str = None):
    rel_path = rel_path or f"{module_name}.py"
    file_path = os.path.join(_workers_dir, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_orchestrator = _load_module("orchestrator")
Orchestrator = _orchestrator.Orchestrator

_tracing = _load_module("tracing")
TracingManager = _tracing.TracingManager
TraceContext = _tracing.TraceContext

import psycopg2
from psycopg2.extras import RealDictCursor

_distributed_lock = _load_module("distributed_lock")
LockContext = _distributed_lock.LockContext
DistributedLock = _distributed_lock.DistributedLock

_state_machine = _load_module("state_machine")
EngagementStateMachine = _state_machine.EngagementStateMachine

# Load compliance reporting
_compliance = _load_module("compliance_reporting")
ComplianceReportGenerator = _compliance.ComplianceReportGenerator
ComplianceStandard = _compliance.ComplianceStandard


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
            state_machine.transition("failed", f"Reporting failed: {str(e)}")
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
        conn = psycopg2.connect(db_conn_string)
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
        conn = psycopg2.connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (engagement_id,))
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
    conn = psycopg2.connect(db_conn_string)
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
    print(f"[REPORT EMAIL] Sending '{report_name}' to {', '.join(recipients)}")
    print(f"[REPORT DATA] {len(report_data.get('findings_summary', []))} severity groups, {len(report_data.get('engagements', []))} engagements")


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
        conn = psycopg2.connect(db_conn_string)
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

            # Store report in database
            cursor.execute(
                """
                INSERT INTO compliance_reports (
                    engagement_id, standard, title, report_data, html_content, status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
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
        conn = psycopg2.connect(db_conn_string)
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
