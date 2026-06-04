"""OpenTelemetry tracing — replaces custom ExecutionSpan."""
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from utils.validation import validate_uuid

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str = "argus-workers"):
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)


tracer = trace.get_tracer(__name__)


class TracingError(Exception):
    """Raised when tracing operations fail"""
    pass


@dataclass
class ExecutionContext:
    trace_id: str
    engagement_id: str
    job_type: str
    start_time: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "engagement_id": self.engagement_id,
            "job_type": self.job_type,
            "start_time": self.start_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionContext":
        return cls(
            trace_id=data["trace_id"],
            engagement_id=data["engagement_id"],
            job_type=data["job_type"],
            start_time=data.get("start_time", time.time()),
        )


class TraceContext:
    _local = threading.local()

    @classmethod
    def set_context(cls, context: ExecutionContext) -> None:
        cls._local.current_context = context

    @classmethod
    def get_context(cls) -> ExecutionContext | None:
        return getattr(cls._local, 'current_context', None)

    @classmethod
    def get_trace_id(cls) -> str | None:
        context = cls.get_context()
        return context.trace_id if context else None

    @classmethod
    def clear_context(cls) -> None:
        cls._local.current_context = None

    @classmethod
    @contextmanager
    def with_context(cls, context: ExecutionContext):
        cls.set_context(context)
        try:
            yield context
        finally:
            cls.clear_context()


class StructuredLogger:
    EVENT_JOB_STARTED = "job_started"
    EVENT_TOOL_EXECUTED = "tool_executed"
    EVENT_PARSER_COMPLETED = "parser_completed"
    EVENT_INTELLIGENCE_DECISION = "intelligence_decision"

    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")

    def log(self, event_type: str, message: str, metadata: dict = None) -> None:
        from utils.logging_utils import ScanLogger
        trace_id = TraceContext.get_trace_id()
        context = TraceContext.get_context()
        slog = ScanLogger("tracing")

        if not trace_id:
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

        self._store_log(log_entry)
        slog.info(f"[{trace_id[:8]}] {event_type}: {message}")

    def _store_log(self, log_entry: dict) -> None:
        if not self.connection_string:
            return
        engagement_id = log_entry.get("engagement_id")
        if engagement_id:
            try:
                engagement_id = validate_uuid(engagement_id, "engagement_id")
            except ValueError:
                logger.error("Failed to store log: invalid engagement_id UUID: '%s'", engagement_id)
                return
        try:
            from database.connection import get_db
            db = get_db()
            conn = db.get_connection()
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
                db.release_connection(conn)
        except Exception as e:
            logger.error("Failed to store log: %s", e)

    def log_job_started(self, job_type: str, engagement_id: str, target: str = None) -> None:
        self.log(
            self.EVENT_JOB_STARTED,
            f"Job started: {job_type}",
            {"job_type": job_type, "engagement_id": engagement_id, "target": target},
        )

    def log_tool_executed(self, tool_name: str, arguments: list, duration_ms: int, success: bool, return_code: int = None) -> None:
        self.log(
            self.EVENT_TOOL_EXECUTED,
            f"Tool executed: {tool_name}",
            {"tool_name": tool_name, "arguments": arguments, "duration_ms": duration_ms, "success": success, "return_code": return_code},
        )

    def log_parser_completed(self, tool_name: str, findings_count: int, parse_time_ms: int = None) -> None:
        self.log(
            self.EVENT_PARSER_COMPLETED,
            f"Parser completed: {tool_name}",
            {"tool_name": tool_name, "findings_count": findings_count, "parse_time_ms": parse_time_ms},
        )

    def log_intelligence_decision(self, actions: list, findings_analyzed: int, reasoning: str = None) -> None:
        self.log(
            self.EVENT_INTELLIGENCE_DECISION,
            f"Intelligence decision: {len(actions)} actions generated",
            {"actions": actions, "findings_analyzed": findings_analyzed, "reasoning": reasoning},
        )


def _serialize_attr(v: Any):
    if isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return str(v)


class ExecutionSpan:
    SPAN_TOOL_EXECUTION = "tool_execution"
    SPAN_PARSING = "parsing"
    SPAN_INTELLIGENCE_EVALUATION = "intelligence_evaluation"
    SPAN_ORCHESTRATOR_STEP = "orchestrator_step"

    def __init__(self, connection_string: str = None, tracer=None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self._tracer = tracer if tracer is not None else trace.get_tracer(__name__)

    @contextmanager
    def span(self, span_name: str, metadata: dict = None):
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("tracing")

        trace_id = TraceContext.get_trace_id()
        start_time = time.time()
        metadata = metadata or {}

        with self._tracer.start_as_current_span(span_name) as otel_span:
            for k, v in metadata.items():
                otel_span.set_attribute(k, _serialize_attr(v))

            span_data = {
                "span_name": span_name,
                "trace_id": trace_id,
                "metadata": metadata,
                "start_time": start_time,
            }

            slog.info(f"SPAN START: {span_name}")

            try:
                yield span_data
            finally:
                end_time = time.time()
                duration_ms = int((end_time - start_time) * 1000)

                # NOTE: _store_span() was removed 2026-06-04 as part of B.06.
                # OTel exporter (console + OTLP) is the only persistence path.
                # If you need DB-backed spans, configure an OTLP collector to
                # write to Postgres instead.

                otel_span.set_attribute("duration_ms", duration_ms)
                slog.info(f"SPAN END: {span_name} ({duration_ms}ms)")

    # DEPRECATED: _store_span() removed 2026-06-04 (B.06).
    # The execution_spans table is preserved for backward compatibility
    # but is no longer written to. OTel exporter handles span persistence.
    # To re-enable DB-backed spans, configure an OTLP collector.
    #
    # The table definition in the database migration is marked @deprecated
    # and can be dropped once all deployments confirm they don't rely on it.

    def record_span(self, span_name: str, duration_ms: int, trace_id: str = None) -> None:
        """Record a span duration. Span is exported via OTel, not written to DB."""
        from utils.logging_utils import ScanLogger
        slog = ScanLogger("tracing")
        slog.info(f"SPAN RECORD: {span_name} ({duration_ms}ms)")


class TracingManager:
    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

    @staticmethod
    def generate_trace_id() -> str:
        return str(uuid.uuid4())

    def create_context(self, engagement_id: str, job_type: str, trace_id: str = None) -> ExecutionContext:
        if not trace_id:
            trace_id = self.generate_trace_id()
        return ExecutionContext(
            trace_id=trace_id,
            engagement_id=engagement_id,
            job_type=job_type,
        )

    @contextmanager
    def trace_execution(self, engagement_id: str, job_type: str, trace_id: str = None):
        context = self.create_context(engagement_id, job_type, trace_id)
        with TraceContext.with_context(context):
            self.logger.log_job_started(
                job_type=job_type,
                engagement_id=engagement_id,
            )
            try:
                yield context
            finally:
                pass

    def log(self, event_type: str, message: str, metadata: dict = None) -> None:
        self.logger.log(event_type, message, metadata)

    def span(self, span_name: str, metadata: dict = None):
        return self.span_recorder.span(span_name, metadata)


def get_trace_id() -> str | None:
    return TraceContext.get_trace_id()


def get_logger(connection_string: str = None) -> StructuredLogger:
    return StructuredLogger(connection_string)


def get_span_recorder(connection_string: str = None) -> ExecutionSpan:
    return ExecutionSpan(connection_string)


def get_tracing_manager(connection_string: str = None) -> TracingManager:
    return TracingManager(connection_string)
