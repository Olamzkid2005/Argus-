#!/usr/bin/env python3
"""
Task Dispatcher for Argus

This script receives task parameters from stdin as JSON and dispatches them
to Celery properly using the Celery API. It bridges between the Node.js backend
and the Celery worker.

Usage: cat task.json | python dispatch_task.py
"""

import json
import logging
import os
import sys

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

from celery_app import app
from job_schema import TASK_NAME_MAP, JobMessage

load_dotenv()

# Ensure DATABASE_URL is available for tasks
if not os.getenv("DATABASE_URL"):
    # Try to read from the platform .env.local
    platform_env = os.path.join(
        os.path.dirname(PROJECT_ROOT), "argus-platform", ".env.local"
    )
    if os.path.exists(platform_env):
        with open(platform_env) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if key == "DATABASE_URL":
                        os.environ[key] = value.strip()
                        break

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def dispatch_task(task_name: str, args: list, task_id: str = None) -> dict:
    """
    Dispatch a task to Celery using the send_task API.

    Args:
        job_type: Type of job (recon, scan, etc.)
        args: Positional arguments for the task
        task_id: Optional custom task ID for tracking

    Returns:
        Dictionary with task ID and status
    """
    logger.info(f"Dispatching task {task_name} with args {args}")

    # Ensure the correct Python path is used by setting environment
    os.environ["PYTHONPATH"] = PROJECT_ROOT

    # Make sure DATABASE_URL is set
    if not os.getenv("DATABASE_URL"):
        raise OSError(
            "DATABASE_URL environment variable is not set. "
            "Set it in .env.local or export it before running dispatch_task."
        )

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
        input_data = sys.stdin.read()
        if not input_data:
            logger.error("No input data received")
            sys.exit(1)

        data = json.loads(input_data)
        job = JobMessage.from_dict(data)

        if not job.type:
            logger.error("Job missing 'type' field")
            sys.exit(1)

        task_name = TASK_NAME_MAP[job.type]
        args = job.to_celery_args()

        result = dispatch_task(task_name, args)

        print(json.dumps(result))

    except Exception as e:
        logger.error(f"Error dispatching task: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
