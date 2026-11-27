"""
Provision every external security tool Argus relies on — the only entry point.

Argus's agent spawns real binaries (nuclei, httpx, katana, subfinder, ffuf,
dalfox, sqlmap, ...). When a binary is missing, tool calls fail LOUDLY with
``NOT_INSTALLED`` status (see ``tools/tool_runner.py``) instead of silently
degrading to fallback scanners. This script closes that gap on Linux, macOS
and Windows:

- **Go binaries** — downloaded from pinned GitHub release assets, verified
  against pinned SHA256 checksums on linux/amd64, extracted into the shared
  ToolCache directory, and exposed on PATH through ``~/go/bin`` (symlink on
  POSIX, copy on Windows, where symlinks need elevation).
- **Release archives** (dependency-check, spotbugs) — unpacked into the cache
  and linked, picking the ``.sh``/``.bat`` entry point per platform.
- **Git-only tools** (commix, jwt_tool, sn1per, brakeman) — cloned into the
  cache with a wrapper (``.cmd`` on Windows) matching the name Argus invokes.
- **Package-manager tools** (trufflehog, phpcs, eslint) — brew/npm/gem on
  POSIX, npm plus winget/scoop/choco on Windows.
- **Python tools** (semgrep, sqlmap, bandit, pip-audit, wafw00f, arjun) — pip
  through this same script, never ad hoc.
- **Tool assets** — the pinned nuclei template set, cloned once into
  ``tool_assets/``.

Nothing else in the repo installs tool binaries; workers only *check* for them
(``--check``, ``start_worker.sh``) and print this script as the fix.

Usage::

    python scripts/install_tools.py              # install everything
    python scripts/install_tools.py --check      # report missing tools, exit 1 if any
    python scripts/install_tools.py nuclei httpx # install specific tools
    python scripts/install_tools.py --go-only    # only pinned Go binaries
    python scripts/install_tools.py --no-assets  # skip the nuclei template set

A required tool that cannot be provisioned on this host makes the run exit 1,
instead of printing success with a scanner still missing; tools with no build
for the current OS at all are reported separately and do not fail it.
"""

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# Allow `python scripts/install_tools.py` to import the workers package.
WORKERS_ROOT = Path(__file__).parent.parent
if str(WORKERS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKERS_ROOT))

from tools.tool_cache import PIP_ALLOWLIST, TOOL_CACHE_DIR, TOOL_VERSIONS  # noqa: E402

#: Windows needs no translation of asset names, but it does need ``.exe``
#: suffixes and copy-instead-of-symlink when exposing binaries on PATH.
IS_WINDOWS = os.name == "nt"

#: Interpreter commands that only exist on POSIX. A git tool needing one is
#: skipped on Windows with an explicit message rather than a broken wrapper.
_POSIX_ONLY_INTERPRETERS = {"sh"}


def binary_filename(tool: str, os_name: str | None = None) -> str:
    """Filename the tool's executable has on *os_name* (default: this host)."""
    if os_name is None:
        os_name = "windows" if IS_WINDOWS else platform.system().lower()
    if os_name == "windows" and not tool.lower().endswith((".exe", ".bat", ".cmd")):
        return f"{tool}.exe"
    return tool


def _link_filename(tool: str, target: Path | None = None) -> str:
    """Name to expose *tool* under in the user bin directory.

    On Windows the launched name must carry its real suffix (``.exe``,
    ``.bat``, ``.cmd``) or PATH lookup cannot find it; on POSIX the plain name
    is what Argus invokes.
    """
    if not IS_WINDOWS:
        return tool
    if target is not None and target.suffix.lower() in (".exe", ".bat", ".cmd"):
        return f"{tool}{target.suffix.lower()}"
    return f"{tool}.exe"

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

#: Per-(tool, platform) archive overrides. ffuf publishes ``.tar.gz`` for
#: linux/darwin but a ``.zip`` for windows at the pinned version; dalfox keeps
#: ``.tar.gz`` everywhere (its windows asset is ``..._windows_amd64.tar.gz``).
_ARCHIVE_SUFFIX: dict[tuple[str, str], str] = {("ffuf", "windows"): "zip"}

#: Tools with no darwin release asset at the pinned version. Installing them
#: needs a package manager instead of a GitHub download.
_NO_DARWIN_ASSET: dict[str, str] = {
    "ffuf": "Install via: brew install ffuf (no darwin asset at the pinned version)",
}

#: Homebrew package used when a tool has no release asset for this platform.
_BREW_FALLBACK: dict[str, str] = {"ffuf": "ffuf"}

#: Tools installed through a package manager instead of a GitHub release
#: asset. ``name -> (manager, package, binary)``. ``binary`` is the name Argus
#: invokes, which is not always the package name (testssl ships ``testssl.sh``,
#: php-code-sniffer ships ``phpcs``).
SYSTEM_TOOL_MANIFEST: dict[str, tuple[str, str, str]] = {
    "trufflehog": ("brew", "trufflehog", "trufflehog"),
    "eslint": ("npm", "eslint", "eslint"),
    "testssl": ("brew", "testssl", "testssl"),
    "nmap": ("brew", "nmap", "nmap"),
    "whatweb": ("brew", "whatweb", "whatweb"),
    "nikto": ("brew", "nikto", "nikto"),
    "wpscan": ("gem", "wpscan", "wpscan"),
    # php-code-sniffer pulls a full PHP runtime; on platforms where Homebrew has
    # to build PHP from source this is a multi-hour install. Kept in the
    # manifest because on Linux/brew-bottle platforms it is a one-liner.
    "phpcs": ("brew", "php-code-sniffer", "phpcs"),
}

#: Windows has no Homebrew. ``tool -> (manager, package)``; ``npm`` needs no
#: entry because it is already cross-platform. The manager list is tried in
#: order and the first one present on PATH wins.
_WINDOWS_SYSTEM_PACKAGES: dict[str, list[tuple[str, str]]] = {
    "trufflehog": [
        ("winget", "TruffleSecurity.TruffleHog"),
        ("scoop", "trufflehog"),
        ("choco", "trufflehog"),
    ],
    # testssl/nikto/whatweb/wpscan/phpcs are scripts: they have no Windows
    # package, so install_tools leaves them to
    # scripts/windows/install-portable-tools.py (runtime + launcher .exe).
    "testssl": [],
    "nmap": [
        ("winget", "Insecure.Nmap"),
        ("scoop", "nmap"),
        ("choco", "nmap"),
    ],
    "whatweb": [],  # Ruby tool: installed by the portable installer
    "nikto": [],  # Perl tool: installed by the portable installer
    "wpscan": [],  # Ruby gem: installed by the portable installer
    "phpcs": [
        ("scoop", "phpcs"),
        ("choco", "php-codesniffer"),
    ],
}

#: Go tools with no release-asset manifest entry: installed with ``go install``
#: (the same command the project used to document by hand). Requires a Go
#: toolchain; the installer reports a skip when it is absent.
GO_INSTALL_MANIFEST: dict[str, str] = {
    "amass": "github.com/owasp-amass/amass/v4/...@latest",
    "naabu": "github.com/projectdiscovery/naabu/v2/cmd/naabu@latest",
    "gau": "github.com/lc/gau/v2/cmd/gau@latest",
    "waybackurls": "github.com/tomnomnom/waybackurls@latest",
    "gospider": "github.com/jaeles-project/gospider@latest",
    "alterx": "github.com/projectdiscovery/alterx/cmd/alterx@latest",
}

#: Tools that are useful but not required for a working install (they need a
#: language runtime the host may not have, e.g. phpcs needs PHP). ``--check``
#: reports them separately and does not fail the run.
OPTIONAL_TOOLS: frozenset[str] = frozenset({"phpcs"})

#: Genuine PyPI distributions Argus dispatches. Deliberately excludes the
#: allowlist entries that are Go binaries — pip-installing those only fetches
#: an unrelated same-named package.
PIP_TOOL_MANIFEST: dict[str, str] = {
    "semgrep": "semgrep",
    "sqlmap": "sqlmap",
    "bandit": "bandit",
    "pip-audit": "pip-audit",
    "wafw00f": "wafw00f",
    "arjun": "arjun",
}

#: Tools published as a release archive on GitHub that is unpacked into the tool
#: cache and exposed through ``~/.local/bin``. ``name -> (repo, version,
#: asset_name_template, posix_binary, windows_binary)``, the binaries being
#: relative to the unpacked root.
#:
#: Used instead of Homebrew for JVM tools: brew resolves ``openjdk`` through an
#: llvm/rust source build on machines without bottles, while the JVM tools only
#: need the ``java`` already on PATH.
RELEASE_TOOL_MANIFEST: dict[str, tuple[str, str, str, str, str]] = {
    "dependency_check": (
        "jeremylong/DependencyCheck",
        "12.1.0",
        "dependency-check-{version}-release.zip",
        "dependency-check/bin/dependency-check.sh",
        "dependency-check/bin/dependency-check.bat",
    ),
    "spotbugs": (
        "spotbugs/spotbugs",
        "4.10.5",
        "spotbugs-{version}.tgz",
        "spotbugs-{version}/bin/spotbugs",
        "spotbugs-{version}/bin/spotbugs.bat",
    ),
}

#: Nuclei template set (an asset, not a binary) cloned once into tool_assets/.
NUCLEI_TEMPLATES_REPO = "https://github.com/projectdiscovery/nuclei-templates.git"
NUCLEI_TEMPLATES_DIR = WORKERS_ROOT / "tool_assets" / "nuclei-templates"

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

#: Hints shown when a tool cannot be installed on the current platform even
#: though the installer knows how to provision it elsewhere.
MANUAL_TOOLS: dict[str, str] = {
    "testssl": "POSIX shell script — run under WSL/Git Bash on Windows",
    "whatweb": "Ruby/POSIX loader — run under WSL on Windows",
    "nikto": "Perl tool — run under WSL on Windows",
    "wpscan": "needs a Ruby toolchain (gem install wpscan)",
    "phpcs": "needs PHP; install PHP_CodeSniffer manually when brew has no PHP bottle",
    "sn1per": "POSIX shell script — run under WSL/Git Bash on Windows",
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
    ext = _ARCHIVE_SUFFIX.get((tool, os_name))
    if ext is None:
        ext = "tar.gz" if tool in _TARBALL_TOOLS else "zip"
    asset = f"{tool}_{version}_{asset_os}_{arch}.{ext}"
    return f"https://github.com/{repo}/releases/download/v{version}/{asset}"


def find_binary_in_zip(namelist: list[str], tool: str) -> str | None:
    """Return the zip entry that contains the *tool* binary.

    Handles both flat layouts (``nuclei``) and versioned-dir layouts
    (``nuclei_3.2.0_linux_amd64/nuclei``). Skips docs/license files.
    """
    wanted = {tool, f"{tool}.exe"}
    candidates: list[str] = []
    for name in namelist:
        base = Path(name).name
        if base not in wanted:
            continue
        if name.endswith((".md", ".txt", ".LICENSE", "LICENSE")):
            continue
        candidates.append(name)
    if not candidates:
        return None
    # Prefer the shallowest path (root-level binary).
    return min(candidates, key=lambda n: n.count("/"))


def _download(url: str, dest: Path, *, timeout: int = 600) -> tuple[bool, str]:
    """Download *url* to *dest* on any platform.

    Prefers ``curl`` (present on macOS, most Linux distros and Windows 10+)
    and falls back to ``urllib`` so a stripped Windows image without curl.exe
    still works. Returns ``(ok, error_text)``.
    """
    curl = shutil.which("curl")
    if curl:
        try:
            result = subprocess.run(  # noqa: S603 — list form, URL from pinned manifest
                [curl, "-sSL", "--max-time", str(timeout), "-o", str(dest), url],
                capture_output=True,
                text=True,
                timeout=timeout + 30,
            )
        except subprocess.TimeoutExpired:
            return False, f"download timed out ({timeout}s)"
        if result.returncode == 0 and dest.exists():
            return True, ""
        return False, (result.stderr or f"curl exit {result.returncode}")[:200]

    request = urllib.request.Request(url, headers={"User-Agent": "argus-install-tools"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(
            dest, "wb"
        ) as out:
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)[:200]
    return True, ""


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
) -> bool | None:
    """Download, verify, extract, and cache a single Go binary.

    An already-cached binary is reused (and just re-symlinked) unless *force*
    is set — re-running the installer must not re-download gigabytes, but it
    must repair ``~/go/bin`` symlinks that point at a stale cache path.

    Returns ``True`` on success, ``False`` on a real failure, and ``None`` when
    this platform has no release asset (and no package-manager fallback).
    Never raises for network/parse failures — logs the error and returns
    ``False`` so the caller can continue with other tools.
    """
    print(f"[install_tools] Installing {tool} ...")
    try:
        os_name, _arch = normalize_platform()
    except RuntimeError as e:
        print(f"[install_tools] FAIL {tool}: {e}")
        return False

    if not force:
        on_path = _find_native_binary(tool)
        if on_path:
            print(f"[install_tools] OK {tool}: already on PATH ({on_path})")
            return True

    try:
        url = asset_url(tool, os_name, _arch)
    except (KeyError, RuntimeError) as e:
        # No release asset for this platform — use the package manager instead
        # of leaving a required scanner missing.
        fallback_package = _BREW_FALLBACK.get(tool)
        if (
            fallback_package
            and os_name == "darwin"
            and shutil.which("brew")
        ):
            return _brew_install_binary(tool, fallback_package)
        print(f"[install_tools] SKIP {tool}: {e}")
        return None

    expected_hash = TOOL_VERSIONS.get(tool + "_sha256") or ""
    if (os_name != "linux" or _arch != "amd64") and expected_hash:
        print(
            f"[install_tools] WARNING {tool}: pinned SHA256 is for linux/amd64; "
            f"skipping checksum verification for {os_name}/{_arch}"
        )
        verify_hash = False

    dest_dir = TOOL_CACHE_DIR / tool
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_binary = dest_dir / binary_filename(tool, os_name)

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
        ok, error = _download(url, archive_path)
        if not ok:
            print(f"[install_tools] FAIL {tool}: download error: {error}")
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

        tmp_bin = Path(tmp) / binary_filename(tool, os_name)
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

        if os_name != "windows":
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
    try:
        symlink_dir.mkdir(parents=True, exist_ok=True)
        link = symlink_dir / binary_filename(tool, os_name)
        if link.exists() or link.is_symlink():
            link.unlink()
        if os_name == "windows":
            # Creating symlinks on Windows needs Developer Mode or elevation;
            # copying keeps a single `install_tools.py` run working either way.
            shutil.copy2(dest_binary, link)
            print(f"[install_tools] OK {tool}: copied to {link}")
        else:
            link.symlink_to(dest_binary)
            print(f"[install_tools] OK {tool}: symlinked to {link}")
    except OSError as e:
        print(
            f"[install_tools] WARNING {tool}: could not expose binary in {symlink_dir}: {e}"
        )


def _link_into_user_bin(link_name: str, target: Path) -> bool:
    """Expose *target* as ``~/.local/bin/<link_name>`` (idempotent).

    POSIX gets a symlink; Windows gets a copy under the target's real suffix
    (``.exe``/``.bat``/``.cmd``) because symlinks there require elevation and
    PATH lookup needs the suffix.
    """
    link_dir = Path.home() / ".local" / "bin"
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / _link_filename(link_name, target)
    try:
        if IS_WINDOWS:
            if link.is_symlink() or link.exists():
                link.unlink()
            shutil.copy2(target, link)
            return True
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


def _is_python_console_script(path: Path) -> bool:
    """Whether *path* is a pip console script rather than a real binary.

    The venv ships scripts whose names collide with the ProjectDiscovery
    binaries: ``venv/bin/httpx`` is the *Python* HTTPX CLI, so resolving it as
    ``httpx`` executes the wrong program (see
    ``mcp_server._augmented_tool_path``). The shebang tells the two apart
    without shelling out, and a Windows ``.exe`` never matches.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(64)
    except OSError:
        return False
    if not head.startswith(b"#!"):
        return False
    return b"python" in head.lower()


def _find_binary(binary: str) -> str | None:
    """Locate *binary* on PATH, then in the Windows package-manager shims."""
    found = shutil.which(binary)
    if found:
        return found
    # Console scripts installed by this venv's pip (semgrep, pip-audit, ...)
    # are not on PATH until the worker augments it.
    interpreter_dir = Path(sys.executable).parent
    for candidate in (
        interpreter_dir / f"{binary}.exe",
        interpreter_dir / binary,
    ):
        if candidate.is_file():
            return str(candidate)
    if not IS_WINDOWS:
        return None
    roots = [
        Path.home() / "scoop" / "shims",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path("C:/ProgramData/chocolatey/bin"),
    ]
    for root in roots:
        for candidate in (
            root / f"{binary}.exe",
            root / f"{binary}.bat",
            root / f"{binary}.cmd",
            root / binary,
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def _find_native_binary(tool: str) -> str | None:
    """Locate the *native* build of *tool*, ignoring Python console scripts.

    Used for every tool that is downloaded as a compiled binary: a pip script
    of the same name must not satisfy the lookup, or the installer reports
    success while the scanner it was asked for is still absent.
    """
    found = _find_binary(tool)
    if found and _is_python_console_script(Path(found)):
        return None
    return found


def _unsupported_on_this_platform(tool: str) -> bool:
    """Whether *tool* has no installer on this OS at all.

    Distinguishes "this platform has no build of the tool" (informational)
    from "this host lacks the manager/runtime needed for it" (a real gap that
    must fail the run), so the Windows-only and POSIX-only tools stay quiet on
    the platform that cannot run them either way.
    """
    if tool in GIT_TOOL_MANIFEST:
        return IS_WINDOWS and GIT_TOOL_MANIFEST[tool][2] in _POSIX_ONLY_INTERPRETERS
    if tool in SYSTEM_TOOL_MANIFEST:
        manager = SYSTEM_TOOL_MANIFEST[tool][0]
        return (
            IS_WINDOWS
            and manager in ("brew", "gem")
            and not _WINDOWS_SYSTEM_PACKAGES.get(tool)
        )
    return False


#: Homebrew bottle tags by macOS major version. A formula with no bottle for
#: the host means `brew install` compiles it from source — for phpcs that is a
#: full PHP toolchain, which can run for hours and then fail on missing CLT.
def _brew_platform_tag() -> str | None:
    if platform.system() != "Darwin":
        return None
    major = int((platform.mac_ver()[0] or "0").split(".")[0] or 0)
    names = {11: "big_sur", 12: "monterey", 13: "ventura", 14: "sonoma", 15: "sequoia"}
    tag = names.get(major)
    if platform.machine().lower() in ("arm64", "aarch64"):
        return f"arm64_{tag}" if tag else "arm64"
    return tag


def _brew_formulae(packages: list[str]) -> list[dict] | None:
    """``brew info --json=v2`` for *packages*, or None if brew could not tell."""
    try:
        result = subprocess.run(  # noqa: S603 — package names from the pinned manifest
            ["brew", "info", "--json=v2", *packages],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get("formulae", [])
    except (ValueError, AttributeError):
        return None


def _brew_bottle_available(package: str) -> bool | None:
    """Whether Homebrew can install *package* from a bottle on this host.

    Checks the formula *and its direct dependencies*: php-code-sniffer is
    bottled everywhere, but its ``php`` dependency is not bottled for older
    Intel macOS, so ``brew install`` silently starts a multi-hour source
    build (which then fails on missing Command Line Tools).

    ``None`` means "could not tell" (old brew, offline) — the caller then tries
    the install rather than skipping a tool it could have provisioned.
    """
    tag = _brew_platform_tag()
    if tag is None:
        return None
    formulae = _brew_formulae([package])
    if not formulae:
        return None
    def files_for(formula: dict) -> dict | None:
        bottle = formula.get("bottle")
        if not isinstance(bottle, dict):
            return None
        stable = bottle.get("stable")
        if not isinstance(stable, dict):
            return None
        files = stable.get("files")
        return files if isinstance(files, dict) else None

    formula = formulae[0]
    target_files = files_for(formula)
    if target_files is None:
        # No bottle metadata for the target formula itself (trufflehog-style
        # taps). A Go source build is quick, so let brew try.
        return None
    if "all" not in target_files and tag not in target_files:
        return None

    deps = formula.get("dependencies") or []
    if not deps:
        return True
    dep_formulae = _brew_formulae(deps)
    if dep_formulae is None:
        return None
    for dep in dep_formulae:
        dep_files = files_for(dep)
        if dep_files is None or (
            "all" not in dep_files and tag not in dep_files
        ):
            # A source-built dependency is the multi-hour trap (php for phpcs).
            return False
    return True


def _brew_install_binary(tool: str, package: str) -> bool | None:
    """Install *package* with Homebrew and resolve *tool* afterwards."""
    print(f"[install_tools] Installing {tool} via brew ({package}) ...")
    result = subprocess.run(  # noqa: S603 — package name from the pinned manifest
        ["brew", "install", package], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[install_tools] FAIL {tool}: brew exit {result.returncode}: {result.stderr[-300:]}")
        return False
    found = _find_binary(tool) or _find_binary(package)
    if found:
        print(f"[install_tools] OK {tool}: {found}")
        return True
    print(f"[install_tools] FAIL {tool}: brew reported success but {tool!r} is not on PATH")
    return False


def _system_install_command(tool: str, manager: str, package: str) -> list[str] | None:
    """Command that installs *tool* with *manager* on this platform."""
    if manager == "gem":
        return ["gem", "install", "--user-install", package]
    if manager == "brew":
        return ["brew", "install", package]
    if manager == "npm":
        return ["npm", "install", "-g", package]
    if manager == "winget":
        return [
            "winget",
            "install",
            "--id",
            package,
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    if manager == "scoop":
        return ["scoop", "install", package]
    if manager == "choco":
        return ["choco", "install", package, "--yes"]
    return None


def install_system_tool(tool: str) -> bool | None:
    """Install a package-manager tool.

    Returns ``True`` when the binary resolves, ``False`` on a real failure, and
    ``None`` when this platform has no way to install the tool (an optional
    tool, or no manager present) so the caller can skip without failing.
    """
    spec = SYSTEM_TOOL_MANIFEST.get(tool)
    if spec is None:
        print(f"[install_tools] SKIP {tool}: no system-package manifest entry")
        return None
    manager, package, binary = spec

    found = _find_binary(binary) or _find_binary(tool)
    if found:
        print(f"[install_tools] OK {tool}: already installed ({found})")
        return True

    candidates: list[tuple[str, str]] = [(manager, package)]
    if IS_WINDOWS and manager in ("brew", "gem"):
        # No Homebrew on Windows: fall through to winget/scoop/choco.
        candidates = _WINDOWS_SYSTEM_PACKAGES.get(tool, [])
        if not candidates:
            hint = MANUAL_TOOLS.get(tool, "install it manually")
            print(f"[install_tools] SKIP {tool}: not available on Windows — {hint}")
            return None

    executed = False
    for candidate_manager, candidate_package in candidates:
        cmd = _system_install_command(tool, candidate_manager, candidate_package)
        if cmd is None:
            print(f"[install_tools] SKIP {tool}: unknown package manager {candidate_manager!r}")
            continue
        if shutil.which(candidate_manager) is None:
            print(f"[install_tools] SKIP {tool}: {candidate_manager} is not installed")
            continue

        if candidate_manager == "brew" and _brew_bottle_available(candidate_package) is False:
            print(
                f"[install_tools] SKIP {tool}: no Homebrew bottle for this macOS "
                f"({_brew_platform_tag()}); brew would build {candidate_package} "
                "from source"
            )
            continue

        executed = True
        print(f"[install_tools] Installing {tool} via {candidate_manager} ({candidate_package}) ...")
        result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603 — list form, pinned manifest
        if result.returncode != 0 and candidate_manager == "gem":
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
            print(
                f"[install_tools] FAIL {tool}: {candidate_manager} exit "
                f"{result.returncode}: {result.stderr[-300:]}"
            )
            continue

        found = _find_binary(binary) or _find_binary(tool)
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
        alias_path = _find_binary(alias) if alias else None
        if alias_path and _link_into_user_bin(tool, Path(alias_path)):
            print(f"[install_tools] OK {tool}: linked {alias} as {tool} in ~/.local/bin")
            return True

        print(
            f"[install_tools] FAIL {tool}: {candidate_manager} reported success but no "
            f"{binary!r} binary is on PATH"
        )

    if not executed:
        hint = MANUAL_TOOLS.get(tool, "install it manually")
        print(f"[install_tools] SKIP {tool}: no usable package manager — {hint}")
        return None
    return False


def install_git_tool(tool: str) -> bool | None:
    """Clone a git-only tool into the cache and expose a wrapper on PATH."""
    spec = GIT_TOOL_MANIFEST.get(tool)
    if spec is None:
        print(f"[install_tools] SKIP {tool}: no git manifest entry")
        return False
    repo, script, interpreter = spec

    already = _find_binary(tool)
    if already:
        print(f"[install_tools] OK {tool}: already on PATH ({already})")
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
    root = str(checkout)
    if IS_WINDOWS:
        if interpreter in _POSIX_ONLY_INTERPRETERS:
            print(
                f"[install_tools] SKIP {tool}: {script} needs a POSIX shell "
                "(WSL/Git Bash); not installed on Windows"
            )
            return None
        wrapper = Path.home() / ".local" / "bin" / f"{tool}.cmd"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        if interpreter == "python":
            program, invoked = sys.executable, [script]
        else:  # ruby
            program, invoked = interpreter, [script]
        args = " ".join(f'"{arg}"' for arg in invoked)
        body = (
            "@echo off\r\n"
            f"rem Argus invokes `{tool}`; the checkout ships {script}.\r\n"
            f'cd /d "{root}"\r\n'
            f'"{program}" {args} %*\r\n'
        )
    else:
        wrapper = Path.home() / ".local" / "bin" / tool
        wrapper.parent.mkdir(parents=True, exist_ok=True)
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
        if not IS_WINDOWS:
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
    repo, version, asset_template, posix_bin, windows_bin = spec

    already = _find_binary(binary_for(tool))
    if already:
        print(f"[install_tools] OK {tool}: already on PATH ({already})")
        return True

    asset = asset_template.format(version=version)
    bin_template = windows_bin if IS_WINDOWS else posix_bin
    bin_rel = bin_template.format(version=version)
    url = f"https://github.com/{repo}/releases/download/v{version}/{asset}"
    dest = TOOL_CACHE_DIR / tool
    dest.mkdir(parents=True, exist_ok=True)

    print(f"[install_tools] Downloading {tool} {version} ...")
    with tempfile.TemporaryDirectory(prefix="argus_release_") as tmp:
        archive = Path(tmp) / asset
        ok, error = _download(url, archive, timeout=900)
        if not ok:
            print(f"[install_tools] FAIL {tool}: download failed: {error}")
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
    if not IS_WINDOWS:
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


def install_go_install_tool(tool: str) -> bool | None:
    """Install a Go tool with ``go install`` when no release asset is pinned."""
    package = GO_INSTALL_MANIFEST.get(tool)
    if package is None:
        print(f"[install_tools] SKIP {tool}: no go-install manifest entry")
        return None

    already = _find_native_binary(tool)
    if already:
        print(f"[install_tools] OK {tool}: already installed ({already})")
        return True

    if shutil.which("go") is None:
        print(f"[install_tools] SKIP {tool}: needs a Go toolchain (go not on PATH)")
        return None

    print(f"[install_tools] go install {package} ...")
    result = subprocess.run(  # noqa: S603 — package path from the pinned manifest
        ["go", "install", package], capture_output=True, text=True, timeout=900
    )
    if result.returncode != 0:
        print(f"[install_tools] FAIL {tool}: go install exit {result.returncode}: {result.stderr[-300:]}")
        return False

    found = _find_native_binary(tool)
    if found:
        print(f"[install_tools] OK {tool}: {found}")
        return True
    print(f"[install_tools] FAIL {tool}: go install succeeded but {tool!r} is not on PATH")
    return False


def install_pip_tool(tool: str) -> bool | None:
    """Install a Python-distributed tool into this venv through pip.

    Only names in ``PIP_TOOL_MANIFEST`` are installable, and only from PyPI:
    several ``PIP_ALLOWLIST`` entries are Go binaries whose PyPI namesakes are
    unrelated packages, so pip-installing them would fetch the wrong tool.
    """
    package = PIP_TOOL_MANIFEST.get(tool)
    if package is None:
        if tool in PIP_ALLOWLIST:
            print(
                f"[install_tools] SKIP {tool}: not a PyPI package "
                "(installed from its own manifest instead)"
            )
        else:
            print(
                f"[install_tools] SKIP {tool}: not in the pip allowlist "
                f"(refusing to pip-install unvetted packages)"
            )
        return None

    already = _find_binary(tool)
    if already:
        print(f"[install_tools] OK {tool}: already installed ({already})")
        return True

    print(f"[install_tools] pip install {package} ...")
    result = subprocess.run(  # noqa: S603 — package name from the pinned allowlist
        [sys.executable, "-m", "pip", "install", package],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        print(f"[install_tools] FAIL {tool}: pip exit {result.returncode}: {result.stderr[-300:]}")
        return False

    found = _find_binary(tool)
    if found:
        print(f"[install_tools] OK {tool}: {found}")
        return True
    print(f"[install_tools] FAIL {tool}: pip succeeded but no {tool!r} executable was produced")
    return False


def install_tool_assets() -> bool | None:
    """Provision the pinned nuclei template set into ``tool_assets/``.

    nuclei ships no templates and exits with "no templates provided", so this
    is part of provisioning a working scanner. Detects any existing template
    tree (including a pre-populated checkout) and only clones when absent.
    """
    if NUCLEI_TEMPLATES_DIR.exists() and any(NUCLEI_TEMPLATES_DIR.rglob("*.yaml")):
        count = sum(1 for _ in NUCLEI_TEMPLATES_DIR.rglob("*.yaml"))
        print(f"[install_tools] OK nuclei-templates: already present ({count} templates)")
        return True

    if shutil.which("git") is None:
        print(
            "[install_tools] SKIP nuclei-templates: git is required to fetch "
            "the template set"
        )
        return None

    print("[install_tools] Cloning nuclei-templates ...")
    NUCLEI_TEMPLATES_DIR.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603 — pinned repo URL, list form
        ["git", "clone", "--depth", "1", NUCLEI_TEMPLATES_REPO, str(NUCLEI_TEMPLATES_DIR)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[install_tools] FAIL nuclei-templates: {result.stderr[-300:]}")
        return False

    if not any(NUCLEI_TEMPLATES_DIR.rglob("*.yaml")):
        print("[install_tools] FAIL nuclei-templates: clone produced no templates")
        return False
    count = sum(1 for _ in NUCLEI_TEMPLATES_DIR.rglob("*.yaml"))
    print(f"[install_tools] OK nuclei-templates: {count} templates in {NUCLEI_TEMPLATES_DIR}")
    return True


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
    local_bin = Path.home() / ".local" / "bin"
    missing: list[str] = []
    for tool in GO_TOOL_MANIFEST:
        # ``registry`` resolves through the augmented PATH, which still lists
        # the venv once a Go build is absent — and ``venv/bin/httpx`` is the
        # Python CLI, not the scanner. Only a real binary counts as present.
        resolved = registry.resolve(tool)
        if isinstance(resolved, str) and not _is_python_console_script(Path(resolved)):
            continue
        if get_cached_tool(tool) is not None:
            continue
        missing.append(tool)
    for tool, (_manager, _package, binary) in SYSTEM_TOOL_MANIFEST.items():
        # ``~/.local/bin/<tool>`` is where installs land when upstream ships a
        # differently named binary (testssl -> testssl.sh); it is not always
        # exported on PATH, so check the directory itself.
        if (
            registry.is_available(binary)
            or registry.is_available(tool)
            or _find_binary(binary)
            or _find_binary(tool)
            or (local_bin / tool).exists()
        ):
            continue
        missing.append(tool)
    for tool in GIT_TOOL_MANIFEST:
        if not registry.is_available(tool):
            missing.append(tool)
    for tool in RELEASE_TOOL_MANIFEST:
        if not registry.is_available(binary_for(tool)):
            missing.append(tool)
    for tool in PIP_TOOL_MANIFEST:
        if not (registry.is_available(tool) or get_cached_tool(tool) is not None):
            missing.append(tool)
    for tool in GO_INSTALL_MANIFEST:
        if not (registry.is_available(tool) or _find_native_binary(tool)):
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
        help="Specific tools to install (default: every manifest group plus assets)",
    )
    parser.add_argument(
        "--pip",
        action="store_true",
        help="Only pip-install the Python tools (semgrep, sqlmap, bandit, ...)",
    )
    parser.add_argument(
        "--go-only",
        action="store_true",
        help="Only install the pinned Go binaries (fast path for CI images)",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Skip the nuclei template set (large download)",
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
        help="Only install package-manager tools (trufflehog, phpcs, eslint)",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Only install git-only tools (commix, jwt_tool, sn1per, brakeman)",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Only install release-archive tools (dependency_check, spotbugs)",
    )
    args = parser.parse_args(argv)

    if args.check:
        try:
            missing = check_missing()
        except RuntimeError as e:
            print(f"[install_tools] ERROR: {e}")
            return 1
        if missing:
            required = [t for t in missing if t not in OPTIONAL_TOOLS]
            optional = [t for t in missing if t in OPTIONAL_TOOLS]
            if required:
                print(
                    f"[install_tools] MISSING {len(required)} tool(s): {', '.join(required)}"
                )
                print("[install_tools] Install with: python scripts/install_tools.py")
            if optional:
                print(
                    f"[install_tools] OPTIONAL missing (not required): "
                    f"{', '.join(optional)}"
                )
            for tool in missing:
                if tool in MANUAL_TOOLS and tool not in optional:
                    print(f"  - {tool}: {MANUAL_TOOLS[tool]}")
            if required:
                return 1
            print("[install_tools] All required tools available. ✔")
            return 0
        print("[install_tools] All tools available. ✔")
        return 0

    failures: list[str] = []
    unsupported: list[str] = []
    optional_failed: list[str] = []

    def record(tool: str, result: bool | None) -> None:
        if result is False:
            # A tool needing a runtime the host lacks (phpcs -> php) must not
            # fail provisioning for every other tool.
            if tool in OPTIONAL_TOOLS:
                optional_failed.append(tool)
            else:
                failures.append(tool)
        elif result is None:
            # ``None`` means "no install path was taken". Quiet only when this
            # OS has no build of the tool at all; a required scanner that was
            # skipped because the host lacks brew/gem/go is a failure, and
            # reporting success there is how a scan runs with no scanners.
            if tool in OPTIONAL_TOOLS:
                optional_failed.append(tool)
            elif _unsupported_on_this_platform(tool):
                unsupported.append(tool)
            else:
                failures.append(tool)

    targets = args.tools
    groups: set[str] = set()
    if targets:
        pass  # explicit tool names only
    elif args.go_only or args.system or args.git or args.release or args.pip:
        if args.go_only:
            groups.add("go")
        if args.system:
            groups.add("system")
        if args.git:
            groups.add("git")
        if args.release:
            groups.add("release")
        if args.pip:
            groups.add("pip")
    else:
        groups = {"go", "system", "git", "release", "pip", "assets"}

    for tool in targets or ():
        if tool in GO_TOOL_MANIFEST:
            record(
                tool,
                install_go_tool(
                    tool, verify_hash=not args.skip_verify, force=args.force
                ),
            )
        elif tool in SYSTEM_TOOL_MANIFEST:
            record(tool, install_system_tool(tool))
        elif tool in GIT_TOOL_MANIFEST:
            record(tool, install_git_tool(tool))
        elif tool in RELEASE_TOOL_MANIFEST:
            record(tool, install_release_tool(tool))
        elif tool in GO_INSTALL_MANIFEST:
            record(tool, install_go_install_tool(tool))
        elif tool in PIP_TOOL_MANIFEST:
            record(tool, install_pip_tool(tool))
        else:
            print(f"[install_tools] SKIP {tool}: no manifest entry")
            if tool in MANUAL_TOOLS:
                print(f"  {MANUAL_TOOLS[tool]}")

    if "go" in groups:
        for tool in GO_TOOL_MANIFEST:
            record(
                tool,
                install_go_tool(
                    tool, verify_hash=not args.skip_verify, force=args.force
                ),
            )
        for tool in GO_INSTALL_MANIFEST:
            record(tool, install_go_install_tool(tool))
    if "release" in groups:
        for tool in RELEASE_TOOL_MANIFEST:
            record(tool, install_release_tool(tool))
    if "git" in groups:
        for tool in GIT_TOOL_MANIFEST:
            record(tool, install_git_tool(tool))
    if "system" in groups:
        for tool in SYSTEM_TOOL_MANIFEST:
            record(tool, install_system_tool(tool))
    if "pip" in groups:
        for tool in sorted(PIP_TOOL_MANIFEST):
            record(tool, install_pip_tool(tool))

    assets_ok = True
    if "assets" in groups and not args.no_assets and not targets:
        assets_ok = install_tool_assets() is not False

    if unsupported:
        print(
            "[install_tools] Not installable on this platform: "
            f"{', '.join(sorted(unsupported))}"
        )
    if optional_failed:
        print(
            "[install_tools] Optional tool(s) unavailable on this host: "
            f"{', '.join(sorted(optional_failed))} — install manually if needed"
        )
    if failures or not assets_ok:
        if failures:
            print(
                f"[install_tools] Done with {len(failures)} failure(s): "
                f"{', '.join(sorted(failures))}"
            )
        if not assets_ok:
            print("[install_tools] FAIL nuclei templates were not provisioned")
        print("[install_tools] Re-run with --check for a per-tool report.")
        return 1
    print("[install_tools] All requested tools installed. ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
