"""
Tests for the security bridge module.

Covers:
  - WORKERS_PATH constant
  - _ensure_workers_path idempotency
  - Import functions return actual classes/objects when workers available
  - import functions call _ensure_workers_path before importing
  - check_workers_available returns correct structure
  - get_bridge_status returns diagnostic information
  - Graceful degradation (
ensure_workers_path is called before import attempt)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from argus_cli.security.bridge import (
    WORKERS_PATH,
    _ensure_workers_path,
    check_workers_available,
    get_bridge_status,
    import_agent,
    import_intelligence_engine,
    import_llm_client,
    import_mcp_server,
    import_orchestrator,
    import_state_machine,
    import_streaming,
    import_tool_definitions,
)


# =========================================================================
# WORKERS_PATH
# =========================================================================


class TestWorkersPath:
    """Tests for the WORKERS_PATH constant."""

    def test_workers_path_is_path(self) -> None:
        assert isinstance(WORKERS_PATH, Path)

    def test_workers_path_points_to_argus_workers(self) -> None:
        assert WORKERS_PATH.name == "argus-workers"


# =========================================================================
# _ensure_workers_path
# =========================================================================


class TestEnsureWorkersPath:
    """Tests for _ensure_workers_path."""

    def test_adds_path_to_sys_path(self) -> None:
        orig = list(sys.path)
        try:
            sys.path = [p for p in sys.path if p != str(WORKERS_PATH)]
            _ensure_workers_path()
            assert str(WORKERS_PATH) in sys.path
        finally:
            sys.path = orig

    def test_idempotent_when_already_present(self) -> None:
        orig = list(sys.path)
        try:
            sys.path = [p for p in sys.path if p != str(WORKERS_PATH)]
            sys.path.insert(0, str(WORKERS_PATH))
            count_before = sys.path.count(str(WORKERS_PATH))
            _ensure_workers_path()
            count_after = sys.path.count(str(WORKERS_PATH))
            assert count_after == count_before
        finally:
            sys.path = orig


# =========================================================================
# Import Functions — Available
# =========================================================================


class TestImportAvailable:
    """
    In the test environment argus-workers is importable, so all import
    functions should return the expected classes/objects.
    """

    def test_import_orchestrator_returns_class(self) -> None:
        result = import_orchestrator()
        assert result is not None
        assert hasattr(result, "run")

    def test_import_agent_returns_class(self) -> None:
        result = import_agent()
        assert result is not None
        assert hasattr(result, "run")

    def test_import_intelligence_engine_returns_class(self) -> None:
        result = import_intelligence_engine()
        assert result is not None

    def test_import_state_machine_returns_class(self) -> None:
        result = import_state_machine()
        assert result is not None
        assert hasattr(result, "transition")

    def test_import_streaming_returns_object(self) -> None:
        result = import_streaming()
        assert result is not None

    def test_import_llm_client_returns_class(self) -> None:
        result = import_llm_client()
        assert result is not None

    def test_import_mcp_server_returns_class(self) -> None:
        result = import_mcp_server()
        assert result is not None

    def test_import_tool_definitions_returns_tools_and_func(self) -> None:
        tools, func = import_tool_definitions()
        assert tools is not None
        assert callable(func)

    def test_ensure_workers_called_on_import(self) -> None:
        """import functions attempt to call _ensure_workers_path first."""
        with patch("argus_cli.security.bridge._ensure_workers_path") as mock_ensure:
            import_orchestrator()
            mock_ensure.assert_called_once()


# =========================================================================
# check_workers_available
# =========================================================================


class TestCheckWorkersAvailable:
    """Tests for check_workers_available."""

    def test_returns_dict(self) -> None:
        result = check_workers_available()
        assert isinstance(result, dict)

    def test_has_all_expected_keys(self) -> None:
        result = check_workers_available()
        expected_keys = {
            "orchestrator", "agent", "intelligence_engine",
            "state_machine", "streaming", "llm_client",
            "mcp_server", "tool_definitions",
        }
        assert set(result.keys()) == expected_keys

    def test_all_values_are_bool(self) -> None:
        result = check_workers_available()
        for v in result.values():
            assert isinstance(v, bool)


# =========================================================================
# get_bridge_status
# =========================================================================


class TestGetBridgeStatus:
    """Tests for get_bridge_status."""

    def test_returns_dict(self) -> None:
        result = get_bridge_status()
        assert isinstance(result, dict)

    def test_has_expected_keys(self) -> None:
        result = get_bridge_status()
        assert "workers_path" in result
        assert "workers_path_exists" in result
        assert "components" in result
        assert "sys_path_includes_workers" in result
        assert "python_path" in result

    def test_workers_path_is_str(self) -> None:
        result = get_bridge_status()
        assert isinstance(result["workers_path"], str)

    def test_workers_path_exists_is_bool(self) -> None:
        result = get_bridge_status()
        assert isinstance(result["workers_path_exists"], bool)

    def test_components_is_dict(self) -> None:
        result = get_bridge_status()
        assert isinstance(result["components"], dict)

    def test_python_path_is_list(self) -> None:
        result = get_bridge_status()
        assert isinstance(result["python_path"], list)
