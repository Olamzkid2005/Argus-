"""
Unified event bus facade.

Routes all event publishing through a single entry point while keeping
the underlying implementations (StreamManager, WebSocketEventPublisher)
intact. This enforces consistency without requiring a rewrite.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """
    Unified event bus that delegates to underlying implementations.

    This is a facade — it doesn't replace StreamManager or
    WebSocketEventPublisher, but provides a single entry point
    that all code should use for event publishing.
    """

    def __init__(self):
        self._stream_manager = None
        self._ws_publisher = None
        self._initialized = False

    def initialize(self, stream_manager=None, ws_publisher=None):
        """Initialize with optional pre-configured instances."""
        self._stream_manager = stream_manager
        self._ws_publisher = ws_publisher
        self._initialized = True
        logger.info("EventBus initialized")

    def _lazy_init(self):
        """Lazy initialization with defaults."""
        if self._initialized:
            return
        try:
            from streaming import StreamManager
            self._stream_manager = StreamManager()
        except Exception as e:
            logger.warning("Failed to initialize StreamManager: %s", e)
        try:
            from websocket_events import WebSocketEventPublisher
            self._ws_publisher = WebSocketEventPublisher()
        except Exception as e:
            logger.warning("Failed to initialize WebSocketEventPublisher: %s", e)
        self._initialized = True

    def publish(
        self,
        event_type: str,
        data: dict[str, Any],
        engagement_id: str | None = None,
        channel: str = "default",
    ):
        """
        Publish an event through all available channels.

        Delegates to StreamManager (SSE subscribers) and
        WebSocketEventPublisher (Redis pub/sub).

        Args:
            event_type: Type of event (e.g., 'tool_start', 'finding')
            data: Event payload
            engagement_id: Optional engagement ID for scoped events
            channel: Channel hint (default, broadcast); currently unused
                     for StreamManager which routes by engagement_id.
        """
        self._lazy_init()

        published = False
        engagement_id = engagement_id or ""

        # Publish via StreamManager (in-process SSE queues)
        if self._stream_manager:
            try:
                from streaming import Event as StreamEvent

                event = StreamEvent(
                    type=event_type,
                    engagement_id=engagement_id,
                    data=data,
                )
                self._stream_manager.publish_event(event)
                published = True
            except Exception as e:
                logger.warning("StreamManager publish failed: %s", e)

        # Publish via WebSocketEventPublisher (Redis pub/sub)
        if self._ws_publisher and engagement_id:
            try:
                from datetime import UTC, datetime

                ws_event = {
                    "type": event_type,
                    "engagement_id": engagement_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": data,
                }
                publish_method = getattr(self._ws_publisher, "publish_event", None) or self._ws_publisher._publish_event
                publish_method(ws_event)
                published = True
            except AttributeError as e:
                logger.error("WebSocketEventPublisher has no publish_event or _publish_event method: %s", e)
            except Exception as e:
                logger.warning("WebSocket publish failed: %s", e)

        if not published:
            logger.debug("Event %s not published (no channels available)", event_type)

        return published

    def publish_tool_event(
        self, tool_name: str, status: str, engagement_id: str, **kwargs
    ):
        """Convenience method for tool lifecycle events."""
        return self.publish(
            f"tool_{status}",
            {"tool": tool_name, "status": status, **kwargs},
            engagement_id=engagement_id,
        )

    def publish_finding(self, finding: dict, engagement_id: str):
        """Convenience method for finding events."""
        return self.publish(
            "finding",
            {"finding": finding},
            engagement_id=engagement_id,
        )

    def publish_engagement_event(
        self,
        engagement_id: str,
        from_state: str,
        to_state: str,
        reason: str = "",
    ):
        """Convenience method for engagement state transitions."""
        return self.publish(
            "state_change",
            {"from": from_state, "to": to_state, "reason": reason},
            engagement_id=engagement_id,
        )


# Global singleton
event_bus = EventBus()
