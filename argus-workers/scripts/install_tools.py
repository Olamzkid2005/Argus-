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
import shlex
import shutil
import subprocess
import sys
import tarfile
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

#: Release-asset naming differs per publisher, so it cannot be derived from the
#: platform alone. ProjectDiscovery publishes macOS builds as ``..._macOS_amd64``
#: (capitalised ``macOS``), while ffuf/dalfox publish ``..._darwin_*`` archives
#: and ship ``.tar.gz`` rather than ``.zip``. Building the URL from the
#: normalised platform name alone produced 404 HTML saved as a ``.zip``, which
#: surfaced as the unhelpful "downloaded file is not a valid zip".
_MACOS_ASSET_NAME = {"nuclei", "httpx", "katana", "subfinder"}
_TARBALL_TOOLS = {"ffuf", "dalfox"}

#: Tools with no darwin release asset at the pinned version. Installing them
#: needs a package manager instead of a GitHub download.
_NO_DARWIN_ASSET: dict[str, str] = {
    "ffuf": "Install via: brew install ffuf (no darwin asset at the pinned version)",
}

#: Tools installed through a package manager instead of a GitHub release
#: asset. ``name -> (manager, package, binary)``. ``binary`` is the name Argus
#: invokes, which is not always the package name (testssl ships ``testssl.sh``,
#: php-code-sniffer ships ``phpcs``).
SYSTEM_TOOL_MANIFEST: dict[str, tuple[str, str, str]] = {
    "trufflehog": ("brew", "trufflehog", "trufflehog"),
    "eslint": ("npm", "eslint", "eslint"),
    "testssl": ("brew", "testssl", "testssl"),
    # php-code-sniffer pulls a full PHP runtime; on platforms where Homebrew has
    # to build PHP from source this is a multi-hour install. Kept in the
    # manifest because on Linux/brew-bottle platforms it is a one-liner.
    "phpcs": ("brew", "php-code-sniffer", "phpcs"),
}

#: Tools published as a release archive on GitHub that is unpacked into the tool
#: cache and exposed through ``~/.local/bin``. ``name -> (repo, version,
#: asset_name_template, binary relative to the unpacked root)``.
#:
#: Used instead of Homebrew for JVM tools: brew resolves ``openjdk`` through an
#: llvm/rust source build on machines without bottles, while the JVM tools only
#: need the ``java`` already on PATH.
RELEASE_TOOL_MANIFEST: dict[str, tuple[str, str, str, str]] = {
    "dependency_check": (
        "jeremylong/DependencyCheck",
        "12.1.0",
        "dependency-check-{version}-release.zip",
        "dependency-check/bin/dependency-check.sh",
    ),
    "spotbugs": (
        "spotbugs/spotbugs",
        "4.10.5",
        "spotbugs-{version}.tgz",
        "spotbugs-{version}/bin/spotbugs",
    ),
}

#: Tools published only as a git checkout. ``name -> (github repo, entry
#: script, interpreter)``. A wrapper of the same name is written to
#: ``~/.local/bin`` because the upstream script names differ from the tool name
#: Argus dispatches (``jwt_tool.py``, ``bin/sniper``) and commix must run with
#: its checkout as the working directory.
GIT_TOOL_MANIFEST: dict[str, tuple[str, str, str]] = {
    "commix": ("commixproject/commix", "commix.py", "python"),
    "jwt_tool": ("ticarpi/jwt_tool", "jwt_tool.py", "python"),
    "sn1per": ("1N3/Sn1per", "sniper", "sh"),
    # Brakeman is installed from its own tag rather than from a .gem: the
    # RubyGems client shipped with macOS (2.6) can neither read the modern
    # index nor install brakeman >= 6, and 5.4.1 still runs on that Ruby.
    "brakeman": ("presidentbeef/brakeman", "bin/brakeman", "ruby"),
}

#: Git refs to check out when a specific tag is required.
_GIT_TOOL_REFS: dict[str, str] = {"brakeman": "v5.4.1"}

#: Binary names a package installs under a different name than Argus uses.
#: After a successful install the wrapper is linked into ``~/.local/bin`` so the
#: worker's augmented PATH resolves the name Argus actually invokes.
_SYSTEM_BINARY_ALIASES: dict[str, str] = {
    "testssl": "testssl.sh",
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
    """Build the pinned GitHub release asset URL for *tool* on the current platform.

    Raises ``RuntimeError`` when the publisher has no asset for the platform
    (ffuf on darwin) so the caller can print the package-manager alternative
    instead of downloading a 404 page.
    """
    if tool not in GO_TOOL_MANIFEST:
        raise KeyError(f"Tool {tool!r} has no binary manifest entry")
    repo, version = GO_TOOL_MANIFEST[tool]
    os_name, arch = normalize_platform(os_name, arch)
    if os_name == "darwin" and tool in _NO_DARWIN_ASSET:
        raise RuntimeError(_NO_DARWIN_ASSET[tool])
    asset_os = "macOS" if os_name == "darwin" and tool in _MACOS_ASSET_NAME else os_name
    ext = "tar.gz" if tool in _TARBALL_TOOLS else "zip"
    asset = f"{tool}_{version}_{asset_os}_{arch}.{ext}"
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
    force: bool = False,
) -> bool:
    """Download, verify, extract, and cache a single Go binary.

    An already-cached binary is reused (and just re-symlinked) unless *force*
    is set — re-running the installer must not re-download gigabytes, but it
    must repair ``~/go/bin`` symlinks that point at a stale cache path.

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

    if dest_binary.exists() and not force:
        print(
            f"[install_tools] OK {tool}: already cached at {dest_binary} "
            f"(pass --force to re-download)"
        )
        _symlink_tool(tool, dest_binary, os_name, symlink_dir)
        return True

    with tempfile.TemporaryDirectory(prefix="argus_install_") as tmp:
        suffix = "tar.gz" if url.endswith(".tar.gz") else "zip"
        archive_path = Path(tmp) / f"{tool}.{suffix}"
        try:
            result = subprocess.run(  # noqa: S603 — safe: list form, URL from pinned manifest
                ["curl", "-L", "-o", str(archive_path), url],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            print(f"[install_tools] FAIL {tool}: download timed out (10 min)")
            return False
        if result.returncode != 0 or not archive_path.exists():
            print(
                f"[install_tools] FAIL {tool}: curl error: {result.stderr[:200]}"
            )
            return False

        if verify_hash and expected_hash:
            actual = sha256_file(archive_path)
            if actual != expected_hash:
                print(
                    f"[install_tools] FAIL {tool}: SHA256 mismatch "
                    f"(expected {expected_hash}, got {actual}) — refusing corrupt download"
                )
                return False
            print(f"[install_tools] {tool}: SHA256 verification passed")

        tmp_bin = Path(tmp) / tool
        is_tarball = url.endswith(".tar.gz")
        try:
            if is_tarball:
                with tarfile.open(archive_path, "r:gz") as tf:
                    names = [m.name for m in tf.getmembers() if m.isfile()]
                    entry = find_binary_in_zip(names, tool)
                    if entry is None:
                        print(
                            f"[install_tools] FAIL {tool}: no binary entry in tarball "
                            f"(entries: {names[:8]})"
                        )
                        return False
                    member = tf.extractfile(entry)
                    if member is None:
                        print(f"[install_tools] FAIL {tool}: cannot read {entry} from tarball")
                        return False
                    with member, open(tmp_bin, "wb") as dst:
                        shutil.copyfileobj(member, dst)
            else:
                with zipfile.ZipFile(archive_path) as zf:
                    entry = find_binary_in_zip(zf.namelist(), tool)
                    if entry is None:
                        print(
                            f"[install_tools] FAIL {tool}: no binary entry in zip "
                            f"(entries: {zf.namelist()[:8]})"
                        )
                        return False
                    with zf.open(entry) as src, open(tmp_bin, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except (zipfile.BadZipFile, tarfile.TarError) as e:
            kind = "tar.gz" if is_tarball else "zip"
            print(
                f"[install_tools] FAIL {tool}: downloaded file is not a valid {kind} ({e}) — "
                f"check the asset name at {url}"
            )
            return False

        os.chmod(tmp_bin, 0o755)
        shutil.move(str(tmp_bin), str(dest_binary))
        print(f"[install_tools] OK {tool}: cached at {dest_binary}")

    _symlink_tool(tool, dest_binary, os_name, symlink_dir)
    return True


def _symlink_tool(
    tool: str,
    dest_binary: Path,
    os_name: str,
    symlink_dir: Path | None = None,
) -> None:
    """Point ``~/go/bin/<tool>`` at the cached binary.

    ToolRegistry resolves tools through PATH, so the cache alone is not enough.
    Always re-created (not just when missing) so a symlink left over from an
    old cache location is repaired on the next run.
    """
    if symlink_dir is None:
        symlink_dir = Path.home() / "go" / "bin"
    if os_name == "windows":
        return
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


def _link_into_user_bin(link_name: str, target: Path) -> bool:
    """Point ``~/.local/bin/<link_name>`` at *target* (idempotent)."""
    link_dir = Path.home() / ".local" / "bin"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / link_name
    try:
        if link.is_symlink() or link.exists():
            if link.resolve() == target.resolve():
                return True
            link.unlink()
        link.symlink_to(target)
        return True
    except OSError as e:
        print(f"[install_tools] WARNING could not link {link_name} -> {target}: {e}")
        return False


#: Fallback version for gem tools when the installed Ruby is too old for
#: latest. brakeman >= 6 requires Ruby >= 3.2; macOS ships 2.6 at /usr/bin/gem.
_GEM_FALLBACK_VERSION: dict[str, str] = {"brakeman": "5.4.1"}


def _user_gem_bin(binary: str) -> Path | None:
    """Locate a ``gem install --user-install`` executable (~/.gem/ruby/*/bin)."""
    for candidate in sorted((Path.home() / ".gem" / "ruby").glob(f"*/bin/{binary}")):
        if candidate.is_file():
            return candidate
    return None


def install_system_tool(tool: str) -> bool:
    """Install a package-manager tool (brew/gem/npm). Returns True when the binary resolves."""
    spec = SYSTEM_TOOL_MANIFEST.get(tool)
    if spec is None:
        print(f"[install_tools] SKIP {tool}: no system-package manifest entry")
        return False
    manager, package, binary = spec

    if shutil.which(binary):
        print(f"[install_tools] OK {tool}: already installed ({shutil.which(binary)})")
        return True

    if manager == "gem":
        cmd = ["gem", "install", "--user-install", package]
    elif manager == "brew":
        cmd = ["brew", "install", package]
    elif manager == "npm":
        cmd = ["npm", "install", "-g", package]
    else:
        print(f"[install_tools] SKIP {tool}: unknown package manager {manager!r}")
        return False

    if shutil.which(manager) is None:
        print(f"[install_tools] SKIP {tool}: {manager} is not installed")
        return False

    print(f"[install_tools] Installing {tool} via {manager} ({package}) ...")
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603 — list form, pinned manifest
    if result.returncode != 0 and manager == "gem":
        # Older system Rubies cannot run the current release; retry with the
        # last version that supports them rather than leaving the tool absent.
        fallback = _GEM_FALLBACK_VERSION.get(tool)
        if fallback:
            print(
                f"[install_tools] RETRY {tool}: latest needs a newer Ruby — "
                f"installing pinned {fallback}"
            )
            result = subprocess.run(  # noqa: S603 — list form, pinned version
                ["gem", "install", "--user-install", package, "-v", fallback],
                capture_output=True,
                text=True,
            )
    if result.returncode != 0:
        print(f"[install_tools] FAIL {tool}: {manager} exit {result.returncode}: {result.stderr[-300:]}")
        return False

    found = shutil.which(binary)
    if found:
        print(f"[install_tools] OK {tool}: {found}")
        return True

    # gem --user-install writes to ~/.gem/ruby/<ver>/bin, which is not on PATH.
    user_bin = _user_gem_bin(binary)
    if user_bin and _link_into_user_bin(tool, user_bin):
        print(f"[install_tools] OK {tool}: linked {user_bin} into ~/.local/bin")
        return True

    # Package installed under upstream's own binary name (testssl -> testssl.sh).
    alias = _SYSTEM_BINARY_ALIASES.get(tool)
    alias_path = shutil.which(alias) if alias else None
    if alias_path and _link_into_user_bin(tool, Path(alias_path)):
        print(f"[install_tools] OK {tool}: linked {alias} as {tool} in ~/.local/bin")
        return True

    print(
        f"[install_tools] FAIL {tool}: {manager} reported success but no "
        f"{binary!r} binary is on PATH"
    )
    return False


def install_git_tool(tool: str) -> bool:
    """Clone a git-only tool into the cache and expose a wrapper on PATH."""
    spec = GIT_TOOL_MANIFEST.get(tool)
    if spec is None:
        print(f"[install_tools] SKIP {tool}: no git manifest entry")
        return False
    repo, script, interpreter = spec

    if shutil.which(tool):
        print(f"[install_tools] OK {tool}: already on PATH ({shutil.which(tool)})")
        return True

    checkout = TOOL_CACHE_DIR / tool
    entry = checkout / script
    if not entry.exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        print(f"[install_tools] Cloning {tool} from github.com/{repo} ...")
        clone_cmd = ["git", "clone", "--depth", "1"]
        ref = _GIT_TOOL_REFS.get(tool)
        if ref:
            clone_cmd += ["--branch", ref]
        clone_cmd += [f"https://github.com/{repo}.git", str(checkout)]
        result = subprocess.run(  # noqa: S603 — list form, repo from pinned manifest
            clone_cmd, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[install_tools] FAIL {tool}: git clone failed: {result.stderr[-300:]}")
            return False

    if not entry.exists():
        print(f"[install_tools] FAIL {tool}: {script} not found in the checkout")
        return False
    try:
        entry.chmod(entry.stat().st_mode | 0o755)
    except OSError:
        pass  # read-only checkout — the interpreter still reads it

    # Wrapper, because upstream's entry script is not named after the tool and
    # commix resolves its ``src`` package relative to the working directory.
    # The absolute checkout path is baked in so an ARGUS_TOOL_CACHE_DIR
    # override keeps working.
    wrapper = Path.home() / ".local" / "bin" / tool
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    root = str(checkout)
    if interpreter == "python":
        body = (
            "#!/usr/bin/env python3\n"
            f'"""Wrapper for the {tool} checkout (Argus invokes `{tool}`)."""\n'
            "import os\nimport runpy\nimport sys\n\n"
            f"root = {root!r}\n"
            "os.chdir(root)\nsys.path.insert(0, root)\n"
            f"script = os.path.join(root, {script!r})\n"
            'sys.argv[0] = script\nrunpy.run_path(script, run_name="__main__")\n'
        )
    else:
        body = (
            "#!/bin/sh\n"
            f"# Argus invokes `{tool}`; the {tool} checkout ships {script}.\n"
            f'exec {shlex.quote(str(entry))} "$@"\n'
        )
    try:
        wrapper.write_text(body)
        wrapper.chmod(0o755)
    except OSError as e:
        print(f"[install_tools] FAIL {tool}: cannot write wrapper {wrapper}: {e}")
        return False

    print(f"[install_tools] OK {tool}: wrapper at {wrapper}")
    return True


def install_release_tool(tool: str) -> bool:
    """Unpack a pinned GitHub release archive into the cache and link its binary.

    Used for JVM tools (dependency-check, spotbugs): Homebrew would resolve
    their ``openjdk`` dependency through an llvm/rust source build on machines
    without bottles, while the archives only need the ``java`` on PATH.
    """
    spec = RELEASE_TOOL_MANIFEST.get(tool)
    if spec is None:
        print(f"[install_tools] SKIP {tool}: no release-archive manifest entry")
        return False
    repo, version, asset_template, bin_template = spec

    if shutil.which(binary_for(tool)):
        print(f"[install_tools] OK {tool}: already on PATH ({shutil.which(binary_for(tool))})")
        return True

    asset = asset_template.format(version=version)
    bin_rel = bin_template.format(version=version)
    url = f"https://github.com/{repo}/releases/download/v{version}/{asset}"
    dest = TOOL_CACHE_DIR / tool
    dest.mkdir(parents=True, exist_ok=True)

    print(f"[install_tools] Downloading {tool} {version} ...")
    with tempfile.TemporaryDirectory(prefix="argus_release_") as tmp:
        archive = Path(tmp) / asset
        result = subprocess.run(  # noqa: S603 — list form, URL from pinned manifest
            ["curl", "-sSL", "--max-time", "900", "-o", str(archive), url],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not archive.exists():
            print(f"[install_tools] FAIL {tool}: download failed: {result.stderr[-200:]}")
            return False
        try:
            if asset.endswith(".zip"):
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(dest)
            else:
                with tarfile.open(archive, "r:*") as tf:
                    tf.extractall(dest)  # noqa: S202 — pinned upstream archive
        except (zipfile.BadZipFile, tarfile.TarError) as e:
            print(f"[install_tools] FAIL {tool}: cannot unpack {asset}: {e}")
            return False

    binary_path = dest / bin_rel
    if not binary_path.exists():
        print(f"[install_tools] FAIL {tool}: {bin_rel} missing after unpack")
        return False
    try:
        binary_path.parent.joinpath(binary_path.name).chmod(0o755)
        for sibling in binary_path.parent.iterdir():
            if sibling.is_file() and sibling.suffix in ("", ".sh"):
                sibling.chmod(0o755)
    except OSError:
        pass

    if not _link_into_user_bin(binary_for(tool), binary_path):
        return False
    print(f"[install_tools] OK {tool}: linked {binary_path} into ~/.local/bin")
    return True


def binary_for(tool: str) -> str:
    """Binary name Argus invokes for *tool* (differs from the package name)."""
    if tool in SYSTEM_TOOL_MANIFEST:
        return SYSTEM_TOOL_MANIFEST[tool][2]
    if tool == "dependency_check":
        return "dependency-check"
    return tool


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
    try:
        from tool_core.registry import ToolRegistry
        from tools.tool_cache import get_cached_tool
    except ImportError as e:
        # The workers package targets Python 3.11 (``datetime.UTC`` and friends).
        # On 3.10 this import fails deep inside tool_core and the traceback says
        # nothing about the real cause, so name the actual problem.
        raise RuntimeError(
            f"cannot import the tool registry ({e}) — the workers require Python 3.11+ "
            f"but this interpreter is {platform.python_version()}. "
            "Recreate the venv with python3.11: "
            "python3.11 -m venv venv && . venv/bin/activate && pip install -r requirements.txt"
        ) from e

    registry = ToolRegistry()
    missing: list[str] = []
    for tool in GO_TOOL_MANIFEST:
        if registry.is_available(tool) or get_cached_tool(tool) is not None:
            continue
        missing.append(tool)
    for tool, (_manager, _package, binary) in SYSTEM_TOOL_MANIFEST.items():
        if not (registry.is_available(binary) or (Path.home() / ".local" / "bin" / tool).exists()):
            missing.append(tool)
    for tool in GIT_TOOL_MANIFEST:
        if not registry.is_available(tool):
            missing.append(tool)
    for tool in RELEASE_TOOL_MANIFEST:
        if not registry.is_available(binary_for(tool)):
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download tools that are already cached",
    )
    parser.add_argument(
        "--system",
        action="store_true",
        help="Also install package-manager tools (trufflehog, spotbugs, phpcs, eslint, brakeman, ...)",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Also install git-only tools (commix, jwt_tool, sn1per, brakeman)",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Also install release-archive tools (dependency_check, spotbugs)",
    )
    args = parser.parse_args(argv)

    if args.check:
        try:
            missing = check_missing()
        except RuntimeError as e:
            print(f"[install_tools] ERROR: {e}")
            return 1
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
            if not install_go_tool(
                tool, verify_hash=not args.skip_verify, force=args.force
            ):
                failures.append(tool)
        elif tool in SYSTEM_TOOL_MANIFEST:
            if not install_system_tool(tool):
                failures.append(tool)
        elif tool in GIT_TOOL_MANIFEST:
            if not install_git_tool(tool):
                failures.append(tool)
        elif tool in RELEASE_TOOL_MANIFEST:
            if not install_release_tool(tool):
                failures.append(tool)
        elif tool in PIP_ALLOWLIST:
            if not install_pip_tool(tool):
                failures.append(tool)
        else:
            print(f"[install_tools] SKIP {tool}: no manifest entry")
            if tool in MANUAL_TOOLS:
                print(f"  {MANUAL_TOOLS[tool]}")

    if args.system:
        for tool in SYSTEM_TOOL_MANIFEST:
            if not install_system_tool(tool):
                failures.append(tool)

    if args.git:
        for tool in GIT_TOOL_MANIFEST:
            if not install_git_tool(tool):
                failures.append(tool)

    if args.release:
        for tool in RELEASE_TOOL_MANIFEST:
            if not install_release_tool(tool):
                failures.append(tool)

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
