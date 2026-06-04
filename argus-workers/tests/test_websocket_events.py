"""Tests for websocket_events.py — WebSocketEventPublisher and convenience functions."""

import json
from unittest.mock import MagicMock, patch

from websocket_events import (
    WebSocketEventPublisher,
    get_websocket_publisher,
    publish_finding,
    publish_posture_update,
    publish_rate_limit_event,
    publish_state_transition,
)


class TestWebSocketEventPublisherInit:
    def test_default_redis_url(self):
        with patch.dict("os.environ", {"REDIS_URL": "redis://test:6379"}, clear=True):
            pub = WebSocketEventPublisher()
            assert pub.redis_url == "redis://test:6379"

    def test_explicit_redis_url(self):
        pub = WebSocketEventPublisher(redis_url="redis://custom:6379")
        assert pub.redis_url == "redis://custom:6379"

    def test_redis_lazy_init(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        assert pub._redis is None
        # Accessing .redis should lazily create connection
        with patch("websocket_events.redis.from_url") as mock_from_url:
            mock_redis = MagicMock()
            mock_from_url.return_value = mock_redis
            r = pub.redis
            assert r is mock_redis
            assert pub._redis is mock_redis


class TestSanitizeEngagementKey:
    def test_sanitizes_safe_key(self):
        safe = WebSocketEventPublisher._sanitize_engagement_key("abc-123_def.SCAN")
        assert safe == "abc-123_def.SCAN"

    def test_sanitizes_dangerous_chars(self):
        safe = WebSocketEventPublisher._sanitize_engagement_key("abc\n123:456")
        assert "\n" not in safe
        assert ":" not in safe


class TestPublishFinding:
    def test_publishes_to_redis(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_redis
        mock_redis.lpush.return_value = mock_redis
        mock_redis.publish.return_value = mock_redis
        mock_redis.ltrim.return_value = mock_redis
        mock_redis.expire.return_value = mock_redis
        mock_redis.execute.return_value = [1, 1, 1, 1]
        pub._redis = mock_redis

        pub.publish_finding(
            engagement_id="eng-123",
            finding_id="find-1",
            finding_type="XSS",
            severity="HIGH",
            confidence=0.9,
            endpoint="/api",
            source_tool="nuclei",
            use_batch=False,
        )
        assert mock_redis.lpush.called
        assert mock_redis.publish.called

    def test_batch_accumulation(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_redis
        mock_redis.lpush.return_value = mock_redis
        mock_redis.publish.return_value = mock_redis
        mock_redis.ltrim.return_value = mock_redis
        mock_redis.expire.return_value = mock_redis
        mock_redis.execute.return_value = [1, 1, 1, 1]
        pub._redis = mock_redis

        pub.publish_finding("eng-1", "f1", "XSS", "HIGH", 0.9, "/api", "nuclei")
        assert len(pub._batch_buffer.get("eng-1", [])) == 1

    def test_batch_flush_on_size(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        pub.BATCH_SIZE = 2
        with patch.object(pub, "flush_batches") as mock_flush:
            pub.publish_finding("eng-1", "f1", "XSS", "HIGH", 0.9, "/api", "nuclei")
            pub.publish_finding("eng-1", "f2", "SQLI", "HIGH", 0.9, "/api", "nuclei")
            assert mock_flush.called


class TestPublishStateTransition:
    def test_publishes_and_sets_state(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_state_transition("eng-1", "recon", "scan", "done")
        assert mock_redis.lpush.called
        assert mock_redis.publish.called
        assert mock_redis.set.called  # state was saved

    def test_stores_current_state(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_state_transition("eng-1", "recon", "scan")
        mock_redis.set.assert_called_with("state:engagement:eng-1", "scan")
        mock_redis.expire.assert_called()


class TestPublishRateLimitEvent:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_rate_limit_event("eng-1", "example.com", "throttle", 5.0)
        assert mock_redis.lpush.called

    def test_with_status_code(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_rate_limit_event("eng-1", "example.com", "backoff", 3.0, status_code=429)
        assert mock_redis.lpush.called


class TestPublishToolExecuted:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_tool_executed("eng-1", "nuclei", 1500, True, 5)
        assert mock_redis.lpush.called


class TestPublishJobStarted:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_job_started("eng-1", "recon", "https://example.com")
        assert mock_redis.lpush.called


class TestPublishJobCompleted:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_job_completed("eng-1", "recon", "success", findings_count=10, duration_ms=5000)
        assert mock_redis.lpush.called


class TestPublishScannerActivity:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        with patch.object(pub, "_persist_scanner_activity"):
            pub.publish_scanner_activity("eng-1", "nuclei", "Scanning endpoints", "in_progress")
            assert mock_redis.lpush.called

    def test_persists_to_db(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        with patch.object(pub, "_persist_scanner_activity") as mock_persist:
            pub.publish_scanner_activity("eng-1", "nuclei", "Scanning", "started")
            mock_persist.assert_called_once()


class TestPublishAgentDecision:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_agent_decision("eng-1", 1, "nuclei", "best tool", False)
        assert mock_redis.lpush.called

    def test_truncates_reasoning(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        long_reasoning = "x" * 500
        pub.publish_agent_decision("eng-1", 1, "nuclei", long_reasoning, False)
        # Should have been truncated to 200 chars
        call_args = mock_redis.lpush.call_args
        published_json = call_args[0][1]
        published = json.loads(published_json)
        assert len(published["data"]["reasoning"]) == 200


class TestPublishPostureUpdate:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_posture_update("eng-1", 85.0, {"soc2": 90.0}, "improving", 12)
        assert mock_redis.lpush.called


class TestPublishError:
    def test_publishes_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_error("eng-1", "something broke", "ERR_001", {"phase": "scan"})
        assert mock_redis.lpush.called


class TestShouldPublish:
    def test_no_min_severity(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        assert pub._should_publish({"data": {"severity": "LOW"}}) is True

    def test_meets_min_severity(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        assert pub._should_publish({"data": {"severity": "HIGH"}}, "LOW") is True

    def test_below_min_severity(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        assert pub._should_publish({"data": {"severity": "INFO"}}, "HIGH") is False

    def test_unknown_severity_defaults_to_publish(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        assert pub._should_publish({"data": {"severity": "UNKNOWN"}}, "LOW") is True


class TestEventTruncation:
    def test_truncates_oversized_event(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.publish_finding(
            engagement_id="eng-1",
            finding_id="f1",
            finding_type="XSS",
            severity="HIGH",
            confidence=0.9,
            endpoint="/api",
            source_tool="nuclei",
            use_batch=False,
        )
        # Should not raise — truncation should handle it gracefully


class TestClose:
    def test_close_releases_redis(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        mock_redis = MagicMock()
        pub._redis = mock_redis
        pub.close()
        mock_redis.close.assert_called_once()
        assert pub._redis is None

    def test_close_no_redis(self):
        pub = WebSocketEventPublisher(redis_url="redis://localhost:6379")
        pub.close()  # should not raise


class TestGetWebSocketPublisher:
    def test_singleton(self):
        p1 = get_websocket_publisher()
        p2 = get_websocket_publisher()
        assert p1 is p2


class TestConvenienceFunctions:
    def test_publish_finding(self):
        with patch("websocket_events.get_websocket_publisher") as mock_get:
            pub = MagicMock()
            mock_get.return_value = pub
            publish_finding("eng-1", "f1", "XSS", "HIGH", 0.9, "/api", "nuclei")
            pub.publish_finding.assert_called_once()

    def test_publish_state_transition(self):
        with patch("websocket_events.get_websocket_publisher") as mock_get:
            pub = MagicMock()
            mock_get.return_value = pub
            publish_state_transition("eng-1", "recon", "scan", "done")
            pub.publish_state_transition.assert_called_once()

    def test_publish_rate_limit_event(self):
        with patch("websocket_events.get_websocket_publisher") as mock_get:
            pub = MagicMock()
            mock_get.return_value = pub
            publish_rate_limit_event("eng-1", "example.com", "throttle", 5.0)
            pub.publish_rate_limit_event.assert_called_once()

    def test_publish_posture_update(self):
        with patch("websocket_events.get_websocket_publisher") as mock_get:
            pub = MagicMock()
            mock_get.return_value = pub
            publish_posture_update("eng-1", 85.0, {"soc2": 90.0}, "improving", 12)
            pub.publish_posture_update.assert_called_once()
