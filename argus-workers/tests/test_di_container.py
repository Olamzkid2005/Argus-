"""Tests for di_container.py

Covers:
  - ContainerDependencies defaults
  - Container init and lazy service creation
  - OutputProvider / TemplateProvider defaults
  - get_or_create_container / get_container / remove_container
  - set_container_factory override
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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

    def test_lazy_tool_runner(self):
        deps = ContainerDependencies(engagement_id="eng-001", db_url="postgresql://localhost/db")
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
        # Clean registry before each test
        from di_container import _containers
        _containers.clear()

    def test_get_or_create_container(self):
        container = get_or_create_container("eng-001", db_url="postgresql://localhost/db")
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
