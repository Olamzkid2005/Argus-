"""
Provision the external security tool binaries Argus relies on.

Argus's agent spawns real binaries (nuclei, httpx, katana, subfinder, ffuf,
dalfox, sqlmap, ...). When a binary is missing, tool calls now fail LOUDLY
with ``NOT_INSTALLED`` status (see ``tools/tool_runner.py``) instead of
silently degrading to fallback scanners. This script closes that gap:

- **Go binaries** — downloaded from pinned GitHub release assets (zip),
  verified against pinned SHA256 checksums on linux/amd64, extracted into the
  shared ToolCache directory, and symlinked into ``~/go/bin`` so both
  ``ToolRunner`` (ToolCache-aware) and ``ToolRegistry`` (PATH-aware) resolve
  them.
- **Python tools** (sqlmap, semgrep, ...) — installed via pip through
  ``ToolCache``'s PIP_ALLOWLIST (supply-chain-safe) with ``--pip``.

Usage::

    python scripts/install_tools.py              # install all Go binaries
    python scripts/install_tools.py nuclei httpx # install specific tools
    python scripts/install_tools.py --pip        # also pip-install allowlisted tools
    python scripts/install_tools.py --check      # report missing tools, exit 1 if any
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Allow `python scripts/install_tools.py` to import the workers package.
WORKERS_ROOT = Path(__file__).parent.parent
if str(WORKERS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKERS_ROOT))

from tools.tool_cache import PIP_ALLOWLIST, TOOL_CACHE_DIR, TOOL_VERSIONS  # noqa: E402

# ── Download manifest (versions pinned to match tools/tool_cache.py) ────────

#: tool name -> (github org/repo, pinned version)
GO_TOOL_MANIFEST: dict[str, tuple[str, str]] = {
    "nuclei": ("projectdiscovery/nuclei", TOOL_VERSIONS["nuclei"]),
    "httpx": ("projectdiscovery/httpx", TOOL_VERSIONS["httpx"]),
    "katana": ("projectdiscovery/katana", TOOL_VERSIONS["katana"]),
    "subfinder": ("projectdiscovery/subfinder", TOOL_VERSIONS["subfinder"]),
    "ffuf": ("ffuf/ffuf", TOOL_VERSIONS["ffuf"]),
    "dalfox": ("hahwul/dalfox", TOOL_VERSIONS["dalfox"]),
}

#: Tools that ship with the OS or a package manager and are NOT auto-installable
#: from GitHub release assets (documented so --check explains why they're skipped).
MANUAL_TOOLS: dict[str, str] = {
    "nmap": "Install via your package manager: apt install nmap / brew install nmap",
    "amass": "Install via: go install -v github.com/owasp-amass/amass/v4/...@latest",
    "naabu": "Install via: go install -v github.com/projectdiscovery/naabu/v2/cmd/naabu@latest",
    "gau": "Install via: go install -v github.com/lc/gau/v2/cmd/gau@latest",
    "waybackurls": "Install via: go install -v github.com/tomnomnom/waybackurls@latest",
    "gospider": "Install via: go install -v github.com/jaeles-project/gospider@latest",
    "whatweb": "Install via: apt install whatweb / brew install whatweb",
    "nikto": "Install via: apt install nikto / brew install nikto",
    "wpscan": "Install via: gem install wpscan",
    "testssl": "Install via: git clone https://github.com/drwetter/testssl.sh.git",
    "alterx": "Install via: go install -v github.com/projectdiscovery/alterx/cmd/alterx@latest",
    "commix": "Install via: pip install commix (or use --pip)",
    "arjun": "Install via: pip install arjun (or use --pip)",
    "jwt_tool": "Install via: git clone https://github.com/ticarpi/jwt_tool.git",
}


# ── Pure helpers (unit-tested) ──────────────────────────────────────────────

def normalize_platform(os_name: str | None = None, arch: str | None = None) -> tuple[str, str]:
    """Map ``platform.system()/machine()`` to GitHub asset naming.

    Returns (os_name, arch) using GitHub's ``linux/darwin/windows`` and
    ``amd64/arm64`` conventions. Raises for unsupported platforms.
    """
    os_name = (os_name or platform.system()).lower()
    arch = (arch or platform.machine()).lower()

    if os_name in ("darwin",):
        os_name = "darwin"
    elif os_name in ("linux",):
        os_name = "linux"
    elif os_name in ("windows", "win32", "cygwin"):
        os_name = "windows"
    else:
        raise RuntimeError(f"Unsupported platform: {os_name!r}")

    if arch in ("x86_64", "amd64", "x64"):
        arch = "amd64"
    elif arch in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {arch!r}")

    return os_name, arch


def asset_url(tool: str, os_name: str | None = None, arch: str | None = None) -> str:
    """Build the pinned GitHub release asset URL for *tool* on the current platform."""
    if tool not in GO_TOOL_MANIFEST:
        raise KeyError(f"Tool {tool!r} has no binary manifest entry")
    repo, version = GO_TOOL_MANIFEST[tool]
    os_name, arch = normalize_platform(os_name, arch)
    asset = f"{tool}_{version}_{os_name}_{arch}.zip"
    return f"https://github.com/{repo}/releases/download/v{version}/{asset}"


def find_binary_in_zip(namelist: list[str], tool: str) -> str | None:
    """Return the zip entry that contains the *tool* binary.

    Handles both flat layouts (``nuclei``) and versioned-dir layouts
    (``nuclei_3.2.0_linux_amd64/nuclei``). Skips docs/license files.
    """
    candidates: list[str] = []
    for name in namelist:
        base = Path(name).name
        if base != tool:
            continue
        if name.endswith((".md", ".txt", ".LICENSE", "LICENSE")):
            continue
        candidates.append(name)
    if not candidates:
        return None
    # Prefer the shallowest path (root-level binary).
    return min(candidates, key=lambda n: n.count("/"))


def sha256_file(path: Path) -> str:
    """Compute the SHA256 hex digest of *path*."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_go_tool(
    tool: str,
    *,
    verify_hash: bool = True,
    symlink_dir: Path | None = None,
) -> bool:
    """Download, verify, extract, and cache a single Go binary.

    Returns True on success. Never raises for network/parse failures — logs
    the error and returns False so the caller can continue with other tools.
    """
    print(f"[install_tools] Installing {tool} ...")
    try:
        url = asset_url(tool)
        os_name, _arch = normalize_platform()
    except (KeyError, RuntimeError) as e:
        print(f"[install_tools] SKIP {tool}: {e}")
        return False

    expected_hash = TOOL_VERSIONS.get(tool + "_sha256") or ""
    if (os_name != "linux" or _arch != "amd64") and expected_hash:
        print(
            f"[install_tools] WARNING {tool}: pinned SHA256 is for linux/amd64; "
            f"skipping checksum verification for {os_name}/{_arch}"
        )
        verify_hash = False

    dest_dir = TOOL_CACHE_DIR / tool
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_binary = dest_dir / tool

    with tempfile.TemporaryDirectory(prefix="argus_install_") as tmp:
        zip_path = Path(tmp) / f"{tool}.zip"
        try:
            result = subprocess.run(  # noqa: S603 — safe: list form, URL from pinned manifest
                ["curl", "-L", "-o", str(zip_path), url],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            print(f"[install_tools] FAIL {tool}: download timed out (10 min)")
            return False
        if result.returncode != 0 or not zip_path.exists():
            print(
                f"[install_tools] FAIL {tool}: curl error: {result.stderr[:200]}"
            )
            return False

        if verify_hash and expected_hash:
            actual = sha256_file(zip_path)
            if actual != expected_hash:
                print(
                    f"[install_tools] FAIL {tool}: SHA256 mismatch "
                    f"(expected {expected_hash}, got {actual}) — refusing corrupt download"
                )
                return False
            print(f"[install_tools] {tool}: SHA256 verification passed")

        try:
            with zipfile.ZipFile(zip_path) as zf:
                entry = find_binary_in_zip(zf.namelist(), tool)
                if entry is None:
                    print(
                        f"[install_tools] FAIL {tool}: no binary entry in zip "
                        f"(entries: {zf.namelist()[:8]})"
                    )
                    return False
                tmp_bin = Path(tmp) / Path(entry).name
                with zf.open(entry) as src, open(tmp_bin, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile:
            print(f"[install_tools] FAIL {tool}: downloaded file is not a valid zip")
            return False

        os.chmod(tmp_bin, 0o755)
        shutil.move(str(tmp_bin), str(dest_binary))
        print(f"[install_tools] OK {tool}: cached at {dest_binary}")

    # Symlink into ~/go/bin so ToolRegistry (PATH-based) also resolves it.
    if symlink_dir is None:
        symlink_dir = Path.home() / "go" / "bin"
    if os_name != "windows":
        try:
            symlink_dir.mkdir(parents=True, exist_ok=True)
            link = symlink_dir / tool
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(dest_binary)
            print(f"[install_tools] OK {tool}: symlinked to {link}")
        except OSError as e:
            print(
                f"[install_tools] WARNING {tool}: could not symlink into {symlink_dir}: {e}"
            )
    return True


def install_pip_tool(tool: str) -> bool:
    """Install a Python-distributed tool via pip (supply-chain allowlisted)."""
    if tool not in PIP_ALLOWLIST:
        print(
            f"[install_tools] SKIP {tool}: not in the pip allowlist "
            f"(refusing to pip-install unvetted packages)"
        )
        return False
    print(f"[install_tools] pip install {tool} ...")
    try:
        from tools.tool_cache import ToolCache

        return ToolCache().cache_tool(tool)
    except Exception as e:  # noqa: BLE001 — install failures must not abort the run
        print(f"[install_tools] FAIL {tool}: {e}")
        return False


def check_missing() -> list[str]:
    """Return tool names that the worker cannot currently resolve.

    Uses ``ToolRegistry`` (augmented PATH + extra dirs) plus the ToolCache
    fallback so tools installed only into the cache are still detected.
    """
    from tool_core.registry import ToolRegistry
    from tools.tool_cache import get_cached_tool

    registry = ToolRegistry()
    missing: list[str] = []
    for tool in GO_TOOL_MANIFEST:
        if registry.is_available(tool) or get_cached_tool(tool) is not None:
            continue
        missing.append(tool)
    for tool in ("sqlmap",):
        if not (registry.is_available(tool) or get_cached_tool(tool) is not None):
            missing.append(tool)
    return sorted(missing)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="install_tools",
        description="Provision the external security tool binaries Argus's agent needs.",
    )
    parser.add_argument(
        "tools",
        nargs="*",
        help="Specific tools to install (default: all Go manifest tools)",
    )
    parser.add_argument(
        "--pip",
        action="store_true",
        help="Also pip-install allowlisted Python tools (sqlmap, semgrep, ...)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only report which tools are missing; exit 1 if any are missing",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip SHA256 verification even on linux/amd64 (not recommended)",
    )
    args = parser.parse_args(argv)

    if args.check:
        missing = check_missing()
        if missing:
            print(
                f"[install_tools] MISSING {len(missing)} tool(s): {', '.join(missing)}"
            )
            print("[install_tools] Install with: python scripts/install_tools.py")
            for tool in missing:
                if tool in MANUAL_TOOLS:
                    print(f"  - {tool}: {MANUAL_TOOLS[tool]}")
            return 1
        print("[install_tools] All tools available. ✔")
        return 0

    targets = args.tools or list(GO_TOOL_MANIFEST)
    failures: list[str] = []

    for tool in targets:
        if tool in GO_TOOL_MANIFEST:
            if not install_go_tool(tool, verify_hash=not args.skip_verify):
                failures.append(tool)
        elif tool in PIP_ALLOWLIST:
            if not install_pip_tool(tool):
                failures.append(tool)
        else:
            print(f"[install_tools] SKIP {tool}: no manifest entry")
            if tool in MANUAL_TOOLS:
                print(f"  {MANUAL_TOOLS[tool]}")

    if args.pip:
        for tool in sorted(PIP_ALLOWLIST):
            if not install_pip_tool(tool):
                failures.append(tool)

    if failures:
        print(
            f"[install_tools] Done with {len(failures)} failure(s): {', '.join(failures)}"
        )
        return 1
    print("[install_tools] All requested tools installed. ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
