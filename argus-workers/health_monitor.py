"""
Worker Health Monitoring and Self-Healing

Monitors worker health metrics and performs self-healing actions.
"""

import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import psutil
import redis

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

    def __init__(self, worker_id: str | None = None, redis_url: str = None):
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.hostname = os.uname().nodename
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
            logger.warning(f"Failed to get system metrics: {e}")
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
            last_heartbeat=datetime.now(UTC).isoformat(),
            status=status,
            uptime_seconds=int(time.time() - self.start_time)
        )

        key = f"{self.REDIS_KEY_PREFIX}:{self.worker_id}"
        try:
            self.redis.hset(key, mapping={k: str(v) for k, v in asdict(health).items()})
            self.redis.expire(key, HEARTBEAT_TTL * 2)

            if status == "critical":
                logger.warning(f"Worker {self.worker_id} in CRITICAL state: {metrics}")

        except Exception as e:
            logger.error(f"Failed to send heartbeat: {e}")

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
                f"High memory usage ({metrics['memory_percent']:.1f}%), "
                "considering restart after current task"
            )
            return True

        # Too many open files
        if metrics["open_files"] > 1000:
            logger.warning(
                f"Too many open files ({metrics['open_files']}), "
                "suggesting restart"
            )
            return True

        return False

    def get_all_worker_health(self) -> list[WorkerHealth]:
        """Get health for all workers"""
        workers = []
        try:
            pattern = f"{self.REDIS_KEY_PREFIX}:*"
            for key in self.redis.scan_iter(match=pattern):
                data = self.redis.hgetall(key)
                if data:
                    workers.append(WorkerHealth(
                        worker_id=data.get(b"worker_id", b"").decode(),
                        hostname=data.get(b"hostname", b"").decode(),
                        pid=int(data.get(b"pid", 0)),
                        cpu_percent=float(data.get(b"cpu_percent", 0)),
                        memory_percent=float(data.get(b"memory_percent", 0)),
                        memory_mb=float(data.get(b"memory_mb", 0)),
                        tasks_processed=int(data.get(b"tasks_processed", 0)),
                        last_heartbeat=data.get(b"last_heartbeat", b"").decode(),
                        status=data.get(b"status", b"unknown").decode(),
                        uptime_seconds=int(data.get(b"uptime_seconds", 0))
                    ))
        except Exception as e:
            logger.error(f"Failed to get worker health: {e}")

        return workers

    def get_unhealthy_workers(self) -> list[WorkerHealth]:
        """Get list of unhealthy workers"""
        all_workers = self.get_all_worker_health()

        unhealthy = []
        now = datetime.now(UTC)

        for worker in all_workers:
            # Check heartbeat age
            try:
                last_beat = datetime.fromisoformat(worker.last_heartbeat)
                if (now - last_beat).total_seconds() > HEARTBEAT_TTL * 2:
                    worker.status = "dead"
                    unhealthy.append(worker)
                    continue
            except Exception:
                pass

            # Check status
            if worker.status in ("warning", "critical", "dead"):
                unhealthy.append(worker)

        return unhealthy

    def cleanup_dead_workers(self) -> int:
        """Remove stale worker entries from Redis"""
        removed = 0
        try:
            pattern = f"{self.REDIS_KEY_PREFIX}:*"
            now = datetime.now(UTC)

            for key in self.redis.scan_iter(match=pattern):
                data = self.redis.hgetall(key)
                if data:
                    last_beat = data.get(b"last_heartbeat", b"").decode()
                    try:
                        last_beat_time = datetime.fromisoformat(last_beat)
                        if (now - last_beat_time).total_seconds() > HEARTBEAT_TTL * 5:
                            self.redis.delete(key)
                            removed += 1
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Failed to cleanup dead workers: {e}")

        return removed


# Singleton instance
_health_monitor: WorkerHealthMonitor | None = None


def get_health_monitor(worker_id: str | None = None) -> WorkerHealthMonitor:
    """Get singleton health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = WorkerHealthMonitor(worker_id=worker_id)
    return _health_monitor
