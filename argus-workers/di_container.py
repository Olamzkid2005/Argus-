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
import threading
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

    Call ``close()`` when the engagement completes to release resources.
    On garbage collection, ``__del__`` will attempt cleanup as a safety net.
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

        # Lazily initialized services — thread-safe via per-container lock
        self._lock = threading.Lock()
        self._tool_runner = None
        self._llm_client = None
        self._checkpoint_manager = None
        # Tear-down guard
        self._closed = False

    def close(self) -> None:
        """Release all lazily-initialized resources.

        Safe to call multiple times — idempotent after first call.
        Called automatically by ``remove_container()``.
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True

            # Collect and release resources outside the lock to avoid
            # potential deadlocks from service teardown.
            tool_runner = self._tool_runner
            llm_client = self._llm_client
            checkpoint_mgr = self._checkpoint_manager

            self._tool_runner = None
            self._llm_client = None
            self._checkpoint_manager = None

        # ── Release resources ──
        if tool_runner is not None:
            try:
                close_attr = getattr(tool_runner, "close", None)
                if close_attr:
                    close_attr()
            except Exception:
                logger.exception(
                    "Error closing tool_runner for engagement %s",
                    self.engagement_id,
                )

        if checkpoint_mgr is not None:
            try:
                close_attr = getattr(checkpoint_mgr, "close", None)
                if close_attr:
                    close_attr()
            except Exception:
                logger.exception(
                    "Error closing checkpoint_manager for engagement %s",
                    self.engagement_id,
                )

        if llm_client is not None:
            try:
                close_attr = getattr(llm_client, "close", None)
                if close_attr:
                    close_attr()
            except Exception:
                logger.exception(
                    "Error closing llm_client for engagement %s",
                    self.engagement_id,
                )

        logger.debug("Container closed for engagement %s", self.engagement_id)

    def __del__(self) -> None:
        """Safety net — release resources if ``close()`` was not called explicitly."""
        try:
            self.close()
        except Exception:
            pass

    @property
    def tool_runner(self):
        """Get or create ToolRunner instance (thread-safe)."""
        if self._closed:
            raise RuntimeError(
                f"Container for engagement {self.engagement_id} is already closed"
            )
        if self._tool_runner is None:
            with self._lock:
                if self._tool_runner is None:
                    if self._closed:
                        raise RuntimeError(
                            f"Container for engagement {self.engagement_id} "
                            "is already closed"
                        )
                    from tools.tool_runner import ToolRunner

                    self._tool_runner = ToolRunner(
                        connection_string=self.db_url,
                        engagement_id=self.engagement_id,
                    )
        return self._tool_runner

    @property
    def llm_client(self):
        """Get or create LLMClient instance (thread-safe)."""
        if self._closed:
            raise RuntimeError(
                f"Container for engagement {self.engagement_id} is already closed"
            )
        if self._llm_client is None:
            with self._lock:
                if self._llm_client is None:
                    if self._closed:
                        raise RuntimeError(
                            f"Container for engagement {self.engagement_id} "
                            "is already closed"
                        )
                    try:
                        from llm_client import LLMClient

                        redis_url = self.redis_url or "redis://localhost:6379"
                        self._llm_client = LLMClient(redis_url=redis_url)
                    except Exception as e:
                        logger.warning("LLM client not available: %s", e)
                        self._llm_client = None
        return self._llm_client

    @property
    def checkpoint_manager(self):
        """Get or create CheckpointManager instance (thread-safe)."""
        if self._closed:
            raise RuntimeError(
                f"Container for engagement {self.engagement_id} is already closed"
            )
        if self._checkpoint_manager is None and self.db_url:
            with self._lock:
                if self._checkpoint_manager is None and self.db_url:
                    if self._closed:
                        raise RuntimeError(
                            f"Container for engagement {self.engagement_id} "
                            "is already closed"
                        )
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
_containers_lock = threading.Lock()


def get_or_create_container(
    engagement_id: str,
    db_url: str | None = None,
    redis_url: str | None = None,
    **kwargs,
) -> Container:
    """Get or create a Container for an engagement (thread-safe).

    Args:
        engagement_id: Engagement ID to scope the container.
        db_url: Optional database URL.
        redis_url: Optional Redis URL.
        **kwargs: Additional ContainerDependencies fields.

    Returns:
        Container instance for the engagement.
    """
    with _containers_lock:
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
    """Get an existing Container for an engagement, if one exists (thread-safe).

    Unlike get_or_create_container, this does NOT create a new container.

    Args:
        engagement_id: Engagement ID.

    Returns:
        Container instance or None.
    """
    with _containers_lock:
        return _containers.get(engagement_id)


def remove_container(engagement_id: str) -> None:
    """Remove a Container when an engagement completes (thread-safe).

    Calls ``container.close()`` before removing from the registry to
    release lazily-initialized resources such as database connections,
    HTTP clients, and checkpoint managers.

    Args:
        engagement_id: Engagement ID to remove.
    """
    container = None
    with _containers_lock:
        container = _containers.pop(engagement_id, None)
    if container is not None:
        container.close()
