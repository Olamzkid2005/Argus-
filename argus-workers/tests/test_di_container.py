"""Tests for di_container.py

Covers:
  - ContainerDependencies defaults
  - Container init and lazy service creation
  - OutputProvider / TemplateProvider defaults
  - get_or_create_container / get_container / remove_container
  - set_container_factory override
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

# Some tests exercise the tool_runner property which transitively imports
# opentelemetry. If it's not available (or broken in the test env), skip
# those tests rather than failing with an import error.
try:
    from opentelemetry import trace  # noqa: F401

    _HAS_OPENTELEMETRY = True
except ImportError:
    _HAS_OPENTELEMETRY = False

skipif_no_opentelemetry = pytest.mark.skipif(
    not _HAS_OPENTELEMETRY,
    reason="opentelemetry not available — tool_runner tests require it",
)

from di_container import (
    Container,
    ContainerDependencies,
    OutputProvider,
    TemplateProvider,
    get_container,
    get_or_create_container,
    remove_container,
    set_container_factory,
)


class TestOutputProvider:
    """Tests for OutputProvider default implementation."""

    @pytest.mark.asyncio
    async def test_write(self):
        provider = OutputProvider()
        await provider.write("step1", "content")  # Should not raise

    @pytest.mark.asyncio
    async def test_read_returns_none(self):
        provider = OutputProvider()
        result = await provider.read("step1")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists_returns_false(self):
        provider = OutputProvider()
        result = await provider.exists("step1")
        assert result is False


class TestTemplateProvider:
    """Tests for TemplateProvider default implementation."""

    @pytest.mark.asyncio
    async def test_load_returns_template_name(self):
        provider = TemplateProvider()
        result = await provider.load("report.html", {"name": "test"})
        assert "report.html" in result


class TestContainerDependencies:
    """Tests for ContainerDependencies dataclass."""

    def test_defaults(self):
        deps = ContainerDependencies()
        assert deps.db_url is None
        assert deps.redis_url is None
        assert deps.engagement_id is None
        assert deps.tool_timeout == 300
        assert deps.max_retries == 3

    def test_custom_values(self):
        deps = ContainerDependencies(
            db_url="postgresql://localhost/db",
            redis_url="redis://localhost:6379",
            engagement_id="eng-001",
            tool_timeout=600,
        )
        assert deps.db_url == "postgresql://localhost/db"
        assert deps.engagement_id == "eng-001"


class TestContainer:
    """Tests for Container class."""

    def test_init_with_defaults(self):
        deps = ContainerDependencies(engagement_id="eng-001")
        container = Container(deps)
        assert container.engagement_id == "eng-001"
        assert isinstance(container.output_provider, OutputProvider)
        assert isinstance(container.template_provider, TemplateProvider)

    @skipif_no_opentelemetry
    def test_lazy_tool_runner(self):
        deps = ContainerDependencies(
            engagement_id="eng-001", db_url="postgresql://localhost/db"
        )
        container = Container(deps)
        with patch("tools.tool_runner.ToolRunner") as mock_tr:
            tr = container.tool_runner
            assert tr is mock_tr.return_value
            # Second call returns cached
            assert container.tool_runner is tr

    def test_lazy_llm_client(self):
        deps = ContainerDependencies(engagement_id="eng-001")
        container = Container(deps)
        with patch("llm_client.LLMClient") as mock_client:
            llm = container.llm_client
            assert llm is mock_client.return_value

    def test_llm_client_failure(self):
        deps = ContainerDependencies(engagement_id="eng-001")
        container = Container(deps)
        with patch("llm_client.LLMClient", side_effect=Exception("LLM init failed")):
            llm = container.llm_client
            assert llm is None

    def test_checkpoint_manager_none_without_db(self):
        deps = ContainerDependencies(engagement_id="eng-001")
        container = Container(deps)
        assert container.checkpoint_manager is None


class TestContainerRegistry:
    """Tests for container registry functions."""

    def setup_method(self):
        # Clean registry and capture original factory before each test
        from di_container import _containers, _factory as default_factory
        _containers.clear()
        self._original_factory = default_factory

    def teardown_method(self):
        # Restore factory to avoid polluting other tests
        from di_container import _containers, set_container_factory
        _containers.clear()
        if hasattr(self, '_original_factory'):
            set_container_factory(self._original_factory)

    def test_get_or_create_container(self):
        container = get_or_create_container(
            "eng-001", db_url="postgresql://localhost/db"
        )
        assert container.engagement_id == "eng-001"
        assert container.db_url == "postgresql://localhost/db"

    def test_get_or_create_returns_same(self):
        c1 = get_or_create_container("eng-001")
        c2 = get_or_create_container("eng-001")
        assert c1 is c2

    def test_get_container(self):
        get_or_create_container("eng-001")
        container = get_container("eng-001")
        assert container is not None
        assert container.engagement_id == "eng-001"

    def test_get_container_nonexistent(self):
        assert get_container("nonexistent") is None

    def test_remove_container(self):
        get_or_create_container("eng-001")
        remove_container("eng-001")
        assert get_container("eng-001") is None

    def test_remove_nonexistent(self):
        remove_container("nonexistent")  # Should not raise

    def test_multiple_containers_isolated(self):
        c1 = get_or_create_container("eng-001")
        c2 = get_or_create_container("eng-002")
        assert c1 is not c2
        assert c1.engagement_id == "eng-001"
        assert c2.engagement_id == "eng-002"

    def test_set_container_factory(self):
        mock_factory = MagicMock(return_value="custom_container")
        set_container_factory(mock_factory)
        container = get_or_create_container("eng-001")
        assert container == "custom_container"
        mock_factory.assert_called_once()


class TestConcurrency:
    """Stress tests verifying thread safety of Container lazy-init properties.

    These tests simulate concurrent access from multiple threads to catch
    race conditions in the double-checked locking pattern on tool_runner,
    llm_client, and checkpoint_manager properties.
    """

    def setup_method(self):
        # Clean registry and reset factory before each test
        from di_container import _containers, _factory as default_factory
        _containers.clear()
        self._original_factory = default_factory
        self.deps = ContainerDependencies(
            engagement_id="eng-concurrency-test",
            db_url="postgresql://localhost/concurrency_test",
            redis_url="redis://localhost:6379",
        )

    def teardown_method(self):
        # Restore factory to avoid polluting other tests
        from di_container import _containers, set_container_factory
        _containers.clear()
        set_container_factory(self._original_factory if hasattr(self, '_original_factory')
                              else lambda deps: Container(deps))

    @skipif_no_opentelemetry
    def test_concurrent_tool_runner_creates_single_instance(self):
        """Multiple threads accessing tool_runner concurrently should all get
        the same instance, with only one creation call."""
        container = Container(self.deps)
        num_threads = 8
        results: list = []
        errors: list[Exception] = []
        barrier = threading.Barrier(num_threads)

        def access_tool_runner():
            barrier.wait()  # All threads hit this at the same time
            try:
                results.append(container.tool_runner)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=access_tool_runner) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        assert len(results) == num_threads
        # All threads got the same instance
        assert all(r is results[0] for r in results), "Not all threads got the same tool_runner"

    def test_concurrent_llm_client_creates_single_instance(self):
        """Multiple threads accessing llm_client concurrently should all get
        the same instance, with only one LLMClient construction."""
        container = Container(self.deps)
        num_threads = 8
        results: list = []
        errors: list[Exception] = []
        barrier = threading.Barrier(num_threads)

        def access_llm_client():
            barrier.wait()
            try:
                results.append(container.llm_client)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=access_llm_client) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        assert len(results) == num_threads
        assert all(r is results[0] for r in results), "Not all threads got the same llm_client"

    def test_concurrent_checkpoint_manager_creates_single_instance(self):
        """Multiple threads accessing checkpoint_manager concurrently should
        all get the same instance."""
        container = Container(self.deps)
        num_threads = 8
        results: list = []
        errors: list[Exception] = []
        barrier = threading.Barrier(num_threads)

        def access_checkpoint_manager():
            barrier.wait()
            try:
                results.append(container.checkpoint_manager)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=access_checkpoint_manager) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        assert len(results) == num_threads
        assert all(r is results[0] for r in results), "Not all threads got the same checkpoint_manager"

    @skipif_no_opentelemetry
    def test_concurrent_all_properties_isolated(self):
        """Multiple threads accessing different lazy properties concurrently
        should not interfere with each other."""
        container = Container(self.deps)
        num_threads = 12  # 4 per property
        results: dict[str, list] = {"tr": [], "llm": [], "cp": []}
        errors: list[Exception] = []
        barrier = threading.Barrier(num_threads)

        def access_tool_runner():
            barrier.wait()
            try:
                results["tr"].append(container.tool_runner)
            except Exception as e:
                errors.append(e)

        def access_llm_client():
            barrier.wait()
            try:
                results["llm"].append(container.llm_client)
            except Exception as e:
                errors.append(e)

        def access_checkpoint_manager():
            barrier.wait()
            try:
                results["cp"].append(container.checkpoint_manager)
            except Exception as e:
                errors.append(e)

        targets = [access_tool_runner] * 4 + [access_llm_client] * 4 + [access_checkpoint_manager] * 4
        threads = [threading.Thread(target=t) for t in targets]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        # Each property group got the same instance across its threads
        assert len(results["tr"]) == 4
        assert all(r is results["tr"][0] for r in results["tr"])
        assert len(results["llm"]) == 4
        assert all(r is results["llm"][0] for r in results["llm"])
        assert len(results["cp"]) == 4
        assert all(r is results["cp"][0] for r in results["cp"])
        # Properties are distinct from each other
        assert results["tr"][0] is not results["llm"][0]

    def test_concurrent_registry_creates_single_container(self):
        """Multiple threads calling get_or_create_container for the same
        engagement_id should all get the same Container instance."""
        num_threads = 8
        results: list = []
        errors: list[Exception] = []
        barrier = threading.Barrier(num_threads)

        def get_container():
            barrier.wait()
            try:
                results.append(
                    get_or_create_container("eng-concurrent-registry")
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=get_container) for _ in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        assert len(results) == num_threads
        assert all(r is results[0] for r in results), "Registry created multiple containers for same engagement"

    def test_concurrent_registry_creates_isolated_containers(self):
        """Multiple threads creating containers for different engagement_ids
        should each get their own distinct container."""
        num_engagements = 5
        threads_per_eng = 4
        results: dict[str, list] = {}
        errors: list[Exception] = []
        total_threads = num_engagements * threads_per_eng
        barrier = threading.Barrier(total_threads)

        eng_ids = [f"eng-concurrent-{i}" for i in range(num_engagements)]
        for eid in eng_ids:
            results[eid] = []

        def get_container_for(eid: str):
            barrier.wait()
            try:
                results[eid].append(get_or_create_container(eid))
            except Exception as e:
                errors.append(e)

        threads = []
        for eid in eng_ids:
            for _ in range(threads_per_eng):
                threads.append(threading.Thread(target=get_container_for, args=(eid,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        # Verify each engagement got a consistent container across threads
        for eid in eng_ids:
            assert len(results[eid]) == threads_per_eng
            assert all(r is results[eid][0] for r in results[eid]), \
                f"Engagement {eid} got different containers"
        # Verify different engagements got different containers
        for i in range(num_engagements):
            for j in range(i + 1, num_engagements):
                assert results[eng_ids[i]][0] is not results[eng_ids[j]][0], \
                    f"Engagements {eng_ids[i]} and {eng_ids[j]} shared a container"

    def test_concurrent_mixed_registry_operations(self):
        """Concurrent get_or_create_container, get_container, and
        remove_container calls should not deadlock or corrupt state."""
        # Pre-populate some containers
        get_or_create_container("eng-mix-a")
        get_or_create_container("eng-mix-b")

        num_ops = 6
        results: list = []
        errors: list[Exception] = []
        barrier = threading.Barrier(num_ops)

        def get_a():
            barrier.wait()
            try:
                results.append(get_container("eng-mix-a"))
            except Exception as e:
                errors.append(e)

        def create_c():
            barrier.wait()
            try:
                results.append(get_or_create_container("eng-mix-c"))
            except Exception as e:
                errors.append(e)

        def remove_b():
            barrier.wait()
            try:
                remove_container("eng-mix-b")
                results.append("removed-b")
            except Exception as e:
                errors.append(e)

        def get_after_remove():
            barrier.wait()
            try:
                results.append(get_container("eng-mix-b"))
            except Exception as e:
                errors.append(e)

        def create_d():
            barrier.wait()
            try:
                results.append(get_or_create_container("eng-mix-d"))
            except Exception as e:
                errors.append(e)

        def remove_a():
            barrier.wait()
            try:
                remove_container("eng-mix-a")
                results.append("removed-a")
            except Exception as e:
                errors.append(e)

        targets = [get_a, create_c, remove_b, get_after_remove, create_d, remove_a]
        threads = [threading.Thread(target=t) for t in targets]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"{len(errors)} thread(s) raised: {errors[0]}"
        # Verify final state: eng-mix-a removed, eng-mix-b removed,
        # eng-mix-c and eng-mix-d created, eng-mix-a should be gone
        assert get_container("eng-mix-a") is None
        assert get_container("eng-mix-b") is None
        assert get_container("eng-mix-c") is not None
        assert get_container("eng-mix-d") is not None
        assert len(results) == num_ops
