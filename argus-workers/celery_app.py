"""
Celery Application Configuration for Argus Workers

This module configures the Celery application for distributed task execution
using Redis as the message broker and result backend.
"""

import os
from celery import Celery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get configuration from environment
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/0")

# Create Celery application
app = Celery(
    "argus_workers",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "tasks.recon",
        "tasks.scan",
        "tasks.analyze",
        "tasks.report",
    ],
)

# Celery Configuration
app.conf.update(
    # Task Configuration
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task Execution
    task_acks_late=True,  # Acknowledge after task completion
    task_reject_on_worker_lost=True,  # Reject if worker dies
    task_track_started=True,  # Track when tasks start
    
    # Task Time Limits
    task_soft_time_limit=300,  # 5 minutes soft limit
    task_time_limit=600,  # 10 minutes hard limit
    
    # Task Retry Configuration
    task_autoretry_for=(Exception,),
    task_retry_kwargs={"max_retries": 3},
    task_retry_backoff=True,  # Exponential backoff
    task_retry_backoff_max=600,  # Max 10 minutes between retries
    task_retry_jitter=True,  # Add randomness to backoff
    
    # Result Backend Configuration
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Store additional metadata
    
    # Worker Configuration
    worker_prefetch_multiplier=1,  # Fetch one task at a time
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    worker_disable_rate_limits=False,
    
    # Broker Configuration
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    
    # Task Routes (for future queue separation)
    task_routes={
        "tasks.recon.*": {"queue": "recon"},
        "tasks.scan.*": {"queue": "scan"},
        "tasks.analyze.*": {"queue": "analyze"},
        "tasks.report.*": {"queue": "report"},
    },
    
    # Task Priority
    task_default_priority=5,
    task_inherit_parent_priority=True,
    
    # Beat Schedule (for periodic tasks)
    beat_schedule={
        # Example: Clean up old results every hour
        "cleanup-old-results": {
            "task": "tasks.maintenance.cleanup_old_results",
            "schedule": 3600.0,  # Every hour
        },
    },
)

# Task Base Class Configuration
class BaseTask(app.Task):
    """Base task class with common functionality"""
    
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails"""
        print(f"Task {task_id} failed: {exc}")
        # TODO: Log to database, send alerts, etc.
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried"""
        print(f"Task {task_id} retrying: {exc}")
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds"""
        print(f"Task {task_id} succeeded")

# Set base task class
app.Task = BaseTask

if __name__ == "__main__":
    app.start()
