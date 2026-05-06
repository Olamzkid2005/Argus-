"""
Celery Application Configuration for Argus Workers

This module configures the Celery application for distributed task execution
using Redis as the message broker and result backend.
"""

import datetime
import logging
import os
import sys

from celery import Celery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Ensure the project root is in the Python path so forked workers can find modules
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure tool binaries are in PATH for worker subprocesses
_venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin")
_go_bin = os.path.expanduser("~/go/bin")
_current_path = os.environ.get("PATH", "")
for _bin_dir in [_venv_bin, _go_bin]:
    if _bin_dir not in _current_path and os.path.isdir(_bin_dir):
        _current_path = f"{_bin_dir}:{_current_path}"
if _current_path != os.environ.get("PATH", ""):
    os.environ["PATH"] = _current_path


# Configure logging
def setup_logging():
    """Configure structured logging for the application with secrets redaction"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Enable automatic secrets redaction in logs
    try:
        from utils.logging_utils import setup_logging as setup_redaction

        setup_redaction()
    except ImportError:
        pass  # Redaction not available, continue without it
    return logging.getLogger(__name__)


logger = setup_logging()

# Get configuration from shared config (single source of truth)
from config.redis import REDIS_URL  # noqa: E402

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/0")

# Ensure required environment variables are set
if not os.getenv("DATABASE_URL"):
    # Try to read from platform .env.local
    platform_root = os.path.dirname(os.path.abspath(__file__))
    platform_env = os.path.join(
        os.path.dirname(platform_root), "argus-platform", ".env.local"
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
        "tasks.repo_scan",
        "tasks.llm_review",
        "tasks.maintenance",
        "tasks.self_scan",
        "tasks.asset_discovery",
        "tasks.scheduled",
        "tasks.replay",
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
    task_time_limit=600,  # 10 minutes hard limit (global default)
    # Task Retry Configuration
    task_autoretry_for=(ConnectionError, TimeoutError, OSError),
    task_retry_kwargs={"max_retries": 3},
    task_retry_backoff=True,  # Exponential backoff
    task_retry_backoff_max=600,  # Max 10 minutes between retries
    task_retry_jitter=True,  # Add randomness to backoff
    # Result Backend Configuration
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Store additional metadata
    result_compression="gzip",  # Compress results
    # Worker Configuration - Optimization
    worker_concurrency=int(os.getenv("CELERY_CONCURRENCY", "8")),  # Concurrent tasks
    worker_prefetch_multiplier=1,  # Don't pre-fetch — each task is long
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    worker_disable_rate_limits=False,
    worker_send_task_events=True,  # Enable task events
    worker_pool="prefork",  # Use prefork pool for CPU tasks
    # Broker Configuration
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=10,
    broker_transport_options={
        "visibility_timeout": 3600,
        "fanout_prefix": True,
        "fanout_patterns": True,
    },
    # Task Routes (for future queue separation)
    # Time limits are set per-task via @app.task decorator or globally above
    task_routes={
        "tasks.recon.*": {"queue": "recon"},
        "tasks.scan.*": {"queue": "scan"},
        "tasks.analyze.*": {"queue": "analyze"},
        "tasks.report.*": {"queue": "report"},
        "tasks.repo_scan.*": {"queue": "repo_scan"},
    },
    # Task Priority
    task_default_priority=5,
    task_inherit_parent_priority=True,
    # Beat Schedule (for periodic tasks)
    beat_schedule={
        # Run due scheduled engagements every 5 minutes
        "run-due-scheduled-scans": {
            "task": "tasks.scheduled.run_due_scans",
            "schedule": 300.0,  # every 5 minutes
        },
        # Clean up old results every hour
        "cleanup-old-results": {
            "task": "tasks.maintenance.cleanup_old_results",
            "schedule": 3600.0,
        },
        # Clean up failed engagements daily
        "cleanup-failed-engagements": {
            "task": "tasks.maintenance.cleanup_failed_engagements",
            "schedule": 86400.0,
        },
        # Run security self-scan daily
        "security-self-scan": {
            "task": "tasks.security.run_self_scan",
            "schedule": 86400.0,
        },
        # Cleanup old checkpoints weekly
        "cleanup-checkpoints": {
            "task": "tasks.maintenance.cleanup_checkpoints",
            "schedule": 604800.0,
        },
        # Refresh materialized views every 5 minutes
        "refresh-materialized-views": {
            "task": "tasks.maintenance.refresh_views",
            "schedule": 300.0,
        },
        # Worker health check every minute
        "worker-health-check": {
            "task": "tasks.maintenance.worker_health_check",
            "schedule": 60.0,
        },
        # Update nuclei templates daily (ensure new CVEs are detected)
        "update-nuclei-templates": {
            "task": "tasks.maintenance.update_nuclei_templates",
            "schedule": 86400.0,  # daily
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
        # Ensure project root is in sys.path (needed for forked/spawned workers on macOS)
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from dead_letter_queue import get_dlq
        from error_classifier import classify_error, log_classified_error
        from shutdown_handler import shutdown_handler

        classification = classify_error(exc, self.name)

        log_classified_error(
            classification=classification,
            task_id=task_id,
            task_name=self.name,
            error=exc,
            extra_context={"args": str(args), "kwargs": str(kwargs)},
        )

        # Send to DLQ if not retryable
        if not classification.should_retry:
            try:
                dlq = get_dlq()
                dlq.enqueue(
                    task_id=task_id,
                    task_name=self.name,
                    args=list(args),
                    kwargs=kwargs,
                    error_message=str(exc),
                    error_class=type(exc).__name__,
                    retry_count=self.request.retries if self.request else 0,
                    engagement_id=kwargs.get("engagement_id") if kwargs else None,
                )
            except Exception as e:
                logger.error(f"Failed to add task {task_id} to DLQ: {e}")

        # Handle shutdown-related failures
        if shutdown_handler.should_shutdown():
            shutdown_handler.handle_task_failure_on_shutdown(
                task_id=task_id,
                task_name=self.name,
                args=args,
                kwargs=kwargs,
                error=exc,
            )

        logger.error(f"Task {task_id} failed: {exc}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is retried"""
        logger.warning(
            f"Task {task_id} retrying (attempt {self.request.retries}): {exc}"
        )

    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds"""
        logger.info(f"Task {task_id} succeeded")

    def __call__(self, *args, **kwargs):
        """Wrap task execution with shutdown checking"""
        # Ensure project root is in sys.path (needed for forked/spawned workers on macOS)
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from health_monitor import get_health_monitor
        from shutdown_handler import shutdown_handler

        task_id = self.request.id if self.request else "unknown"

        # Register with shutdown handler
        shutdown_handler.register_task(task_id)

        # Update health metrics
        try:
            monitor = get_health_monitor()
            monitor.increment_tasks()
        except Exception as e:
            logger.warning("Failed to update health metrics: %s", e)

        try:
            # Check if shutdown is requested before starting
            if shutdown_handler.should_shutdown():
                logger.warning(f"Task {task_id} cancelled due to shutdown")
                raise Exception("Worker is shutting down")

            return self.run(*args, **kwargs)
        finally:
            shutdown_handler.unregister_task(task_id)


# Set base task class
app.Task = BaseTask


# ── Health check task ──
@app.task(bind=True, name="tasks.health.ping")
def ping_task(self):
    """Simple ping task to verify worker is alive and can execute tasks."""
    return {
        "status": "ok",
        "worker": self.request.hostname,
        "pid": os.getpid(),
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    }


if __name__ == "__main__":
    app.start()
