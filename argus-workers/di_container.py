"""
Dependency Injection Container — per-engagement scope.

Provides scoped service instantiation without a DI framework.
Key design:
  - One container per engagement (scoped lifecycle, no state leaks)
  - No-op defaults for optional providers (everything works out of the box)
  - Factory override hook for customization (test mocking, Pro edition)
  - AuditSession is NOT stored here — passed per-step for parallel safety

Usage:
    from di_container import get_or_create_container, remove_container

    container = get_or_create_container(engagement_id, db_url="...")
    result = container.tool_runner.run("nuclei", ["-u", target])

    # Clean up when engagement completes
    remove_container(engagement_id)

Stolen from: Shannon's apps/worker/src/services/container.ts
Pattern: Per-workflow DI container with explicit injection, no-op defaults,
         and a factory override hook.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ── Provider interfaces (protocols) ──


class OutputProvider:
    """Interface for persisting step outputs.

    Default no-op implementation — override to store in DB or S3.
    """

    async def write(self, _step_name: str, content: str) -> None:
        """Write output for a step."""

    async def read(self, _step_name: str) -> str | None:
        """Read output for a step. Returns None if not found."""
        return None

    async def exists(self, _step_name: str) -> bool:
        """Check if output exists for a step."""
        return False


class TemplateProvider:
    """Interface for loading and rendering templates.

    Default no-op implementation — override to load from files/DB.
    """

    async def load(self, template_name: str, _variables: dict[str, str]) -> str:
        """Load and render a template."""
        return f"Template: {template_name}"


# ── Container dependencies ──


@dataclass
class ContainerDependencies:
    """Dependencies for creating a Container."""

    db_url: str | None = None
    redis_url: str | None = None
    engagement_id: str | None = None
    output_provider: OutputProvider | None = None
    template_provider: TemplateProvider | None = None
    tool_timeout: int = 300
    max_retries: int = 3
    log_level: str = "INFO"


# ── Container ──


class Container:
    """Per-engagement DI container.

    Holds all service instances for one engagement lifecycle.
    Services are instantiated once and reused across phases/steps.

    NOTE: AuditSession-like stateful objects are NOT stored here.
    They are passed per-step to support parallel execution safety.
    """

    def __init__(self, deps: ContainerDependencies) -> None:
        self.deps = deps
        self.engagement_id = deps.engagement_id
        self.db_url = deps.db_url
        self.redis_url = deps.redis_url
        self.tool_timeout = deps.tool_timeout
        self.max_retries = deps.max_retries

        # Providers — no-op defaults when not provided
        self.output_provider = deps.output_provider or OutputProvider()
        self.template_provider = deps.template_provider or TemplateProvider()

        # Lazily initialized services
        self._tool_runner = None
        self._llm_client = None
        self._checkpoint_manager = None

    @property
    def tool_runner(self):
        """Get or create ToolRunner instance."""
        if self._tool_runner is None:
            from tools.tool_runner import ToolRunner
            self._tool_runner = ToolRunner(
                connection_string=self.db_url,
                engagement_id=self.engagement_id,
            )
        return self._tool_runner

    @property
    def llm_client(self):
        """Get or create LLMClient instance."""
        if self._llm_client is None:
            try:
                from llm_client import LLMClient
                redis_url = self.redis_url or "redis://localhost:6379"
                self._llm_client = LLMClient(redis_url=redis_url)
            except Exception as e:
                logger.warning(f"LLM client not available: {e}")
                self._llm_client = None
        return self._llm_client

    @property
    def checkpoint_manager(self):
        """Get or create CheckpointManager instance."""
        if self._checkpoint_manager is None and self.db_url:
            from checkpoint_manager import CheckpointManager
            self._checkpoint_manager = CheckpointManager(self.db_url)
        return self._checkpoint_manager


# ── Container factory with override hook ──

# Default factory: creates a plain Container
ContainerFactory = Callable[[ContainerDependencies], Container]

def _factory(deps):
    return Container(deps)


def set_container_factory(factory: ContainerFactory) -> None:
    """Override the default container factory.

    Call once at worker startup to inject custom implementations.
    Useful for testing (provide mock services) or Pro edition overrides.

    Args:
        factory: A callable that takes ContainerDependencies and returns Container.
    """
    global _factory
    _factory = factory
    logger.info("Container factory overridden")


#: Map of engagement_id to Container instance.
_containers: dict[str, Container] = {}


def get_or_create_container(
    engagement_id: str,
    db_url: str | None = None,
    redis_url: str | None = None,
    **kwargs,
) -> Container:
    """Get or create a Container for an engagement.

    Args:
        engagement_id: Engagement ID to scope the container.
        db_url: Optional database URL.
        redis_url: Optional Redis URL.
        **kwargs: Additional ContainerDependencies fields.

    Returns:
        Container instance for the engagement.
    """
    if engagement_id in _containers:
        return _containers[engagement_id]

    deps = ContainerDependencies(
        db_url=db_url,
        redis_url=redis_url,
        engagement_id=engagement_id,
        **kwargs,
    )
    container = _factory(deps)
    _containers[engagement_id] = container
    return container


def get_container(engagement_id: str) -> Container | None:
    """Get an existing Container for an engagement, if one exists.

    Unlike get_or_create_container, this does NOT create a new container.

    Args:
        engagement_id: Engagement ID.

    Returns:
        Container instance or None.
    """
    return _containers.get(engagement_id)


def remove_container(engagement_id: str) -> None:
    """Remove a Container when an engagement completes.

    Args:
        engagement_id: Engagement ID to remove.
    """
    _containers.pop(engagement_id, None)
