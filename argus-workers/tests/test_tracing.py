"""
Tests for tracing module

Validates: Requirements 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 21.1, 21.2
"""
import time
import uuid
from unittest.mock import MagicMock, patch

from tracing import (
    ExecutionContext,
    ExecutionSpan,
    StructuredLogger,
    TraceContext,
    TracingManager,
    get_logger,
    get_span_recorder,
    get_trace_id,
    get_tracing_manager,
)


class TestExecutionContext:
    """Tests for ExecutionContext"""

    def test_create_context(self):
        """Test creating an execution context"""
        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        assert context.trace_id == trace_id
        assert context.engagement_id == "550e8400-e29b-41d4-a716-446655440000"
        assert context.job_type == "recon"
        assert context.start_time is not None

    def test_context_to_dict(self):
        """Test converting context to dictionary"""
        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="scan"
        )

        result = context.to_dict()

        assert result["trace_id"] == trace_id
        assert result["engagement_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert result["job_type"] == "scan"
        assert "start_time" in result

    def test_context_from_dict(self):
        """Test creating context from dictionary"""
        trace_id = str(uuid.uuid4())
        data = {
            "trace_id": trace_id,
            "engagement_id": "550e8400-e29b-41d4-a716-446655440001",
            "job_type": "analyze",
            "start_time": time.time()
        }

        context = ExecutionContext.from_dict(data)

        assert context.trace_id == trace_id
        assert context.engagement_id == "550e8400-e29b-41d4-a716-446655440001"
        assert context.job_type == "analyze"


class TestTraceContext:
    """Tests for TraceContext (thread-local context management)"""

    def test_set_and_get_context(self):
        """Test setting and getting context"""
        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        TraceContext.set_context(context)
        result = TraceContext.get_context()

        assert result is not None
        assert result.trace_id == trace_id

        # Cleanup
        TraceContext.clear_context()

    def test_get_trace_id(self):
        """Test getting trace_id from context"""
        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        TraceContext.set_context(context)
        result = get_trace_id()

        assert result == trace_id

        # Cleanup
        TraceContext.clear_context()

    def test_get_trace_id_no_context(self):
        """Test getting trace_id when no context is set"""
        TraceContext.clear_context()
        result = get_trace_id()
        assert result is None

    def test_context_manager(self):
        """Test context manager for automatic cleanup"""
        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        with TraceContext.with_context(context):
            # Context should be available inside
            assert get_trace_id() == trace_id

        # Context should be cleared after exiting
        assert get_trace_id() is None


class TestTracingManager:
    """Tests for TracingManager"""

    def test_generate_trace_id(self):
        """Test trace_id generation (UUID format)"""
        trace_id = TracingManager.generate_trace_id()

        # Should be valid UUID
        uuid_obj = uuid.UUID(trace_id)
        assert str(uuid_obj) == trace_id

    def test_generate_unique_trace_ids(self):
        """Test that each generated trace_id is unique"""
        ids = [TracingManager.generate_trace_id() for _ in range(100)]

        # All should be unique
        assert len(set(ids)) == 100

    def test_create_context(self):
        """Test creating execution context"""
        manager = TracingManager()

        context = manager.create_context(
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        assert context.engagement_id == "550e8400-e29b-41d4-a716-446655440000"
        assert context.job_type == "recon"
        assert context.trace_id is not None

        # trace_id should be valid UUID
        uuid.UUID(context.trace_id)

    def test_create_context_with_existing_trace_id(self):
        """Test creating context with existing trace_id"""
        manager = TracingManager()
        existing_trace_id = str(uuid.uuid4())

        context = manager.create_context(
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="scan",
            trace_id=existing_trace_id
        )

        assert context.trace_id == existing_trace_id

    def test_trace_execution_context_manager(self):
        """Test trace_execution context manager"""
        manager = TracingManager()

        with manager.trace_execution("550e8400-e29b-41d4-a716-446655440000", "recon") as context:
            # Context should be set
            assert get_trace_id() == context.trace_id
            assert context.engagement_id == "550e8400-e29b-41d4-a716-446655440000"
            assert context.job_type == "recon"

        # Context should be cleared after
        assert get_trace_id() is None


class TestStructuredLogger:
    """Tests for StructuredLogger"""

    def test_log_event_types(self):
        """Test that all required event types are defined"""
        assert StructuredLogger.EVENT_JOB_STARTED == "job_started"
        assert StructuredLogger.EVENT_TOOL_EXECUTED == "tool_executed"
        assert StructuredLogger.EVENT_PARSER_COMPLETED == "parser_completed"
        assert StructuredLogger.EVENT_INTELLIGENCE_DECISION == "intelligence_decision"

    @patch('tracing.connect')
    def test_log_without_trace_context(self, mock_connect):
        """Test logging without trace context (should not fail)"""
        TraceContext.clear_context()

        logger = StructuredLogger()
        # Should not raise exception
        logger.log("test_event", "Test message")

        # Should not have attempted database connection
        mock_connect.assert_not_called()

    @patch('tracing.connect')
    def test_log_with_trace_context(self, mock_connect):
        """Test logging with trace context"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        with TraceContext.with_context(context):
            logger = StructuredLogger("test_connection_string")
            logger.log("test_event", "Test message", {"key": "value"})

        # Should have executed INSERT
        mock_cursor.execute.assert_called_once()

    @patch('tracing.connect')
    def test_log_job_started(self, mock_connect):
        """Test log_job_started convenience method"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        with TraceContext.with_context(context):
            logger = StructuredLogger("test_connection_string")
            logger.log_job_started("recon", "550e8400-e29b-41d4-a716-446655440000", "https://example.com")

        mock_cursor.execute.assert_called_once()

    @patch('tracing.connect')
    def test_log_tool_executed(self, mock_connect):
        """Test log_tool_executed convenience method"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="scan"
        )

        with TraceContext.with_context(context):
            logger = StructuredLogger("test_connection_string")
            logger.log_tool_executed(
                tool_name="nuclei",
                arguments=["-t", "cves"],
                duration_ms=1500,
                success=True,
                return_code=0
            )

        mock_cursor.execute.assert_called_once()

    @patch('tracing.connect')
    def test_log_parser_completed(self, mock_connect):
        """Test log_parser_completed convenience method"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        with TraceContext.with_context(context):
            logger = StructuredLogger("test_connection_string")
            logger.log_parser_completed(
                tool_name="nuclei",
                findings_count=5,
                parse_time_ms=100
            )

        mock_cursor.execute.assert_called_once()

    @patch('tracing.connect')
    def test_log_intelligence_decision(self, mock_connect):
        """Test log_intelligence_decision convenience method"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="analyze"
        )

        with TraceContext.with_context(context):
            logger = StructuredLogger("test_connection_string")
            logger.log_intelligence_decision(
                actions=[{"type": "deep_scan", "targets": ["https://example.com"]}],
                findings_analyzed=10,
                reasoning="High-value targets found"
            )

        mock_cursor.execute.assert_called_once()


class TestExecutionSpan:
    """Tests for ExecutionSpan"""

    def test_span_names(self):
        """Test that all required span names are defined"""
        assert ExecutionSpan.SPAN_TOOL_EXECUTION == "tool_execution"
        assert ExecutionSpan.SPAN_PARSING == "parsing"
        assert ExecutionSpan.SPAN_INTELLIGENCE_EVALUATION == "intelligence_evaluation"
        assert ExecutionSpan.SPAN_ORCHESTRATOR_STEP == "orchestrator_step"

    @patch('tracing.connect')
    def test_span_context_manager(self, mock_connect):
        """Test span context manager records duration"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        trace_id = str(uuid.uuid4())
        context = ExecutionContext(
            trace_id=trace_id,
            engagement_id="550e8400-e29b-41d4-a716-446655440000",
            job_type="recon"
        )

        with TraceContext.with_context(context):
            recorder = ExecutionSpan("test_connection_string")

            with recorder.span("test_span") as span_data:
                assert span_data["span_name"] == "test_span"
                assert span_data["trace_id"] == trace_id
                time.sleep(0.01)  # Small delay to ensure duration > 0

            # Should have executed INSERT
            mock_cursor.execute.assert_called_once()

            # Check the call arguments
            call_args = mock_cursor.execute.call_args
            assert "test_span" in str(call_args)

    @patch('tracing.connect')
    def test_span_without_trace_context(self, mock_connect):
        """Test span without trace context (should not store)"""
        TraceContext.clear_context()

        recorder = ExecutionSpan()

        with recorder.span("test_span"):
            pass

        # Should not have attempted database connection
        mock_connect.assert_not_called()


class TestConvenienceFunctions:
    """Tests for convenience functions"""

    def test_get_logger(self):
        """Test get_logger function"""
        logger = get_logger()
        assert isinstance(logger, StructuredLogger)

    def test_get_span_recorder(self):
        """Test get_span_recorder function"""
        recorder = get_span_recorder()
        assert isinstance(recorder, ExecutionSpan)

    def test_get_tracing_manager(self):
        """Test get_tracing_manager function"""
        manager = get_tracing_manager()
        assert isinstance(manager, TracingManager)


class TestIntegration:
    """Integration tests for tracing"""

    @patch('tracing.connect')
    def test_full_tracing_flow(self, mock_connect):
        """Test complete tracing flow from job start to completion"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor

        manager = TracingManager("test_connection_string")

        # Simulate a full job execution
        with manager.trace_execution("550e8400-e29b-41d4-a716-446655440000", "recon"):

            # Log job started
            manager.logger.log_job_started("recon", "550e8400-e29b-41d4-a716-446655440000", "https://example.com")

            # Record tool execution span
            with manager.span(ExecutionSpan.SPAN_TOOL_EXECUTION):
                time.sleep(0.01)

            # Log tool executed
            manager.logger.log_tool_executed(
                tool_name="nuclei",
                arguments=["-t", "cves"],
                duration_ms=1500,
                success=True
            )

            # Record parsing span
            with manager.span(ExecutionSpan.SPAN_PARSING):
                time.sleep(0.01)

            # Log parser completed
            manager.logger.log_parser_completed("nuclei", 5)

        # Should have made multiple database calls
        assert mock_cursor.execute.call_count >= 4
