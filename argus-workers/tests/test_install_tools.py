"""Tests for scripts/install_tools.py provisioning helpers.

Covers: platform normalization, release asset URL construction, zip binary
extraction, --check mode exit codes, and the install pipeline with a stubbed
download.
"""

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

    def test_macos_uses_capitalised_asset_name(self):
        # ProjectDiscovery publishes macOS assets as `..._macOS_amd64.zip`.
        url = install_tools.asset_url("nuclei", "Darwin", "arm64")
        assert (
            "github.com/projectdiscovery/nuclei/releases/download/v3.2.0/"
            "nuclei_3.2.0_macOS_arm64.zip"
        ) in url

    def test_darwin_arm64_never_builds_darwin_asset_name(self):
        for tool in ("nuclei", "httpx", "katana", "subfinder"):
            url = install_tools.asset_url(tool, "Darwin", "arm64")
            assert "_darwin_" not in url
            assert "_macOS_" in url

    def test_tarball_tools_use_tar_gz(self):
        assert install_tools.asset_url("dalfox", "Linux", "x86_64").endswith(
            "dalfox_2.10.0_linux_amd64.tar.gz"
        )
        assert install_tools.asset_url("dalfox", "Darwin", "arm64").endswith(
            "dalfox_2.10.0_darwin_arm64.tar.gz"
        )
        assert install_tools.asset_url("ffuf", "Linux", "x86_64").endswith(
            "ffuf_2.1.0_linux_amd64.tar.gz"
        )

    def test_ffuf_darwin_has_no_asset(self):
        # ffuf publishes no darwin build at v2.1.0 — raise so the caller can
        # print the brew alternative instead of downloading a 404 page.
        with pytest.raises(RuntimeError, match="brew install ffuf"):
            install_tools.asset_url("ffuf", "Darwin", "arm64")

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


def _fake_download_from(zip_path):
    """Return a ``_download`` stand-in that writes *zip_path* to the target."""

    def fake_download(url, dest, **_kwargs):
        import shutil

        shutil.copy(str(zip_path), dest)
        return True, ""

    return fake_download


class TestInstallGoTool:
    def test_downloads_verifies_extracts_and_symlinks(self, tmp_path):
        # Build a fake release zip
        zip_path = tmp_path / "nuclei_3.2.0_linux_amd64.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("README.md", "docs")
            zf.writestr("nuclei", b"#!/bin/sh\necho nuclei 3.2.0\n")

        with patch(
            "install_tools._download", side_effect=_fake_download_from(zip_path)
        ), patch(
            "install_tools.TOOL_CACHE_DIR", tmp_path / "cache"
        ), patch("install_tools.Path.home", return_value=tmp_path), patch(
            "install_tools.normalize_platform", return_value=("linux", "amd64")
        ), patch("install_tools._find_binary", return_value=None):
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

        with patch(
            "install_tools._download", side_effect=_fake_download_from(zip_path)
        ), patch(
            "install_tools.TOOL_CACHE_DIR", tmp_path / "cache"
        ), patch(
            "install_tools.normalize_platform", return_value=("linux", "amd64")
        ), patch("install_tools._find_binary", return_value=None):
            ok = install_tools.install_go_tool("nuclei", verify_hash=True)

        assert ok is False
        assert not (tmp_path / "cache" / "nuclei" / "nuclei").exists()


class TestGitToolWrapper:
    """The wrapper must use the real checkout, not a hardcoded cache path.

    ``ARGUS_TOOL_CACHE_DIR`` can move the cache, so baking ``~/.argus/tools``
    into the wrapper silently breaks the git-only tools.
    """

    @pytest.mark.parametrize(
        ("tool", "script"), [("jwt_tool", "jwt_tool.py"), ("sn1per", "sniper")]
    )
    def test_wrapper_uses_the_actual_checkout_path(
        self, monkeypatch, tmp_path, tool, script
    ):
        cache = tmp_path / "custom-cache"
        checkout = cache / tool
        checkout.mkdir(parents=True)
        (checkout / script).write_text("#!/bin/sh\n")
        monkeypatch.setattr(install_tools, "TOOL_CACHE_DIR", cache)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setattr(install_tools.shutil, "which", lambda _name: None)

        assert install_tools.install_git_tool(tool) is True

        wrapper = tmp_path / "home" / ".local" / "bin" / tool
        body = wrapper.read_text()
        assert str(checkout) in body
        assert "~/.argus/tools" not in body


class TestWindowsSupport:
    def test_binary_filename_adds_exe_only_on_windows(self):
        assert install_tools.binary_filename("nuclei", "windows") == "nuclei.exe"
        assert install_tools.binary_filename("nuclei", "darwin") == "nuclei"
        assert install_tools.binary_filename("nuclei", "linux") == "nuclei"

    def test_windows_asset_names(self):
        assert install_tools.asset_url("nuclei", "Windows", "AMD64").endswith(
            "nuclei_3.2.0_windows_amd64.zip"
        )
        # ffuf is a tarball everywhere except windows.
        assert install_tools.asset_url("ffuf", "Windows", "AMD64").endswith(
            "ffuf_2.1.0_windows_amd64.zip"
        )
        # dalfox keeps .tar.gz on windows too.
        assert install_tools.asset_url("dalfox", "Windows", "AMD64").endswith(
            "dalfox_2.10.0_windows_amd64.tar.gz"
        )

    def test_windows_exe_is_found_inside_the_archive(self):
        names = ["nuclei_3.2.0_windows_amd64/nuclei.exe", "README.md"]
        assert (
            install_tools.find_binary_in_zip(names, "nuclei")
            == "nuclei_3.2.0_windows_amd64/nuclei.exe"
        )

    def test_git_tool_wrapper_is_a_cmd_on_windows(self, monkeypatch, tmp_path):
        cache = tmp_path / "cache"
        checkout = cache / "jwt_tool"
        checkout.mkdir(parents=True)
        (checkout / "jwt_tool.py").write_text("print('jwt')\n")
        monkeypatch.setattr(install_tools, "TOOL_CACHE_DIR", cache)
        monkeypatch.setattr(install_tools, "IS_WINDOWS", True)
        monkeypatch.setattr(install_tools, "_find_binary", lambda _name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        assert install_tools.install_git_tool("jwt_tool") is True

        wrapper = tmp_path / "home" / ".local" / "bin" / "jwt_tool.cmd"
        body = wrapper.read_text()
        assert body.startswith("@echo off")
        assert str(checkout) in body
        assert "jwt_tool.py" in body

    def test_sh_only_tool_is_skipped_on_windows(self, monkeypatch, tmp_path):
        cache = tmp_path / "cache"
        checkout = cache / "sn1per"
        checkout.mkdir(parents=True)
        (checkout / "sniper").write_text("#!/bin/sh\n")
        monkeypatch.setattr(install_tools, "TOOL_CACHE_DIR", cache)
        monkeypatch.setattr(install_tools, "IS_WINDOWS", True)
        monkeypatch.setattr(install_tools, "_find_binary", lambda _name: None)

        assert install_tools.install_git_tool("sn1per") is None

    def test_download_falls_back_to_urllib_without_curl(self, monkeypatch, tmp_path):
        monkeypatch.setattr(install_tools.shutil, "which", lambda _name: None)
        dest = tmp_path / "payload"

        class FakeResponse:
            def __init__(self):
                self._chunks = [b"data"]

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self, _size=-1):
                return self._chunks.pop() if self._chunks else b""

        monkeypatch.setattr(
            install_tools.urllib.request,
            "urlopen",
            lambda _request, timeout=0: FakeResponse(),
        )

        ok, error = install_tools._download("https://example.invalid/x", dest)

        assert ok is True, error
        assert dest.read_bytes() == b"data"


class TestDefaultGroups:
    def _record_calls(self, monkeypatch, calls):
        for fn in (
            "install_go_tool",
            "install_go_install_tool",
            "install_system_tool",
            "install_git_tool",
            "install_release_tool",
            "install_pip_tool",
        ):
            name = fn

            def recorder(tool, _name=name, **_kwargs):
                calls.append((_name, tool))
                return True

            monkeypatch.setattr(install_tools, fn, recorder)
        monkeypatch.setattr(
            install_tools,
            "install_tool_assets",
            lambda: calls.append(("assets", "templates")) or True,
        )

    def test_default_installs_every_group(self, monkeypatch):
        calls: list[tuple[str, str]] = []
        self._record_calls(monkeypatch, calls)

        assert install_tools.main([]) == 0

        tools = {tool for _fn, tool in calls}
        assert {"nuclei", "phpcs", "commix", "dependency_check"} <= tools
        assert set(install_tools.PIP_TOOL_MANIFEST) <= tools
        assert set(install_tools.GO_INSTALL_MANIFEST) <= tools
        assert ("assets", "templates") in calls

    def test_go_only_stays_on_go_tools(self, monkeypatch):
        calls: list[tuple[str, str]] = []
        self._record_calls(monkeypatch, calls)

        assert install_tools.main(["--go-only"]) == 0

        assert {fn for fn, _tool in calls} == {
            "install_go_tool",
            "install_go_install_tool",
        }


class TestGoInstallTool:
    def test_skips_without_a_go_toolchain(self, monkeypatch):
        monkeypatch.setattr(install_tools, "_find_binary", lambda _name: None)
        monkeypatch.setattr(install_tools.shutil, "which", lambda _name: None)

        assert install_tools.install_go_install_tool("naabu") is None

    def test_runs_go_install_and_resolves_the_binary(self, monkeypatch, tmp_path):
        go_bin = tmp_path / "go" / "bin"
        go_bin.mkdir(parents=True)

        def fake_which(name):
            if name == "go":
                return "/usr/local/bin/go"
            candidate = go_bin / name
            return str(candidate) if candidate.exists() else None

        def fake_run(cmd, **_kwargs):
            (go_bin / "naabu").write_text("#!/bin/sh\n")
            return install_tools.subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(install_tools, "_find_binary", fake_which)
        monkeypatch.setattr(install_tools.shutil, "which", fake_which)
        monkeypatch.setattr(install_tools.subprocess, "run", fake_run)

        assert install_tools.install_go_install_tool("naabu") is True


class TestPythonConsoleScriptShadowing:
    """``venv/bin/httpx`` is the Python HTTPX CLI, not ProjectDiscovery's."""

    def test_recognises_a_pip_console_script(self, tmp_path):
        script = tmp_path / "httpx"
        script.write_text("#!/tmp/venv/bin/python\nfrom httpx import main\n")

        assert install_tools._is_python_console_script(script) is True

    def test_compiled_binary_and_missing_files_are_not_scripts(self, tmp_path):
        binary = tmp_path / "httpx"
        binary.write_bytes(b"\x7fELF\x02\x01\x01\x00")

        assert install_tools._is_python_console_script(binary) is False
        assert install_tools._is_python_console_script(tmp_path / "absent") is False

    def test_native_lookup_ignores_the_venv_cli(self, monkeypatch, tmp_path):
        script = tmp_path / "httpx"
        script.write_text("#!/usr/bin/env python3\nfrom httpx import main\n")
        monkeypatch.setattr(install_tools, "_find_binary", lambda _name: str(script))

        assert install_tools._find_native_binary("httpx") is None

    def test_install_go_tool_downloads_despite_the_venv_cli(self, monkeypatch, tmp_path):
        # The regression: with the venv active, PATH resolves httpx to the
        # Python CLI and the Go scanner was reported present but never fetched.
        archive = tmp_path / "httpx.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("httpx", b"\x7fELF fake go binary")
        venv_cli = tmp_path / "httpx"
        venv_cli.write_text("#!/usr/bin/env python3\nfrom httpx import main\n")

        monkeypatch.setattr(install_tools, "_find_binary", lambda _name: str(venv_cli))
        monkeypatch.setattr(install_tools, "_download", _fake_download_from(archive))
        monkeypatch.setattr(install_tools, "TOOL_CACHE_DIR", tmp_path / "cache")
        monkeypatch.setattr(install_tools.Path, "home", lambda: tmp_path / "home")
        monkeypatch.setattr(
            install_tools, "normalize_platform", lambda: ("linux", "amd64")
        )
        monkeypatch.setattr(
            install_tools,
            "asset_url",
            lambda *_a, **_k: "https://example.invalid/httpx.zip",
        )

        assert install_tools.install_go_tool("httpx", verify_hash=False) is True
        assert (tmp_path / "cache" / "httpx" / "httpx").exists()


class TestFailureReporting:
    """A skipped required tool must not report success."""

    def test_required_tool_with_no_install_path_fails_the_run(
        self, monkeypatch, capsys
    ):
        monkeypatch.setattr(install_tools, "IS_WINDOWS", False)
        monkeypatch.setattr(install_tools, "install_system_tool", lambda _tool: None)

        assert install_tools.main(["--system"]) == 1

        out = capsys.readouterr().out
        assert "failure(s)" in out
        assert "All requested tools installed" not in out

    def test_tools_with_no_build_for_this_os_stay_quiet(self, monkeypatch, capsys):
        monkeypatch.setattr(install_tools, "IS_WINDOWS", True)

        def fake_system(tool):
            return None if install_tools._unsupported_on_this_platform(tool) else True

        monkeypatch.setattr(install_tools, "install_system_tool", fake_system)

        assert install_tools.main(["--system"]) == 0

        out = capsys.readouterr().out
        assert "Not installable on this platform" in out
        assert "failure(s)" not in out

    def test_platform_support_matrix(self, monkeypatch):
        monkeypatch.setattr(install_tools, "IS_WINDOWS", True)

        for tool in ("testssl", "nikto", "whatweb", "wpscan", "sn1per"):
            assert install_tools._unsupported_on_this_platform(tool) is True
        # Windows does have packages for these, so a skip is a real failure.
        for tool in ("nmap", "trufflehog", "eslint"):
            assert install_tools._unsupported_on_this_platform(tool) is False


class TestCheckModeResolution:
    def test_check_missing_sees_the_local_bin_alias(self, monkeypatch, tmp_path):
        with (
            patch("tool_core.registry.ToolRegistry") as registry_cls,
            patch("tools.tool_cache.get_cached_tool", return_value=None),
        ):
            registry_cls.return_value.is_available.return_value = False
            registry_cls.return_value.resolve.return_value = None
            monkeypatch.setattr(install_tools.Path, "home", lambda: tmp_path)
            monkeypatch.setattr(install_tools, "_find_binary", lambda _name: None)
            local_bin = tmp_path / ".local" / "bin"
            local_bin.mkdir(parents=True)
            (local_bin / "testssl").write_text("#!/bin/sh\n")

            missing = install_tools.check_missing()

        assert "testssl" not in missing
        assert "nuclei" in missing

    def test_check_missing_rejects_the_venv_python_cli(self, monkeypatch, tmp_path):
        script = tmp_path / "httpx"
        script.write_text("#!/usr/bin/env python3\nfrom httpx import main\n")

        with (
            patch("tool_core.registry.ToolRegistry") as registry_cls,
            patch("tools.tool_cache.get_cached_tool", return_value=None),
        ):
            registry_cls.return_value.is_available.return_value = True
            registry_cls.return_value.resolve.return_value = str(script)
            monkeypatch.setattr(install_tools.Path, "home", lambda: tmp_path)
            monkeypatch.setattr(install_tools, "_find_binary", lambda _name: None)

            missing = install_tools.check_missing()

        assert "httpx" in missing
