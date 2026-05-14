"""
Tracing Module - Structured logging and execution tracing

Provides trace_id generation, propagation, and structured logging
for distributed tracing across all worker components.

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 21.1, 21.2
"""
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from database.connection import connect
from utils.validation import validate_uuid


class TracingError(Exception):
    """Raised when tracing operations fail"""
    pass


@dataclass
class ExecutionContext:
    """
    Execution context that holds trace information.
    Propagated through all components during engagement execution.
    """
    trace_id: str
    engagement_id: str
    job_type: str
    start_time: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert context to dictionary for serialization"""
        return {
            "trace_id": self.trace_id,
            "engagement_id": self.engagement_id,
            "job_type": self.job_type,
            "start_time": self.start_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionContext":
        """Create context from dictionary"""
        return cls(
            trace_id=data["trace_id"],
            engagement_id=data["engagement_id"],
            job_type=data["job_type"],
            start_time=data.get("start_time", time.time()),
        )


class TraceContext:
    """
    Thread-local context for trace_id propagation.
    Uses threading.local() to ensure each thread has its own context,
    preventing race conditions in concurrent Celery workers.
    """
    _local = threading.local()

    @classmethod
    def set_context(cls, context: ExecutionContext) -> None:
        """Set the current execution context"""
        cls._local.current_context = context

    @classmethod
    def get_context(cls) -> ExecutionContext | None:
        """Get the current execution context"""
        return getattr(cls._local, 'current_context', None)

    @classmethod
    def get_trace_id(cls) -> str | None:
        """Get the current trace_id"""
        context = cls.get_context()
        return context.trace_id if context else None

    @classmethod
    def clear_context(cls) -> None:
        """Clear the current execution context"""
        cls._local.current_context = None

    @classmethod
    @contextmanager
    def with_context(cls, context: ExecutionContext):
        """Context manager for automatic context cleanup"""
        cls.set_context(context)
        try:
            yield context
        finally:
            cls.clear_context()


class StructuredLogger:
    """
    Structured logger that writes to execution_logs table.
    All logs include trace_id for distributed tracing.
    """

    # Event types as defined in requirements
    EVENT_JOB_STARTED = "job_started"
    EVENT_TOOL_EXECUTED = "tool_executed"
    EVENT_PARSER_COMPLETED = "parser_completed"
    EVENT_INTELLIGENCE_DECISION = "intelligence_decision"

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")

    def log(self, event_type: str, message: str, metadata: dict = None) -> None:
        """
        Log an event with trace context.

        Args:
            event_type: Type of event (job_started, tool_executed, etc.)
            message: Log message
            metadata: Additional metadata as dictionary
        """
        from utils.logging_utils import ScanLogger

        trace_id = TraceContext.get_trace_id()
        context = TraceContext.get_context()
        slog = ScanLogger("tracing")

        if not trace_id:
            # No trace context, log to console only
            slog.info(f"[NO_TRACE] {event_type}: {message}")
            return

        log_entry = {
            "trace_id": trace_id,
            "engagement_id": context.engagement_id if context else None,
            "event_type": event_type,
            "message": message,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Store in database
        self._store_log(log_entry)

        # Also print for debugging
        slog.info(f"[{trace_id[:8]}] {event_type}: {message}")

    def _store_log(self, log_entry: dict) -> None:
        """Store log entry in execution_logs table"""
        if not self.connection_string:
            return

        engagement_id = log_entry.get("engagement_id")
        # Validate UUID before DB insert to prevent InvalidTextRepresentation errors
        if engagement_id:
            try:
                engagement_id = validate_uuid(engagement_id, "engagement_id")
            except ValueError:
                # Non-fatal: skip DB logging for invalid UUIDs
                print(f"Failed to store log: invalid engagement_id UUID: '{engagement_id}'")
                return

        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    INSERT INTO execution_logs
                    (engagement_id, trace_id, event_type, message, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    engagement_id,
                    log_entry["trace_id"],
                    log_entry["event_type"],
                    log_entry["message"],
                    json.dumps(log_entry.get("metadata", {})),
                    log_entry.get("created_at"),
                ))
                conn.commit()
            finally:
                cursor.close()
                conn.close()
        except Exception as e:
            # Don't fail execution if logging fails
            print(f"Failed to store log: {e}")

    def log_job_started(self, job_type: str, engagement_id: str, target: str = None) -> None:
        """
        Log job_started event.

        Requirements: 20.3
        """
        self.log(
            self.EVENT_JOB_STARTED,
            f"Job started: {job_type}",
            {
                "job_type": job_type,
                "engagement_id": engagement_id,
                "target": target,
            }
        )

    def log_tool_executed(
        self,
        tool_name: str,
        arguments: list,
        duration_ms: int,
        success: bool,
        return_code: int = None
    ) -> None:
        """
        Log tool_executed event.

        Requirements: 20.4
        """
        self.log(
            self.EVENT_TOOL_EXECUTED,
            f"Tool executed: {tool_name}",
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "duration_ms": duration_ms,
                "success": success,
                "return_code": return_code,
            }
        )

    def log_parser_completed(
        self,
        tool_name: str,
        findings_count: int,
        parse_time_ms: int = None
    ) -> None:
        """
        Log parser_completed event.

        Requirements: 20.5
        """
        self.log(
            self.EVENT_PARSER_COMPLETED,
            f"Parser completed: {tool_name}",
            {
                "tool_name": tool_name,
                "findings_count": findings_count,
                "parse_time_ms": parse_time_ms,
            }
        )

    def log_intelligence_decision(
        self,
        actions: list,
        findings_analyzed: int,
        reasoning: str = None
    ) -> None:
        """
        Log intelligence_decision event.

        Requirements: 20.6
        """
        self.log(
            self.EVENT_INTELLIGENCE_DECISION,
            f"Intelligence decision: {len(actions)} actions generated",
            {
                "actions": actions,
                "findings_analyzed": findings_analyzed,
                "reasoning": reasoning,
            }
        )


class ExecutionSpan:
    """
    Represents an execution span for timing operations.
    Stores duration and metadata in execution_spans table.
    """

    # Span names as defined in requirements
    SPAN_TOOL_EXECUTION = "tool_execution"
    SPAN_PARSING = "parsing"
    SPAN_INTELLIGENCE_EVALUATION = "intelligence_evaluation"
    SPAN_ORCHESTRATOR_STEP = "orchestrator_step"

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")

    @contextmanager
    def span(self, span_name: str, metadata: dict = None):
        """
        Context manager for recording execution spans.
        Automatically records duration_ms.

        Args:
            span_name: Name of the span
            metadata: Additional metadata

        Yields:
            Span dictionary
        """
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("tracing")

        trace_id = TraceContext.get_trace_id()
        start_time = time.time()
        span_data = {
            "span_name": span_name,
            "trace_id": trace_id,
            "metadata": metadata or {},
            "start_time": start_time,
        }

        slog.info(f"SPAN START: {span_name}")

        try:
            yield span_data
        finally:
            # Calculate duration
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)

            # Store span
            if trace_id:
                self._store_span(trace_id, span_name, duration_ms)

            slog.info(f"SPAN END: {span_name} ({duration_ms}ms)")

    def _store_span(self, trace_id: str, span_name: str, duration_ms: int) -> None:
        """Store span in execution_spans table"""
        if not self.connection_string:
            return

        try:
            conn = connect(self.connection_string)
            cursor = conn.cursor()

            try:
                cursor.execute("""
                    INSERT INTO execution_spans
                    (trace_id, span_name, duration_ms, created_at)
                    VALUES (%s, %s, %s, %s)
                """, (
                    trace_id,
                    span_name,
                    duration_ms,
                    datetime.now(UTC).isoformat(),
                ))
                conn.commit()
            finally:
                cursor.close()
                conn.close()
        except Exception as e:
            # Don't fail execution if span storage fails
            print(f"Failed to store span: {e}")

    def record_span(self, span_name: str, duration_ms: int, trace_id: str = None) -> None:
        """
        Record a span that has already completed.

        Args:
            span_name: Name of the span
            duration_ms: Duration in milliseconds
            trace_id: Optional trace_id (uses current context if not provided)
        """
        if not trace_id:
            trace_id = TraceContext.get_trace_id()

        if trace_id:
            self._store_span(trace_id, span_name, duration_ms)


class TracingManager:
    """
    Central manager for tracing operations.
    Provides unified interface for logging and spans.
    """

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

    @staticmethod
    def generate_trace_id() -> str:
        """
        Generate a unique trace_id (UUID).

        Requirements: 20.1
        """
        return str(uuid.uuid4())

    def create_context(
        self,
        engagement_id: str,
        job_type: str,
        trace_id: str = None
    ) -> ExecutionContext:
        """
        Create a new execution context with trace_id.

        Args:
            engagement_id: Engagement ID
            job_type: Type of job (recon, scan, analyze, report)
            trace_id: Optional existing trace_id (generates new one if not provided)

        Returns:
            ExecutionContext instance
        """
        if not trace_id:
            trace_id = self.generate_trace_id()

        return ExecutionContext(
            trace_id=trace_id,
            engagement_id=engagement_id,
            job_type=job_type,
        )

    @contextmanager
    def trace_execution(
        self,
        engagement_id: str,
        job_type: str,
        trace_id: str = None
    ):
        """
        Context manager for traced execution.
        Sets up context, logs job_started, and ensures cleanup.

        Args:
            engagement_id: Engagement ID
            job_type: Type of job
            trace_id: Optional existing trace_id

        Yields:
            ExecutionContext
        """
        context = self.create_context(engagement_id, job_type, trace_id)

        with TraceContext.with_context(context):
            # Log job started
            self.logger.log_job_started(
                job_type=job_type,
                engagement_id=engagement_id,
            )

            try:
                yield context
            finally:
                # Context automatically cleared by context manager
                pass

    def log(self, event_type: str, message: str, metadata: dict = None) -> None:
        """Log an event"""
        self.logger.log(event_type, message, metadata)

    def span(self, span_name: str, metadata: dict = None):
        """Create an execution span"""
        return self.span_recorder.span(span_name, metadata)


# Convenience functions for easy import
def get_trace_id() -> str | None:
    """Get the current trace_id from context"""
    return TraceContext.get_trace_id()


def get_logger(connection_string: str = None) -> StructuredLogger:
    """Get a structured logger instance"""
    return StructuredLogger(connection_string)


def get_span_recorder(connection_string: str = None) -> ExecutionSpan:
    """Get an execution span recorder instance"""
    return ExecutionSpan(connection_string)


def get_tracing_manager(connection_string: str = None) -> TracingManager:
    """Get a tracing manager instance"""
    return TracingManager(connection_string)
