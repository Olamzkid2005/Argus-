"""
Runtime Package — Canonical runtime state, checkpointing, memory, and governance.

Provides the execution layer for the agent-first architecture:
- EngagementState: Canonical runtime state for an engagement
- DecisionCheckpoint: Replay-safe decision persistence
- ExecutionEngine: Shared tool dispatch with middleware chain
- DeterministicRuntime: Fallback pipeline executor
- MemoryRetriever: 3-tier memory retrieval (Phase 5)
- Governance: Unified safety controls (Phase 6)
"""

from .engagement_state import EngagementState, ToolExecutionRecord
from .decision_checkpoint import DecisionCheckpoint, DecisionCheckpointRepository
from .execution_engine import ExecutionEngine
from .deterministic_runtime import DeterministicRuntime
from .memory import MemoryRetriever
from .governance import Governance

__all__ = [
    "EngagementState",
    "ToolExecutionRecord",
    "DecisionCheckpoint",
    "DecisionCheckpointRepository",
    "ExecutionEngine",
    "DeterministicRuntime",
    "MemoryRetriever",
    "Governance",
]
