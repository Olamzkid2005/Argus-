"""Tests for scripts/install_tools.py provisioning helpers.

Covers: platform normalization, release asset URL construction, zip binary
extraction, --check mode exit codes, and the install pipeline with a stubbed
download.
"""

import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import install_tools  # noqa: E402


class TestNormalizePlatform:
    def test_linux_amd64(self):
        assert install_tools.normalize_platform("Linux", "x86_64") == (
            "linux",
            "amd64",
        )

    def test_macos_arm64(self):
        assert install_tools.normalize_platform("Darwin", "arm64") == (
            "darwin",
            "arm64",
        )

    def test_windows_amd64(self):
        assert install_tools.normalize_platform("Windows", "AMD64") == (
            "windows",
            "amd64",
        )

    def test_unsupported_raises(self):
        with pytest.raises(RuntimeError):
            install_tools.normalize_platform("plan9", "mips")


class TestAssetUrl:
    def test_nuclei_linux_amd64(self):
        url = install_tools.asset_url("nuclei", "Linux", "x86_64")
        assert (
            "github.com/projectdiscovery/nuclei/releases/download/v3.2.0/"
            "nuclei_3.2.0_linux_amd64.zip"
        ) in url

    def test_ffuf_darwin_arm64(self):
        url = install_tools.asset_url("ffuf", "Darwin", "arm64")
        assert "ffuf_2.1.0_darwin_arm64.zip" in url

    def test_unknown_tool_raises(self):
        with pytest.raises(KeyError):
            install_tools.asset_url("definitely_not_a_tool")


class TestFindBinaryInZip:
    def test_flat_layout(self):
        assert (
            install_tools.find_binary_in_zip(["nuclei", "README.md"], "nuclei")
            == "nuclei"
        )

    def test_versioned_dir_layout(self):
        names = [
            "nuclei_3.2.0_linux_amd64/LICENSE.md",
            "nuclei_3.2.0_linux_amd64/nuclei",
        ]
        assert (
            install_tools.find_binary_in_zip(names, "nuclei")
            == "nuclei_3.2.0_linux_amd64/nuclei"
        )

    def test_missing_returns_none(self):
        assert install_tools.find_binary_in_zip(["foo", "bar"], "nuclei") is None


class TestCheckMode:
    def test_check_exit_one_when_missing(self, monkeypatch):
        monkeypatch.setattr(install_tools, "check_missing", lambda: ["nuclei"])
        assert install_tools.main(["--check"]) == 1

    def test_check_exit_zero_when_all_present(self, monkeypatch):
        monkeypatch.setattr(install_tools, "check_missing", lambda: [])
        assert install_tools.main(["--check"]) == 0

    def test_check_missing_reports_via_registry(self):
        with patch("tool_core.registry.ToolRegistry") as TR, patch(
            "tools.tool_cache.get_cached_tool", return_value=None
        ):
            registry = TR.return_value
            registry.is_available.return_value = False
            missing = install_tools.check_missing()
        assert "nuclei" in missing
        assert "httpx" in missing


class TestInstallGoTool:
    def test_downloads_verifies_extracts_and_symlinks(self, tmp_path):
        # Build a fake release zip
        zip_path = tmp_path / "nuclei_3.2.0_linux_amd64.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("README.md", "docs")
            zf.writestr("nuclei", b"#!/bin/sh\necho nuclei 3.2.0\n")

        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "curl":
                dest = cmd[cmd.index("-o") + 1]
                import shutil

                shutil.copy(str(zip_path), dest)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return real_run(cmd, *args, **kwargs)

        with patch("install_tools.subprocess.run", side_effect=fake_run), patch(
            "install_tools.TOOL_CACHE_DIR", tmp_path / "cache"
        ), patch("install_tools.Path.home", return_value=tmp_path), patch(
            "install_tools.normalize_platform", return_value=("linux", "amd64")
        ):
            ok = install_tools.install_go_tool("nuclei", verify_hash=False)

        assert ok is True
        binary = tmp_path / "cache" / "nuclei" / "nuclei"
        assert binary.exists()
        assert binary.stat().st_mode & 0o111  # executable bit
        # Symlinked into ~/go/bin so ToolRegistry resolves it too
        assert (tmp_path / "go" / "bin" / "nuclei").is_symlink()

    def test_hash_mismatch_refuses(self, tmp_path):
        zip_path = tmp_path / "nuclei_3.2.0_linux_amd64.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("nuclei", b"evil")

        real_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "curl":
                dest = cmd[cmd.index("-o") + 1]
                import shutil

                shutil.copy(str(zip_path), dest)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return real_run(cmd, *args, **kwargs)

        with patch("install_tools.subprocess.run", side_effect=fake_run), patch(
            "install_tools.TOOL_CACHE_DIR", tmp_path / "cache"
        ), patch(
            "install_tools.normalize_platform", return_value=("linux", "amd64")
        ):
            ok = install_tools.install_go_tool("nuclei", verify_hash=True)

        assert ok is False
        assert not (tmp_path / "cache" / "nuclei" / "nuclei").exists()
