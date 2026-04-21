"""
Basic Self-Scan Task

Performs a lightweight security scan of the Argus platform itself.
This is a scheduled Celery task for continuous security monitoring.
"""

from celery_app import app
import logging

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.security.run_self_scan")
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
            f"Self-scan complete: {summary['total_findings']} findings "
            f"({summary['critical']} critical, {summary['high']} high)"
        )
        
        # Alert if critical findings
        if summary["critical"] > 0:
            logger.critical(
                f"CRITICAL: Self-scan found {summary['critical']} critical security issues!"
            )
        
        return {
            "status": "completed",
            "summary": summary,
            "findings_count": summary["total_findings"]
        }
        
    except Exception as e:
        logger.error(f"Self-scan failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
