"""
Tool execution context — formal dependency interface for recon/scan functions.

Instead of passing the entire Orchestrator object (whose interface is undefined
and includes private methods), extracted functions receive a ToolContext with
only the dependencies they need.
"""

from dataclasses import dataclass, field
from datetime import datetime
from tool_core._compat import utc
from typing import Any, Protocol

from tools.tool_runner import ToolRunner


class ParserProtocol(Protocol):
    """Minimal interface for what recon/scan need from a parser."""

    def parse(self, tool_name: str, raw_output: str) -> list[dict[str, Any]]: ...


class NormalizerProtocol(Protocol):
    """Minimal interface for normalizing findings."""

    def normalize(self, raw_finding: dict[str, Any], source_tool: str) -> Any: ...


@dataclass
class ToolContext:
    """
    Dependencies needed by tool execution functions (recon, scan, repo_scan).

    Replaces passing the entire Orchestrator instance, which exposed
    internal implementation details and made testing harder.
    """

    engagement_id: str
    tool_runner: ToolRunner
    parser: ParserProtocol
    normalizer: NormalizerProtocol
    ws_publisher: Any = None  # WebSocket event publisher (optional)
    llm_payload_generator: Any = None  # optional LLM payload generator

    @staticmethod
    def from_orchestrator(orchestrator) -> "ToolContext":
        """Extract a ToolContext from an Orchestrator instance."""
        return ToolContext(
            engagement_id=orchestrator.engagement_id,
            tool_runner=orchestrator.tool_runner,
            parser=orchestrator.parser,
            normalizer=orchestrator.normalizer,
            ws_publisher=orchestrator.ws_publisher,
            llm_payload_generator=getattr(orchestrator, "llm_payload_generator", None),
        )

    def publish_activity(
        self,
        tool: str,
        activity: str,
        status: str,
        items: int = None,
        details: str = None,
    ) -> None:
        """Publish a scanner activity event (no-op if no ws_publisher)."""
        if self.ws_publisher:
            self.ws_publisher.publish_scanner_activity(
                engagement_id=self.engagement_id,
                tool_name=tool,
                activity=activity,
                status=status,
                items_found=items,
                details=details,
            )

    def _normalize_finding(self, raw_finding: dict, tool: str) -> dict | None:
        if self.normalizer is not None:
            from orchestrator_pkg.normalizer_utils import normalize_finding

            return normalize_finding(self.normalizer, raw_finding, tool)  # type: ignore[arg-type]
        return raw_finding

    def normalize(self, raw_finding: dict, tool: str) -> dict | None:
        return self._normalize_finding(raw_finding, tool)


@dataclass(frozen=True)
class ScanContext:
    """Immutable context carried through the scan pipeline.

    All fields are set once at creation and never mutated.
    This eliminates the fragile practice of reaching into orchestrator
    or tool_runner internals to find org_id or trace_id.

    Replaces ad-hoc threading of org_id, trace_id, and DB connection info
    through pipeline functions. Set once at creation, frozen thereafter.
    """

    engagement_id: str
    org_id: str
    trace_id: str = ""
    target_url: str = ""
    aggressiveness: str = "default"
    db_connection_string: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(utc).isoformat())
