"""
Tests for autoscale.py

Validates: Queue depth calculation, target worker logic, scaling decisions
"""
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from autoscale import AutoscaleConfig, CeleryAutoscale


class TestAutoscaleConfig:
    """Tests for AutoscaleConfig dataclass"""

    def test_default_values(self):
        """Test default configuration values"""
        config = AutoscaleConfig()
        assert config.min_workers == 2
        assert config.max_workers == 20
        assert config.target_queue_depth == 10
        assert config.scale_up_threshold == 1.5
        assert config.scale_down_threshold == 0.3
        assert config.scale_up_cooldown == 60
        assert config.scale_down_cooldown == 300
        assert config.queues == ["celery", "recon", "scan", "analyze", "report", "repo_scan"]

    def test_custom_queues(self):
        """Test custom queues configuration"""
        config = AutoscaleConfig(queues=["high", "low"])
        assert config.queues == ["high", "low"]


class TestCeleryAutoscale:
    """Tests for CeleryAutoscale class"""

    @pytest.fixture
    def mock_redis(self):
        """Fixture providing a mock Redis client"""
        return MagicMock()

    @pytest.fixture
    def mock_control(self):
        """Fixture providing a mock Celery Control"""
        return MagicMock()

    @pytest.fixture
    def scaler(self, mock_redis, mock_control):
        """Fixture providing a CeleryAutoscale with mocked dependencies"""
        with patch("autoscale.redis.from_url", return_value=mock_redis):
            with patch("autoscale.Control", return_value=mock_control):
                config = AutoscaleConfig(min_workers=2, max_workers=10, target_queue_depth=10)
                s = CeleryAutoscale(config)
                yield s

    def test_init(self, scaler, mock_redis, mock_control):
        """Test autoscale initialization"""
        assert scaler.config.min_workers == 2
        assert scaler.config.max_workers == 10
        assert scaler.current_workers == 2
        assert scaler.last_scale_up == 0
        assert scaler.last_scale_down == 0

    def test_get_queue_depths(self, scaler, mock_redis):
        """Test getting queue depths for all monitored queues"""
        mock_redis.llen.side_effect = [5, 0, 15, 3, 0, 0]

        depths = scaler.get_queue_depths()

        assert depths["celery"] == 5
        assert depths["recon"] == 0
        assert depths["scan"] == 15
        assert depths["analyze"] == 3
        assert depths["report"] == 0
        assert depths["repo_scan"] == 0
        assert mock_redis.llen.call_count == 6

    def test_get_queue_depths_failure(self, scaler, mock_redis):
        """Test get_queue_depths handles Redis failures gracefully"""
        mock_redis.llen.side_effect = Exception("Redis error")

        depths = scaler.get_queue_depths()

        assert all(depth == 0 for depth in depths.values())

    def test_get_active_worker_count(self, scaler, mock_control):
        """Test getting active worker count from Celery"""
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = {"worker1": {}, "worker2": {}}
        mock_control.inspect.return_value = mock_inspect

        count = scaler.get_active_worker_count()

        assert count == 2

    def test_get_active_worker_count_none(self, scaler, mock_control):
        """Test get_active_worker_count falls back when no stats"""
        mock_inspect = MagicMock()
        mock_inspect.stats.return_value = None
        mock_control.inspect.return_value = mock_inspect

        count = scaler.get_active_worker_count()

        assert count == scaler.current_workers

    def test_get_active_worker_count_failure(self, scaler, mock_control):
        """Test get_active_worker_count handles exceptions gracefully"""
        mock_control.inspect.side_effect = Exception("Celery error")

        count = scaler.get_active_worker_count()

        assert count == scaler.current_workers

    def test_calculate_target_workers_empty_queues(self, scaler):
        """Test target workers when all queues empty"""
        depths = dict.fromkeys(scaler.config.queues, 0)
        target = scaler.calculate_target_workers(depths)
        assert target == scaler.config.min_workers

    def test_calculate_target_workers_normal(self, scaler):
        """Test target workers calculation with moderate load"""
        depths = {"celery": 50, "recon": 30, "scan": 20, "analyze": 0, "report": 0, "repo_scan": 0}
        target = scaler.calculate_target_workers(depths)
        # total=100, target_depth=10 -> 100/10 + 1 = 11, clamped to max 10
        assert target == 10

    def test_calculate_target_workers_low_load(self, scaler):
        """Test target workers with low load stays at minimum"""
        depths = {"celery": 5, "recon": 0, "scan": 0, "analyze": 0, "report": 0, "repo_scan": 0}
        target = scaler.calculate_target_workers(depths)
        assert target == scaler.config.min_workers

    def test_calculate_target_workers_respects_max(self, scaler):
        """Test target workers does not exceed max_workers"""
        depths = dict.fromkeys(scaler.config.queues, 100)
        target = scaler.calculate_target_workers(depths)
        assert target == scaler.config.max_workers

    def test_scale_workers_scale_up(self, scaler, mock_control):
        """Test scaling up when target > current"""
        scaler.current_workers = 2
        with patch.object(scaler, "get_active_worker_count", return_value=2):
            with patch.object(scaler, "_start_workers") as mock_start:
                scaler.scale_workers(5)

        mock_start.assert_called_once_with(3)
        assert scaler.last_scale_up > 0
        assert scaler.current_workers == 5

    def test_scale_workers_scale_down(self, scaler, mock_control):
        """Test scaling down when target < current"""
        scaler.current_workers = 8
        with patch.object(scaler, "get_active_worker_count", return_value=8):
            with patch.object(scaler, "_stop_workers") as mock_stop:
                scaler.scale_workers(3)

        mock_stop.assert_called_once_with(5)
        assert scaler.last_scale_down > 0
        assert scaler.current_workers == 3

    def test_scale_workers_no_change(self, scaler):
        """Test no scaling when target == current"""
        scaler.current_workers = 4
        with patch.object(scaler, "get_active_worker_count", return_value=4):
            with patch.object(scaler, "_start_workers") as mock_start:
                with patch.object(scaler, "_stop_workers") as mock_stop:
                    scaler.scale_workers(4)

        mock_start.assert_not_called()
        mock_stop.assert_not_called()

    def test_scale_workers_scale_up_cooldown(self, scaler):
        """Test scale up respects cooldown"""
        scaler.current_workers = 2
        scaler.last_scale_up = time.time()
        with patch.object(scaler, "get_active_worker_count", return_value=2):
            with patch.object(scaler, "_start_workers") as mock_start:
                scaler.scale_workers(10)

        mock_start.assert_not_called()

    def test_scale_workers_scale_down_cooldown(self, scaler):
        """Test scale down respects cooldown"""
        scaler.current_workers = 10
        scaler.last_scale_down = time.time()
        with patch.object(scaler, "get_active_worker_count", return_value=10):
            with patch.object(scaler, "_stop_workers") as mock_stop:
                scaler.scale_workers(2)

        mock_stop.assert_not_called()

    @patch("autoscale.subprocess.Popen")
    @patch("autoscale.sys.executable", "/usr/bin/python")
    def test_start_workers(self, mock_popen, scaler):
        """Test starting worker processes via subprocess"""
        scaler._start_workers(3)

        assert mock_popen.call_count == 3
        call_args = mock_popen.call_args[1]
        assert call_args["cwd"] is not None
        assert call_args["stdout"] is not None
        assert call_args["stderr"] is not None

    @patch("autoscale.subprocess.Popen")
    def test_start_workers_failure(self, mock_popen, scaler):
        """Test _start_workers handles subprocess failures gracefully"""
        mock_popen.side_effect = Exception("Subprocess error")
        scaler._start_workers(1)
        # Should not raise

    def test_stop_workers(self, scaler, mock_control):
        """Test stopping workers via Celery control shutdown"""
        with patch("os.uname") as mock_uname:
            mock_uname.return_value = Mock(nodename="testhost")
            scaler._stop_workers(2)

        mock_control.shutdown.assert_called_once()

    def test_stop_workers_failure(self, scaler, mock_control):
        """Test _stop_workers handles Celery control failures gracefully"""
        mock_control.shutdown.side_effect = Exception("Celery error")
        with patch("os.uname") as mock_uname:
            mock_uname.return_value = Mock(nodename="testhost")
            scaler._stop_workers(1)
        # Should not raise

    def test_run_loop(self, scaler):
        """Test autoscaling run loop executes iterations"""
        call_count = 0

        def fake_get_queue_depths():
            nonlocal call_count
            call_count += 1
            return {"celery": 10}

        scaler.get_queue_depths = fake_get_queue_depths
        scaler.scale_workers = Mock()

        sleep_calls = 0
        def fake_sleep(interval):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 2:
                raise SystemExit("end test")

        with patch("autoscale.time.sleep", side_effect=fake_sleep):
            with pytest.raises(SystemExit):
                scaler.run(interval=30)

        assert scaler.scale_workers.call_count >= 1
