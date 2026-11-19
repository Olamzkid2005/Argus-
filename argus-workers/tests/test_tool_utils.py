"""Tests for tools.tool_utils — Category: function"""

import os

import pytest

from tools import tool_utils
from tools.tool_utils import (
    get_augmented_path,
    is_python_console_script,
    is_tool_available,
    resolve_tool_binary,
    shadowing_diagnostic,
)


class TestGetAugmentedPath:
    """Tests for the get_augmented_path function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        instance = get_augmented_path()
        assert instance is not None

    def test_returns_correct_type(self):
        """Returns a string path."""
        instance = get_augmented_path()
        assert isinstance(instance, str)


class TestResolveToolBinary:
    """Tests for the resolve_tool_binary function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_binary()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            resolve_tool_binary()


class TestIsToolAvailable:
    """Tests for the is_tool_available function."""

    def test_basic_execution(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_tool_available()

    def test_returns_correct_type(self):
        """Function requires arguments."""
        with pytest.raises(TypeError):
            is_tool_available()


# A pip console script looks like an executable to shutil.which. This is the
# exact shape of `venv/bin/httpx` from the `httpx` Python package, which used to
# be picked over ProjectDiscovery httpx and made every probe fail with
# "The httpx command line client could not run".
PYTHON_CONSOLE_SCRIPT = b"#!/usr/bin/env python3\nfrom httpx import main\nmain()\n"
NATIVE_BINARY = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 24


def _write_executable(path, content: bytes) -> None:
    path.write_bytes(content)
    path.chmod(0o755)


def _path_with(monkeypatch, *dirs) -> None:
    monkeypatch.setattr(
        tool_utils, "get_augmented_path", lambda: os.pathsep.join(str(d) for d in dirs)
    )


class TestShadowedNativeTools:
    """Tool resolution must not run a same-named Python console script."""

    def test_is_python_console_script_detects_shebang(self, tmp_path):
        script = tmp_path / "httpx"
        _write_executable(script, PYTHON_CONSOLE_SCRIPT)
        native = tmp_path / "native"
        _write_executable(native, NATIVE_BINARY)
        assert is_python_console_script(str(script)) is True
        assert is_python_console_script(str(native)) is False

    def test_native_binary_wins_over_earlier_python_script(self, tmp_path, monkeypatch):
        venv_bin = tmp_path / "venv" / "bin"
        go_bin = tmp_path / "go" / "bin"
        venv_bin.mkdir(parents=True)
        go_bin.mkdir(parents=True)
        _write_executable(venv_bin / "httpx", PYTHON_CONSOLE_SCRIPT)
        _write_executable(go_bin / "httpx", NATIVE_BINARY)
        _path_with(monkeypatch, venv_bin, go_bin)

        assert resolve_tool_binary("httpx") == str(go_bin / "httpx")
        assert is_tool_available("httpx") is True
        assert shadowing_diagnostic("httpx") is None

    def test_shadowed_tool_without_native_is_unusable(self, tmp_path, monkeypatch):
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        _write_executable(venv_bin / "httpx", PYTHON_CONSOLE_SCRIPT)
        _path_with(monkeypatch, venv_bin)

        assert resolve_tool_binary("httpx") is None
        assert is_tool_available("httpx") is False

        diagnostic = shadowing_diagnostic("httpx")
        assert diagnostic is not None
        assert str(venv_bin / "httpx") in diagnostic
        assert "projectdiscovery" in diagnostic.lower()

    def test_python_console_script_still_resolves_for_script_tools(
        self, tmp_path, monkeypatch
    ):
        """Tools whose real implementation is a Python script keep working."""
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        _write_executable(venv_bin / "arjun", PYTHON_CONSOLE_SCRIPT)
        _path_with(monkeypatch, venv_bin)

        assert resolve_tool_binary("arjun") == str(venv_bin / "arjun")
        assert shadowing_diagnostic("arjun") is None

    def test_missing_tool_returns_none(self, tmp_path, monkeypatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        _path_with(monkeypatch, empty)
        assert resolve_tool_binary("nuclei") is None
        assert shadowing_diagnostic("nuclei") is None
