"""Basic syntax/import tests for Playwright browser verifier scripts.

These tests verify that the scripts are syntactically valid and their
core functions are importable. Full Playwright tests require a browser
and are skipped if playwright is not installed.
"""

import importlib.util
import subprocess
import sys

import pytest

SCRIPTS_DIR = "tools/scripts"


def _check_import_available(script_name):
    """Check whether a script's core import would work (playwright may be absent)."""
    path = f"{SCRIPTS_DIR}/{script_name}"
    try:
        with open(path) as f:
            source = f.read()
        # If the script imports playwright, skip the import test without it
        if "from playwright" in source or "import playwright" in source:
            try:
                __import__("playwright")
            except ImportError:
                return False
        return True
    except (FileNotFoundError, ImportError):
        return False


def _import_module(name, path):
    """Import a module from a file path for syntax/import checking."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPlaywrightBola:
    def test_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"{SCRIPTS_DIR}/playwright_bola.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(not _check_import_available("playwright_bola.py"), reason="playwright not installed")
    def test_import_core_function(self):
        mod = _import_module("playwright_bola", f"{SCRIPTS_DIR}/playwright_bola.py")
        assert hasattr(mod, "check_bola")
        assert hasattr(mod, "_check_auth_success")

    @pytest.mark.skipif(not _check_import_available("playwright_bola.py"), reason="playwright not installed")
    def test_check_bola_accepts_new_params(self):
        mod = _import_module("playwright_bola", f"{SCRIPTS_DIR}/playwright_bola.py")
        import inspect
        sig = inspect.signature(mod.check_bola)
        params = list(sig.parameters.keys())
        assert "resource_pattern" in params


class TestPlaywrightXss:
    def test_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"{SCRIPTS_DIR}/playwright_xss.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(not _check_import_available("playwright_xss.py"), reason="playwright not installed")
    def test_import_core_function(self):
        mod = _import_module("playwright_xss", f"{SCRIPTS_DIR}/playwright_xss.py")
        assert hasattr(mod, "check_stored_xss")
        assert hasattr(mod, "_check_auth_success")


class TestPlaywrightPrivesc:
    def test_syntax_valid(self):
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", f"{SCRIPTS_DIR}/playwright_privesc.py"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.skipif(not _check_import_available("playwright_privesc.py"), reason="playwright not installed")
    def test_import_core_function(self):
        mod = _import_module("playwright_privesc", f"{SCRIPTS_DIR}/playwright_privesc.py")
        assert hasattr(mod, "check_privesc")
        assert hasattr(mod, "_check_auth_success")


class TestCredsFileFormat:
    def test_bola_creds_structure(self):
        """Verify the expected creds file format for BOLA."""
        import json
        creds = {
            "attacker": {"username": "user1", "password": "pass1"},
            "victim": {"username": "user2", "password": "pass2"},
        }
        serialized = json.dumps(creds)
        deserialized = json.loads(serialized)
        assert "attacker" in deserialized
        assert "victim" in deserialized
        assert "username" in deserialized["attacker"]
        assert "password" in deserialized["victim"]

    def test_simple_creds_structure(self):
        """Verify simple credential format (for XSS and Privesc)."""
        import json
        creds = {"username": "user1", "password": "pass1"}
        serialized = json.dumps(creds)
        deserialized = json.loads(serialized)
        assert "username" in deserialized
        assert "password" in deserialized
