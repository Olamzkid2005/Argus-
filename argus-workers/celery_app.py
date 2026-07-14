"""
Celery Application Configuration for Argus Workers

This module configures the Celery application for distributed task execution
using Redis as the message broker and result backend.
"""

import datetime
import logging
import os
import re
import sys
import threading

from celery import Celery
from dotenv import load_dotenv

from tool_core._compat import utc
from tracing import setup_tracing

tracer = setup_tracing()

# Load environment variables
load_dotenv()

# Ensure the project root is in the Python path so forked workers can find modules
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure tool binaries are in PATH for worker subprocesses
_venv_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin")
_go_bin = os.environ.get("GO_BIN_PATH", os.path.expanduser("~/go/bin"))
_current_path = os.environ.get("PATH", "")
for _bin_dir in [_venv_bin, _go_bin]:
    if _bin_dir not in _current_path and os.path.isdir(_bin_dir):
        _current_path = f"{_bin_dir}:{_current_path}"
if _current_path != os.environ.get("PATH", ""):
    os.environ["PATH"] = _current_path

# ── Patterns for extracting engagement IDs from task arguments ──
# TypeScript TUI uses: ENG-{base36timestamp}-{base36seq}  (e.g. "ENG-m0v1w2x3-5")
# Python server uses: UUID v4                             (e.g. "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_ENGAGEMENT_ID_PATTERNS = [
    re.compile(r"^ENG-[a-z0-9]+-[a-z0-9]+$", re.IGNORECASE),  # ENG-* format
    re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
    ),  # UUID
]


def _looks_like_engagement_id(value: str) -> bool:
    """Check if a string looks like an Argus engagement ID (ENG-* or UUID format).

    Used by on_failure to extract engagement_id from positional task args
    when kwargs don't contain it directly.
    """
    return any(p.match(value) for p in _ENGAGEMENT_ID_PATTERNS)


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
        logging.getLogger(__name__).debug(
            "Logging redaction not available — continuing without it"
        )
    return logging.getLogger(__name__)


logger = setup_logging()

# ── Startup guard: AUTH_CHECKPOINT_KEY ──
# Auth checkpoints store session tokens (cookies, Bearer tokens, CSRF tokens)
# that MUST be encrypted at rest. The key must be set before any task runs.
# A loud warning is emitted at import time so missing config is obvious.
# (C-v4-02: mandatory encryption for all persisted auth state)
_AUTH_CHECKPOINT_KEY = os.environ.get("AUTH_CHECKPOINT_KEY")
# Gap 13.4: AUTH_CHECKPOINT_KEY enforcement — not set will prevent auth checkpoint
# persistence across worker restarts. Ferret-encrypted checkpoints are mandatory
# for any engagement that uses browser authentication.
if not _AUTH_CHECKPOINT_KEY:
    _missing_key_msg = (
        "AUTH_CHECKPOINT_KEY is not set. Auth checkpoints contain session "
        "tokens that MUST be encrypted at rest. Without this key, the agent "
        "CANNOT save authentication state across worker restarts.\n"
        "Generate a key with: python3 -c \"from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())\"\n"
        "Then set AUTH_CHECKPOINT_KEY=<your-key> in your environment.\n"
        "Continue without this key if you don't use browser authentication "
        "(auth checkpoints will be stored unencrypted as a fallback)."
    )
    logger.error("%s", _missing_key_msg)
else:
    # Validate the key is a valid Fernet key so the failure is loud at startup
    # rather than silently failing when the first checkpoint is saved.
    try:
        from cryptography.fernet import Fernet
        Fernet(_AUTH_CHECKPOINT_KEY.encode())
        logger.info("AUTH_CHECKPOINT_KEY is present and valid")
    except Exception as e:
        logger.error(
            "AUTH_CHECKPOINT_KEY is invalid: %s. Generate a valid Fernet key with: "
            "python3 -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"",
            e,
        )

# Get configuration from shared config (single source of truth)
from config.redis import REDIS_URL  # noqa: E402

# Use separate Redis DBs for broker (0) and result backend (1) to prevent
# result data from evicting queued messages when Redis memory is constrained.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")

# Ensure required environment variables are set
if not os.getenv("DATABASE_URL"):
    # Try to read from root .env (development fallback only)
    root_env = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.exists(root_env):
        try:
            with open(root_env) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if key == "DATABASE_URL":
                            os.environ[key] = value.strip()
                            break
        except OSError as e:
            logger.warning("Failed to read DATABASE_URL from %s: %s", root_env, e)

# ── Lazy migration flag ──
# Migrations are NOT run at module import time (Gap 11.1 fix). Instead, they
# run on the FIRST task execution via BaseTask.__call__, which calls
# ensure_migrations_applied() before executing the task body.
# This prevents an import-time crash when a migration fails and allows the
# worker to start up, log the failure, and handle it gracefully.
_migrations_applied_this_process = False
_migrations_lock = threading.Lock()


def ensure_migrations_applied() -> None:
    """Run pending database migrations lazily (not at module import time).

    This function is called by BaseTask.__call__() before the first task
    body executes. It runs migrations only once per process lifetime.

    Gap 11.1: Migrations no longer run at module import time, which means a
    migration failure won't crash the Celery worker at startup. The worker
    starts, logs the failure, and can still serve health checks and other
    non-DB tasks while the operator addresses the issue.

    Gap 11.2: Each migration file runs in its own transaction. If a migration
    fails, the _migrations table records it as 'failed'. The operator can
    revert using rollback_last_migration().
    """
    global _migrations_applied_this_process
    if _migrations_applied_this_process:
        return
    with _migrations_lock:
        if _migrations_applied_this_process:
            return
        try:
            from database.migrations.runner import run_migrations

            applied = run_migrations()
            _migrations_applied_this_process = True
            if applied:
                logger.info(
                    "Applied %d pending migration(s) on first task execution",
                    len(applied),
                )
        except Exception as e:
            logger.error(
                "Database migration failed on first task execution: %s. "
                "Worker will continue but DB queries may fail. "
                "Run migrations manually or fix the issue and restart.",
                e,
                exc_info=True,
            )
            # Don't set the flag — allow retry on next task
            raise


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
        "tasks.security",
        "tasks.asset_discovery",
        "tasks.scheduled",
        "tasks.replay",
        "tasks.diff",
        "tasks.posture",
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
        "tasks.posture.*": {"queue": "analyze"},
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
        # Clean up old DLQ items every 12 hours
        "cleanup-dlq": {
            "task": "tasks.maintenance.cleanup_dlq",
            "schedule": 43200.0,  # every 12 hours
        },
    },
)


# Task Base Class Configuration
class BaseTask(app.Task):  # type: ignore[name-defined]
    """Base task class with common functionality"""

    # Only retry on transient infrastructure errors — not on validation,
    # security, or permanent application errors. The error_classifier already
    # handles DLQ dispatch for non-retryable failures in on_failure().
    autoretry_for = (ConnectionError, TimeoutError, OSError, IOError)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True

    def on_failure(self, exc, task_id, args, kwargs, _einfo):
        """Called when task fails"""
        # Ensure project root is in sys.path (needed for forked/spawned workers on macOS)
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from dead_letter_queue import get_dlq
        from error_classifier import classify_error, log_classified_error
        from shutdown_handler import shutdown_handler

        classification = classify_error(exc, self.name)
        self._last_classification = classification

        log_classified_error(
            classification=classification,
            task_id=task_id,
            task_name=self.name,
            error=exc,
            extra_context={"args": str(args), "kwargs": str(kwargs)},
        )

        # Transition engagement to 'failed' when a task fails (catches SIGKILL/timeout too)
        # Check kwargs first (for send_task with keyword args), then args[0] (for positional calls)
        engagement_id = kwargs.get("engagement_id") if kwargs else None
        if not engagement_id and args and len(args) > 0:
            # Most Argus tasks take engagement_id as the first positional argument.
            # Accept both UUIDs (Python server) and ENG-* format (TypeScript TUI).
            potential_id = str(args[0]) if args[0] else None
            if potential_id and _looks_like_engagement_id(potential_id):
                engagement_id = potential_id
        if engagement_id:
            # H-03: State transitions are handled by task_context() — the single
            # authoritative handler. We only log and let task_context() manage
            # the _failed_transition_done flag.
            if getattr(self, "_failed_transition_done", False):
                logger.debug(
                    "Failure transition already handled for engagement %s by task_context",
                    engagement_id,
                )
            else:
                # If task_context was NOT used (e.g., on_failure from SIGKILL/timeout
                # where the task body never ran), attempt a safe transition.
                try:
                    from database.connection import db_cursor

                    with db_cursor() as cursor:
                        cursor.execute(
                            "SELECT status FROM engagements WHERE id = %s",
                            (engagement_id,),
                        )
                        row = cursor.fetchone()
                        current_state = row[0] if row else "created"
                    if current_state not in ("complete", "failed"):
                        from state_machine import EngagementStateMachine

                        sm = EngagementStateMachine(
                            engagement_id,
                            current_state=current_state,
                        )
                        if not sm.safe_transition(
                            "failed", f"Task {self.name} failed: {exc}"
                        ):
                            logger.debug(
                                "safe_transition skipped for engagement %s (already in terminal state)",
                                engagement_id,
                            )
                except Exception as e:
                    logger.warning(
                        "Failed to update engagement state on failure: %s", e
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
                logger.error("Failed to add task %s to DLQ: %s", task_id, e)

        # Handle shutdown-related failures
        if shutdown_handler.should_shutdown():
            shutdown_handler.handle_task_failure_on_shutdown(
                task_id=task_id,
                task_name=self.name,
                args=args,
                kwargs=kwargs,
                error=exc,
            )

        logger.error("Task %s failed: %s", task_id, exc)

    def retry(
        self,
        args=None,
        kwargs=None,
        exc=None,
        throw=True,
        eta=None,
        countdown=None,
        max_retries=None,
        default_retry_delay=None,
        **options,
    ):
        """Override retry to inject classification-based retry_delay_seconds."""
        if (
            countdown is None
            and hasattr(self, "_last_classification")
            and self._last_classification is not None
        ):
            cd = self._last_classification.retry_delay_seconds
            if cd is not None and cd > 0:
                countdown = cd
        return super().retry(
            args=args,
            kwargs=kwargs,
            exc=exc,
            throw=throw,
            eta=eta,
            countdown=countdown,
            max_retries=max_retries,
            default_retry_delay=default_retry_delay,
            **options,
        )

    def on_retry(self, exc, task_id, _args, _kwargs, _einfo):
        """Called when task is retried"""
        delay = ""
        if (
            hasattr(self, "_last_classification")
            and self._last_classification is not None
        ):
            cd = self._last_classification.retry_delay_seconds
            if cd is not None:
                delay = f" (delay={cd}s)"
            logger.warning(
                "Task %s retrying (attempt %s)%s: %s",
                task_id,
                self.request.retries,
                delay,
                exc,
            )

    def on_success(self, _retval, task_id, _args, _kwargs):
        """Called when task succeeds"""
        logger.info("Task %s succeeded", task_id)

    def __call__(self, *args, **kwargs):
        """Wrap task execution with shutdown checking and lazy migration"""
        # Reset the _failed_transition_done flag at the start of each task
        # invocation. This flag is set by task_context() when a failure
        # transition is handled. Without this reset, a previous invocation's
        # flag leak would cause the next invocation to skip its failure
        # transition, leaving engagements stuck in non-terminal states.
        # See: autonomous-red-team-readiness-review.md Part 3 §3
        self._failed_transition_done = False

        # Gap 11.1: Run migrations on first task execution (not at module import)
        if not _migrations_applied_this_process:
            try:
                ensure_migrations_applied()
            except Exception as _mig_err:
                logger.error(
                    "Migrations failed before task %s: %s — task will proceed "
                    "but DB operations may fail",
                    self.request.id if self.request else "unknown",
                    _mig_err,
                )

        # Ensure project root is in sys.path (needed for forked/spawned workers on macOS)
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from health_monitor import get_health_monitor
        from shutdown_handler import shutdown_handler

        task_id = self.request.id if self.request else "unknown"

        # Register with shutdown handler
        shutdown_handler.register_task(task_id)

        # Update health metrics and send heartbeat
        try:
            monitor = get_health_monitor()
            monitor.increment_tasks()
            monitor.send_heartbeat()
        except Exception as e:
            logger.warning("Failed to update health metrics: %s", e)

        try:
            # Check if shutdown is requested before starting
            if shutdown_handler.should_shutdown():
                logger.warning("Task %s cancelled due to shutdown", task_id)
                raise RuntimeError("Worker is shutting down")

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
        "timestamp": datetime.datetime.now(utc).isoformat(),
    }


if __name__ == "__main__":
    app.start()
