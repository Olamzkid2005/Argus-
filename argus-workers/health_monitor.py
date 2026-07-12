"""
Worker Health Monitoring and Self-Healing

Monitors worker health metrics and performs self-healing actions.
Also tracks per-tool health from the tool_metrics table.
"""

import logging
import os
import platform as _platform
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from tool_core._compat import utc

import psutil
import redis
from typing import cast

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
HEARTBEAT_TTL = 60  # seconds


@dataclass
class WorkerHealth:
    """Worker health snapshot"""

    worker_id: str
    hostname: str
    pid: int
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    tasks_processed: int
    last_heartbeat: str
    status: str  # healthy, warning, critical, dead
    uptime_seconds: int


class WorkerHealthMonitor:
    """
    Monitors worker health and performs self-healing.

    Tracks:
    - CPU and memory usage
    - Heartbeat freshness
    - Task processing rate
    - Worker crashes/restarts
    """

    REDIS_KEY_PREFIX = "worker:health"

    @staticmethod
    def _sanitize_engagement_key(engagement_id: str) -> str:
        """Sanitize engagement_id for safe use in Redis keys.

        Prevents Redis key injection via malicious engagement_id values
        by stripping non-alphanumeric characters, newlines, colons, etc.
        """
        from utils.validation import sanitize_redis_key

        return sanitize_redis_key(engagement_id)

    def __init__(self, worker_id: str | None = None, redis_url: str = None):
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        try:
            self.hostname = _platform.uname().node
        except AttributeError:
            # Fallback if platform.uname() fails
            self.hostname = _platform.node() or "localhost"
        self.pid = os.getpid()
        self.redis_url = redis_url or REDIS_URL
        self._redis = None
        self.start_time = time.time()
        self.tasks_processed = 0

    @property
    def redis(self) -> redis.Redis:
        """Lazy Redis connection"""
        if self._redis is None:
            self._redis = redis.from_url(self.redis_url)
        assert self._redis is not None
        return self._redis

    def get_system_metrics(self) -> dict[str, float]:
        """Get current system metrics for this worker"""
        try:
            process = psutil.Process(self.pid)
            return {
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "memory_mb": process.memory_info().rss / (1024 * 1024),
                "open_files": len(process.open_files()),
                "connections": len(process.connections()),
            }
        except Exception as e:
            logger.warning("Failed to get system metrics: %s", e)
            return {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "memory_mb": 0.0,
                "open_files": 0,
                "connections": 0,
            }

    def determine_status(self, metrics: dict[str, float]) -> str:
        """Determine worker status based on metrics"""
        if metrics["memory_percent"] > 90 or metrics["cpu_percent"] > 95:
            return "critical"
        elif metrics["memory_percent"] > 75 or metrics["cpu_percent"] > 80:
            return "warning"
        return "healthy"

    def send_heartbeat(self):
        """Send heartbeat to Redis"""
        metrics = self.get_system_metrics()
        status = self.determine_status(metrics)

        health = WorkerHealth(
            worker_id=self.worker_id,
            hostname=self.hostname,
            pid=self.pid,
            cpu_percent=metrics["cpu_percent"],
            memory_percent=metrics["memory_percent"],
            memory_mb=metrics["memory_mb"],
            tasks_processed=self.tasks_processed,
            last_heartbeat=datetime.now(utc).isoformat(),
            status=status,
            uptime_seconds=int(time.time() - self.start_time),
        )

        key = f"{self.REDIS_KEY_PREFIX}:{self.worker_id}"
        try:
            self.redis.hset(key, mapping={k: str(v) for k, v in asdict(health).items()})
            self.redis.expire(key, HEARTBEAT_TTL * 2)

            if status == "critical":
                logger.warning(
                    "Worker %s in CRITICAL state: %s", self.worker_id, metrics
                )

        except Exception as e:
            logger.error("Failed to send heartbeat: %s", e)

    def increment_tasks(self, count: int = 1):
        """Increment processed task counter"""
        self.tasks_processed += count

    def check_self_heal(self) -> bool:
        """
        Check if worker needs self-healing and perform action.

        Returns:
            True if self-healing was performed
        """
        metrics = self.get_system_metrics()

        # Memory pressure - suggest restart
        if metrics["memory_percent"] > 85:
            logger.warning(
                "High memory usage (%s), considering restart after current task",
                metrics["memory_percent"],
            )
            return True

        # Too many open files
        if metrics["open_files"] > 1000:
            logger.warning(
                "Too many open files (%s), suggesting restart",
                metrics["open_files"],
            )
            return True

        return False

    def get_all_worker_health(self) -> list[WorkerHealth]:
        """Get health for all workers"""
        workers = []
        try:
            pattern = f"{self.REDIS_KEY_PREFIX}:*"
            for key in self.redis.scan_iter(match=pattern):
                raw_hgetall = self.redis.hgetall(key)
                data: dict[bytes, bytes] = cast(dict[bytes, bytes], raw_hgetall)
                if data:
                    try:
                        workers.append(
                            WorkerHealth(
                                worker_id=data.get(b"worker_id", b"").decode(),
                                hostname=data.get(b"hostname", b"").decode(),
                                pid=int(data.get(b"pid", 0)),
                                cpu_percent=float(data.get(b"cpu_percent", 0)),
                                memory_percent=float(data.get(b"memory_percent", 0)),
                                memory_mb=float(data.get(b"memory_mb", 0)),
                                tasks_processed=int(data.get(b"tasks_processed", 0)),
                                last_heartbeat=data.get(
                                    b"last_heartbeat", b""
                                ).decode(),
                                status=data.get(b"status", b"unknown").decode(),
                                uptime_seconds=int(data.get(b"uptime_seconds", 0)),
                            )
                        )
                    except Exception:
                        logger.debug("Skipping malformed worker health entry: %s", key)
        except Exception as e:
            logger.error("Failed to fetch worker health: %s", e)

        return workers

    def get_unhealthy_workers(self) -> list[WorkerHealth]:
        """Get list of unhealthy workers"""
        all_workers = self.get_all_worker_health()

        unhealthy = []
        now = datetime.now(utc)

        for worker in all_workers:
            # Check heartbeat age
            try:
                last_beat = datetime.fromisoformat(worker.last_heartbeat)
                if (now - last_beat).total_seconds() > HEARTBEAT_TTL * 2:
                    worker.status = "dead"
                    unhealthy.append(worker)
                    continue
            except (ValueError, OSError):
                logger.debug(
                    "Skipping worker with unparseable heartbeat: %s", worker.worker_id
                )

            # Check status
            if worker.status in ("warning", "critical", "dead"):
                unhealthy.append(worker)

        return unhealthy

    def cleanup_dead_workers(self) -> int:
        """Remove stale worker entries from Redis"""
        removed = 0
        try:
            pattern = f"{self.REDIS_KEY_PREFIX}:*"
            now = datetime.now(utc)

            for key in self.redis.scan_iter(match=pattern):
                raw_hgetall = self.redis.hgetall(key)
                data: dict[bytes, bytes] = cast(dict[bytes, bytes], raw_hgetall)
                if data:
                    last_beat = data.get(b"last_heartbeat", b"").decode()
                    try:
                        last_beat_time = datetime.fromisoformat(last_beat)
                        if (now - last_beat_time).total_seconds() > HEARTBEAT_TTL * 5:
                            self.redis.delete(key)
                            removed += 1
                    except ValueError:
                        logger.debug(
                            "Skipping worker with unparseable heartbeat: %s", key
                        )

        except Exception as e:
            logger.error("Failed to cleanup dead workers: %s", e)

        return removed


# Singleton instance
_health_monitor: WorkerHealthMonitor | None = None
_health_monitor_lock = threading.Lock()


def get_health_monitor(worker_id: str | None = None) -> WorkerHealthMonitor:
    """Get singleton health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        with _health_monitor_lock:
            if _health_monitor is None:
                _health_monitor = WorkerHealthMonitor(worker_id=worker_id)
    return _health_monitor


@dataclass
class ToolHealth:
    """Health snapshot for a single security tool."""

    tool_name: str
    success_rate_24h: float
    avg_duration_seconds: float
    total_runs_24h: int
    last_success_at: str | None
    consecutive_failures: int
    status: str  # healthy | degraded | down


class ToolHealthTracker:
    """Queries tool_metrics to surface per-tool health scores."""

    _db_conn: str | None = None

    def __init__(self, db_connection_string: str | None = None):
        self._db_conn = db_connection_string or os.getenv("DATABASE_URL")

    def get_tool_health(self) -> list[ToolHealth]:
        """Query tool_metrics for the last 24 hours and return per-tool health."""
        conn = None
        cursor = None
        db = None
        try:
            from database.connection import get_db

            db = get_db()
            conn = db.get_connection()
            cursor = conn.cursor()
            cutoff = datetime.now(utc) - timedelta(hours=24)

            cursor.execute(
                """
                SELECT
                    tool_name,
                    COUNT(*) AS total_runs,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0) AS success_rate,
                    AVG(duration_ms)::float / 1000.0 AS avg_duration_sec,
                    MAX(CASE WHEN success THEN created_at ELSE NULL END) AS last_success_at
                FROM tool_metrics
                WHERE created_at >= %s
                GROUP BY tool_name
                ORDER BY tool_name
            """,
                (cutoff,),
            )
            rows = cursor.fetchall()

            # Count consecutive failures per tool from recent runs
            cursor.execute(
                """
                SELECT tool_name, success
                FROM tool_metrics
                WHERE created_at >= %s
                ORDER BY tool_name, created_at DESC
            """,
                (cutoff,),
            )
            all_metrics = cursor.fetchall()

            # Compute consecutive failures per tool (newest-first order).
            # Data is ordered by tool_name, created_at DESC. For each tool,
            # count failures from newest to oldest until a success is found.
            cons_failures: dict[str, int] = {}
            finalized_tools: set[str] = set()
            for row in all_metrics:
                tool = row[0]
                success = row[1]

                # Skip tools we've already finalized (found a success in their history)
                if tool in finalized_tools:
                    continue

                if tool not in cons_failures:
                    cons_failures[tool] = 0

                if not success:
                    cons_failures[tool] += 1
                else:
                    # Success found for this tool — stop counting failures for it
                    finalized_tools.add(tool)

            results = []
            for row in rows:
                (
                    tool_name,
                    total_runs,
                    success_rate,
                    avg_duration_sec,
                    last_success_at,
                ) = row
                if success_rate is None:
                    success_rate = 0.0
                consecutive = cons_failures.get(tool_name, 0)

                if success_rate < 0.5 or consecutive >= 5:
                    status = "down"
                elif success_rate < 0.8 or consecutive >= 3:
                    status = "degraded"
                else:
                    status = "healthy"

                results.append(
                    ToolHealth(
                        tool_name=tool_name,
                        status=status,
                        success_rate_24h=success_rate,
                        avg_duration_seconds=avg_duration_sec,
                        total_runs_24h=total_runs,
                        last_success_at=last_success_at,
                        consecutive_failures=consecutive,
                    )
                )
            return results
        except Exception as e:
            logger.warning("Tool health query failed: %s", e)
            return []
        finally:
            if cursor:
                cursor.close()
            if conn and db:
                db.release_connection(conn)


_tool_health_tracker: ToolHealthTracker | None = None
_tool_health_tracker_lock = threading.Lock()


def get_tool_health_tracker(db_conn: str | None = None) -> ToolHealthTracker:
    """Get singleton tool health tracker instance."""
    global _tool_health_tracker
    if _tool_health_tracker is None:
        with _tool_health_tracker_lock:
            if _tool_health_tracker is None:
                _tool_health_tracker = ToolHealthTracker(db_connection_string=db_conn)
    return _tool_health_tracker
