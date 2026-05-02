"""
Celery task for replaying failed tasks from the Dead Letter Queue.

Keeps the Celery dependency out of dead_letter_queue.py,
breaking the circular import between celery_app and dead_letter_queue.
"""

import json
import logging

from celery_app import app
from dead_letter_queue import get_dlq

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.replay.replay_dlq_task")
def replay_dlq_task(self, task_id: str) -> bool:
    """
    Find a failed task in the DLQ and re-dispatch it to Celery.

    Args:
        task_id: The task ID to replay

    Returns:
        True if replay initiated successfully
    """
    dlq = get_dlq()
    task_data = dlq.get_task_by_id(task_id)
    if not task_data:
        logger.warning(f"Task {task_id} not found in DLQ")
        return False

    try:
        app.send_task(
            task_data["task_name"],
            args=task_data["args"],
            kwargs=task_data["kwargs"],
            task_id=task_id + ".replay",
        )
        logger.info(f"Replayed task {task_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to replay task {task_id}: {e}")
        return False
