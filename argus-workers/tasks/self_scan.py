"""
Basic Self-Scan Task

Performs a lightweight security scan of the Argus platform itself.
This is a scheduled Celery task for continuous security monitoring.
"""

import logging

from celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    bind=True, name="tasks.security.run_self_scan", soft_time_limit=300, time_limit=360
)
def run_self_scan(self):
    """
    Run a basic security self-assessment of the Argus platform.

    This task:
    - Checks for exposed secrets
    - Validates security headers on API endpoints
    - Checks for known misconfigurations

    Returns:
        dict: Scan results with findings
    """
    from security_audit import SecurityAudit

    logger.info("Starting Argus platform self-scan")

    try:
        audit = SecurityAudit()
        report = audit.generate_report()

        # Log summary
        summary = report["summary"]
        logger.info(
            "Self-scan complete: %s findings (%s critical, %s high)",
            summary["total_findings"],
            summary["critical"],
            summary["high"],
        )

        # Alert if critical findings
        if summary["critical"] > 0:
            logger.critical(
                "CRITICAL: Self-scan found %s critical security issues!",
                summary["critical"],
            )

        return {
            "status": "completed",
            "summary": summary,
            "findings_count": summary["total_findings"],
        }

    except Exception as e:
        logger.error("Self-scan failed: %s", e)
        return {"status": "error", "error": str(e)}
