"""
Tool execution context — formal dependency interface for recon/scan functions.

Instead of passing the entire Orchestrator object (whose interface is undefined
and includes private methods), extracted functions receive a ToolContext with
only the dependencies they need.
"""

from dataclasses import dataclass, field
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
    normalize_finding: Any = None  # optional wrapper: raw_finding, tool -> dict | None
    ws_publisher: Any = None  # WebSocket event publisher (optional)

    @staticmethod
    def from_orchestrator(orchestrator) -> "ToolContext":
        """Extract a ToolContext from an Orchestrator instance."""
        # Capture _normalize_finding as a bound method so the extracted
        # functions don't need access to the full orchestrator.
        normalize = getattr(orchestrator, "_normalize_finding", None)
        if normalize is not None:
            normalize = normalize.__get__(orchestrator, type(orchestrator))
        return ToolContext(
            engagement_id=orchestrator.engagement_id,
            tool_runner=orchestrator.tool_runner,
            parser=orchestrator.parser,
            normalizer=orchestrator.normalizer,
            normalize_finding=normalize,
            ws_publisher=orchestrator.ws_publisher,
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
        """Delegate to normalize_finding if available, else use normalizer directly."""
        if self.normalize_finding is not None:
            return self.normalize_finding(raw_finding, tool)
        if self.normalizer is not None:
            try:
                finding = self.normalizer.normalize(raw_finding, tool)
                return {
                    "type": finding.type,
                    "severity": finding.severity.value if hasattr(finding.severity, "value") else finding.severity,
                    "endpoint": finding.endpoint,
                    "evidence": finding.evidence,
                    "confidence": finding.confidence,
                    "source_tool": tool,
                }
            except Exception:
                return None
        return raw_finding

    def normalize(self, raw_finding: dict, tool: str) -> dict | None:
        """Normalize a raw finding. Uses normalize_finding wrapper if set."""
        if self.normalize_finding is not None:
            return self.normalize_finding(raw_finding, tool)
        try:
            finding = self.normalizer.normalize(raw_finding, tool)
            return {
                "type": finding.type,
                "severity": finding.severity.value
                if hasattr(finding.severity, "value")
                else finding.severity,
                "endpoint": finding.endpoint,
                "evidence": finding.evidence,
                "confidence": finding.confidence,
                "source_tool": tool,
            }
        except Exception:
            return None
