"""
Runtime Package — Canonical runtime state, checkpointing, memory, governance,
shadow-mode validation, Redis caching, and in-flight migration.

Provides the execution layer for the agent-first architecture:
- EngagementState: Canonical runtime state for an engagement
- DecisionCheckpoint: Replay-safe decision persistence
- ExecutionEngine: Shared tool dispatch with middleware chain
- DeterministicRuntime: Fallback pipeline executor
- MemoryRetriever: 3-tier memory retrieval (Phase 5)
- Governance: Unified safety controls (Phase 6)
- shadow_compare: Shadow-mode validation (Phase 0, Principle 2)
- RedisStateCache: Fast-access Redis cache for EngagementState
- migrate_engagement: In-flight migration gate (Phase 0)
"""

from .engagement_state import EngagementState, ToolExecutionRecord
from .decision_checkpoint import DecisionCheckpoint, DecisionCheckpointRepository
from .execution_engine import ExecutionEngine
from .deterministic_runtime import DeterministicRuntime
from .memory import MemoryRetriever
from .governance import Governance
from .shadow_mode import (
    shadow_compare,
    get_shadow_stats,
    reset_shadow_stats,
)

__all__ = [
    "EngagementState",
    "ToolExecutionRecord",
    "DecisionCheckpoint",
    "DecisionCheckpointRepository",
    "ExecutionEngine",
    "DeterministicRuntime",
    "MemoryRetriever",
    "Governance",
    "shadow_compare",
    "get_shadow_stats",
    "reset_shadow_stats",
]
