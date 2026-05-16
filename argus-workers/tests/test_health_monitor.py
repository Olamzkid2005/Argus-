"""
Tests for health_monitor.py

Validates: Health check recording, heartbeat, self-healing, dead worker cleanup
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from health_monitor import (
    HEARTBEAT_TTL,
    WorkerHealthMonitor,
    get_health_monitor,
)


class TestWorkerHealthMonitor:
    """Tests for WorkerHealthMonitor class"""

    @pytest.fixture
    def mock_redis(self):
        """Fixture providing a mock Redis client"""
        return MagicMock()

    @pytest.fixture
    def monitor(self, mock_redis):
        """Fixture providing a WorkerHealthMonitor with mocked Redis and system info"""
        with (
            patch("health_monitor.redis.from_url", return_value=mock_redis),
            patch("os.getpid", return_value=12345),
            patch("os.uname") as mock_uname,
        ):
            mock_uname.return_value = Mock(nodename="testhost")
            m = WorkerHealthMonitor(worker_id="worker-1", redis_url="redis://mock:6379")
            m._redis = mock_redis
            yield m

    @pytest.fixture
    def mock_process(self):
        """Fixture providing a mock psutil.Process"""
        proc = MagicMock()
        proc.cpu_percent.return_value = 25.0
        proc.memory_percent.return_value = 40.0
        mem_info = MagicMock()
        mem_info.rss = 200 * 1024 * 1024  # 200 MB
        proc.memory_info.return_value = mem_info
        proc.open_files.return_value = [Mock(), Mock()]
        proc.connections.return_value = [Mock()]
        return proc

    def test_init(self, monitor):
        """Test monitor initialization sets correct attributes"""
        assert monitor.worker_id == "worker-1"
        assert monitor.hostname == "testhost"
        assert monitor.pid == 12345
        assert monitor.tasks_processed == 0

    def test_get_system_metrics(self, monitor, mock_process):
        """Test getting system metrics from psutil"""
        with patch("health_monitor.psutil.Process", return_value=mock_process):
            metrics = monitor.get_system_metrics()

        assert metrics["cpu_percent"] == 25.0
        assert metrics["memory_percent"] == 40.0
        assert metrics["memory_mb"] == 200.0
        assert metrics["open_files"] == 2
        assert metrics["connections"] == 1

    def test_get_system_metrics_failure(self, monitor):
        """Test get_system_metrics gracefully handles psutil failures"""
        with patch("health_monitor.psutil.Process", side_effect=Exception("psutil error")):
            metrics = monitor.get_system_metrics()

        assert metrics["cpu_percent"] == 0.0
        assert metrics["memory_percent"] == 0.0
        assert metrics["memory_mb"] == 0.0
        assert metrics["open_files"] == 0
        assert metrics["connections"] == 0

    def test_determine_status_healthy(self, monitor):
        """Test healthy status determination"""
        metrics = {"memory_percent": 50.0, "cpu_percent": 60.0}
        assert monitor.determine_status(metrics) == "healthy"

    def test_determine_status_warning(self, monitor):
        """Test warning status determination"""
        metrics = {"memory_percent": 80.0, "cpu_percent": 60.0}
        assert monitor.determine_status(metrics) == "warning"

        metrics = {"memory_percent": 50.0, "cpu_percent": 85.0}
        assert monitor.determine_status(metrics) == "warning"

    def test_determine_status_critical(self, monitor):
        """Test critical status determination"""
        metrics = {"memory_percent": 95.0, "cpu_percent": 60.0}
        assert monitor.determine_status(metrics) == "critical"

        metrics = {"memory_percent": 50.0, "cpu_percent": 96.0}
        assert monitor.determine_status(metrics) == "critical"

    def test_send_heartbeat(self, monitor, mock_redis, mock_process):
        """Test heartbeat stores health data in Redis"""
        with patch("health_monitor.psutil.Process", return_value=mock_process):
            monitor.send_heartbeat()

        mock_redis.hset.assert_called_once()
        mock_redis.expire.assert_called_once()
        call_args = mock_redis.hset.call_args[1]["mapping"]
        assert call_args["worker_id"] == "worker-1"
        assert call_args["hostname"] == "testhost"
        assert call_args["pid"] == "12345"
        assert float(call_args["cpu_percent"]) == 25.0
        assert call_args["status"] == "healthy"

    def test_send_heartbeat_critical(self, monitor, mock_redis):
        """Test heartbeat logs warning when critical"""
        proc = MagicMock()
        proc.cpu_percent.return_value = 96.0
        proc.memory_percent.return_value = 95.0
        mem_info = MagicMock()
        mem_info.rss = 500 * 1024 * 1024
        proc.memory_info.return_value = mem_info
        proc.open_files.return_value = []
        proc.connections.return_value = []

        with patch("health_monitor.psutil.Process", return_value=proc):
            monitor.send_heartbeat()

        assert mock_redis.hset.call_args[1]["mapping"]["status"] == "critical"

    def test_send_heartbeat_redis_failure(self, monitor, mock_redis):
        """Test heartbeat handles Redis failure gracefully"""
        mock_redis.hset.side_effect = Exception("Redis down")
        monitor.send_heartbeat()
        # Should not raise

    def test_increment_tasks(self, monitor):
        """Test incrementing processed task counter"""
        monitor.increment_tasks()
        assert monitor.tasks_processed == 1
        monitor.increment_tasks(4)
        assert monitor.tasks_processed == 5

    def test_check_self_heal_memory_pressure(self, monitor):
        """Test self-heal triggers on high memory usage"""
        metrics = {"memory_percent": 90.0, "open_files": 10}
        with patch.object(monitor, "get_system_metrics", return_value=metrics):
            result = monitor.check_self_heal()
        assert result is True

    def test_check_self_heal_open_files(self, monitor):
        """Test self-heal triggers on too many open files"""
        metrics = {"memory_percent": 50.0, "open_files": 1001}
        with patch.object(monitor, "get_system_metrics", return_value=metrics):
            result = monitor.check_self_heal()
        assert result is True

    def test_check_self_heal_healthy(self, monitor):
        """Test self-heal returns False when healthy"""
        metrics = {"memory_percent": 50.0, "open_files": 100}
        with patch.object(monitor, "get_system_metrics", return_value=metrics):
            result = monitor.check_self_heal()
        assert result is False

    def test_get_all_worker_health(self, monitor, mock_redis):
        """Test retrieving health for all workers"""
        mock_redis.scan_iter.return_value = [b"worker:health:worker-1", b"worker:health:worker-2"]
        mock_redis.hgetall.side_effect = [
            {
                b"worker_id": b"worker-1",
                b"hostname": b"host-a",
                b"pid": b"123",
                b"cpu_percent": b"10.0",
                b"memory_percent": b"20.0",
                b"memory_mb": b"100.0",
                b"tasks_processed": b"5",
                b"last_heartbeat": datetime.now(UTC).isoformat().encode(),
                b"status": b"healthy",
                b"uptime_seconds": b"300",
            },
            {
                b"worker_id": b"worker-2",
                b"hostname": b"host-b",
                b"pid": b"124",
                b"cpu_percent": b"30.0",
                b"memory_percent": b"40.0",
                b"memory_mb": b"200.0",
                b"tasks_processed": b"10",
                b"last_heartbeat": datetime.now(UTC).isoformat().encode(),
                b"status": b"warning",
                b"uptime_seconds": b"600",
            },
        ]

        workers = monitor.get_all_worker_health()

        assert len(workers) == 2
        assert workers[0].worker_id == "worker-1"
        assert workers[0].status == "healthy"
        assert workers[1].worker_id == "worker-2"
        assert workers[1].status == "warning"

    def test_get_all_worker_health_failure(self, monitor, mock_redis):
        """Test get_all_worker_health handles Redis failure gracefully"""
        mock_redis.scan_iter.side_effect = Exception("Redis error")
        workers = monitor.get_all_worker_health()
        assert workers == []

    def test_get_unhealthy_workers_dead(self, monitor, mock_redis):
        """Test detecting dead workers by stale heartbeat"""
        stale_time = (datetime.now(UTC) - timedelta(seconds=HEARTBEAT_TTL * 3)).isoformat()
        mock_redis.scan_iter.return_value = [b"worker:health:worker-dead"]
        mock_redis.hgetall.return_value = {
            b"worker_id": b"worker-dead",
            b"hostname": b"host-a",
            b"pid": b"123",
            b"cpu_percent": b"10.0",
            b"memory_percent": b"20.0",
            b"memory_mb": b"100.0",
            b"tasks_processed": b"5",
            b"last_heartbeat": stale_time.encode(),
            b"status": b"healthy",
            b"uptime_seconds": b"300",
        }

        unhealthy = monitor.get_unhealthy_workers()

        assert len(unhealthy) == 1
        assert unhealthy[0].worker_id == "worker-dead"
        assert unhealthy[0].status == "dead"

    def test_get_unhealthy_workers_critical(self, monitor, mock_redis):
        """Test detecting workers with critical status"""
        mock_redis.scan_iter.return_value = [b"worker:health:worker-crit"]
        mock_redis.hgetall.return_value = {
            b"worker_id": b"worker-crit",
            b"hostname": b"host-a",
            b"pid": b"123",
            b"cpu_percent": b"96.0",
            b"memory_percent": b"95.0",
            b"memory_mb": b"500.0",
            b"tasks_processed": b"5",
            b"last_heartbeat": datetime.now(UTC).isoformat().encode(),
            b"status": b"critical",
            b"uptime_seconds": b"300",
        }

        unhealthy = monitor.get_unhealthy_workers()

        assert len(unhealthy) == 1
        assert unhealthy[0].status == "critical"

    def test_get_unhealthy_workers_healthy(self, monitor, mock_redis):
        """Test healthy workers are not returned"""
        mock_redis.scan_iter.return_value = [b"worker:health:worker-ok"]
        mock_redis.hgetall.return_value = {
            b"worker_id": b"worker-ok",
            b"hostname": b"host-a",
            b"pid": b"123",
            b"cpu_percent": b"10.0",
            b"memory_percent": b"20.0",
            b"memory_mb": b"100.0",
            b"tasks_processed": b"5",
            b"last_heartbeat": datetime.now(UTC).isoformat().encode(),
            b"status": b"healthy",
            b"uptime_seconds": b"300",
        }

        unhealthy = monitor.get_unhealthy_workers()
        assert unhealthy == []

    def test_cleanup_dead_workers(self, monitor, mock_redis):
        """Test cleanup removes stale worker entries"""
        stale_time = (datetime.now(UTC) - timedelta(seconds=HEARTBEAT_TTL * 6)).isoformat()
        mock_redis.scan_iter.return_value = [b"worker:health:old-worker"]
        mock_redis.hgetall.return_value = {
            b"last_heartbeat": stale_time.encode(),
            b"worker_id": b"old-worker",
        }

        removed = monitor.cleanup_dead_workers()

        assert removed == 1
        mock_redis.delete.assert_called_once_with(b"worker:health:old-worker")

    def test_cleanup_dead_workers_none(self, monitor, mock_redis):
        """Test cleanup does not remove recent workers"""
        recent_time = datetime.now(UTC).isoformat()
        mock_redis.scan_iter.return_value = [b"worker:health:recent-worker"]
        mock_redis.hgetall.return_value = {
            b"last_heartbeat": recent_time.encode(),
            b"worker_id": b"recent-worker",
        }

        removed = monitor.cleanup_dead_workers()

        assert removed == 0
        mock_redis.delete.assert_not_called()

    def test_cleanup_dead_workers_failure(self, monitor, mock_redis):
        """Test cleanup handles Redis failure gracefully"""
        mock_redis.scan_iter.side_effect = Exception("Redis error")
        removed = monitor.cleanup_dead_workers()
        assert removed == 0


class TestSingleton:
    """Tests for singleton accessor"""

    def test_get_health_monitor_returns_same_instance(self):
        """Test get_health_monitor returns a singleton"""
        hm1 = get_health_monitor()
        hm2 = get_health_monitor()
        assert hm1 is hm2

    def test_get_health_monitor_returns_monitor(self):
        """Test get_health_monitor returns correct type"""
        hm = get_health_monitor()
        assert isinstance(hm, WorkerHealthMonitor)
