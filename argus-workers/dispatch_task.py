#!/usr/bin/env python3
"""
Task Dispatcher for Argus

This script receives task parameters from stdin as JSON and dispatches them
to Celery properly using the Celery API. It bridges between the Node.js backend
and the Celery worker.

Usage: cat task.json | python dispatch_task.py
"""
import json
import sys
import os
import logging

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from celery_app import app
from dotenv import load_dotenv

load_dotenv()

# Ensure DATABASE_URL is available for tasks
if not os.getenv("DATABASE_URL"):
    # Try to read from the platform .env.local
    platform_env = os.path.join(os.path.dirname(PROJECT_ROOT), "argus-platform", ".env.local")
    if os.path.exists(platform_env):
        with open(platform_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if key == "DATABASE_URL":
                            os.environ[key] = value
                            break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# Map job types to Celery task names
TASK_NAME_MAP = {
    "recon": "tasks.recon.run_recon",
    "scan": "tasks.scan.run_scan",
    "analyze": "tasks.analyze.run_analysis",
    "report": "tasks.report.generate_report",
    "repo_scan": "tasks.repo_scan.run_repo_scan",
    "compliance_report": "tasks.report.generate_compliance_report",
    "full_report": "tasks.report.generate_full_report",
    "asset_discovery": "tasks.asset_discovery.run_asset_discovery",
    "asset_risk_scoring": "tasks.asset_discovery.update_asset_risk_scores",
}


def dispatch_task(job_type: str, args: list, task_id: str = None) -> dict:
    """
    Dispatch a task to Celery using the send_task API.

    Args:
        job_type: Type of job (recon, scan, etc.)
        args: Positional arguments for the task
        task_id: Optional custom task ID for tracking

    Returns:
        Dictionary with task ID and status
    """
    task_name = TASK_NAME_MAP.get(job_type)
    if not task_name:
        raise ValueError(f"Unknown job type: {job_type}")

    logger.info(f"Dispatching task {task_name} with args {args}")

    # Ensure the correct Python path is used by setting environment
    os.environ["PYTHONPATH"] = PROJECT_ROOT
    
    # Make sure DATABASE_URL is set
    if not os.getenv("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "postgresql://argus_user:argus_dev_password_change_in_production@localhost:5432/argus_pentest"

    # Send the task through Celery with the correct environment
    result = app.send_task(
        task_name,
        args=args,
        task_id=task_id,
    )

    logger.info(f"Task dispatched with ID: {result.id}")

    return {
        "task_id": result.id,
        "state": result.state,
    }


def main():
    """Read JSON from stdin and dispatch the task."""
    try:
        # Read JSON from stdin
        input_data = sys.stdin.read()
        if not input_data:
            logger.error("No input data received")
            sys.exit(1)

        job = json.loads(input_data)

        job_type = job.get("type")
        if not job_type:
            logger.error("Job missing 'type' field")
            sys.exit(1)

        # Build positional args based on job type
        args = []
        if job_type == "recon":
            args = [
                job["engagement_id"],
                job["target"],
                job["budget"],
                job.get("trace_id"),
            ]
        elif job_type == "scan":
            args = [
                job["engagement_id"],
                [job["target"]],
                job["budget"],
                job.get("trace_id"),
            ]
        elif job_type == "analyze":
            args = [
                job["engagement_id"],
                job["budget"],
                job.get("trace_id"),
            ]
        elif job_type == "report":
            args = [
                job["engagement_id"],
                job.get("trace_id"),
            ]
        elif job_type == "repo_scan":
            args = [
                job["engagement_id"],
                job.get("repo_url") or job.get("target"),
                job["budget"],
                job.get("trace_id"),
            ]
        elif job_type == "compliance_report":
            args = [
                job["engagement_id"],
                job.get("standard", "owasp_top10"),
                job.get("trace_id"),
            ]
        elif job_type == "full_report":
            args = [
                job["engagement_id"],
                job.get("report_id"),
                job.get("trace_id"),
            ]
        elif job_type == "asset_discovery":
            args = [
                job["engagement_id"],
                job.get("target"),
                job.get("org_id"),
                job.get("trace_id"),
            ]
        elif job_type == "asset_risk_scoring":
            args = [
                job.get("org_id"),
            ]
        else:
            raise ValueError(f"Unknown job type: {job_type}")

        result = dispatch_task(job_type, args)

        # Output result as JSON
        print(json.dumps(result))

    except Exception as e:
        logger.error(f"Error dispatching task: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()