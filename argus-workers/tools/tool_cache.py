"""
Tool caching and optimization for workers.

Caches downloaded tools to avoid re-downloading.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

# Tool cache directory
TOOL_CACHE_DIR = Path(tempfile.gettempdir()) / "argus_tool_cache"
TOOL_CACHE_DIR.mkdir(exist_ok=True)

# Strict allowlist of tool names that can be installed via pip.
# Only known, vetted tool names are allowed to prevent supply-chain injection.
PIP_ALLOWLIST = frozenset(
    {
        "semgrep",
        "bandit",
        "gitleaks",
        "trufflehog",
        "trivy",
        "pip-audit",
        "sqlmap",
        "dalfox",
        "commix",
        "gospider",
        "arjun",
        "naabu",
        "httpx",
        "subfinder",
        "katana",
        "gau",
        "waybackurls",
        "whatweb",
        "wafw00f",
        "wpscan",
        "alterx",
        "nikto",
        "jwt_tool",
        "testssl",
    }
)

# Tool versions for security
TOOL_VERSIONS = {
    "nuclei": "3.2.0",
    # SHA256 checksums for supply-chain integrity verification.
    # Retrieved from official GitHub release assets on 2026-07-17.
    # Linux amd64 binaries; other archs would need their own entries.
    # Sources:
    #   nuclei: https://github.com/projectdiscovery/nuclei/releases/tag/v3.2.0
    #   httpx:  https://github.com/projectdiscovery/httpx/releases/tag/v1.6.0
    #   katana: https://github.com/projectdiscovery/katana/releases/tag/v1.1.0
    #   subfinder: https://github.com/projectdiscovery/subfinder/releases/tag/v2.6.6
    #   ffuf:   https://github.com/ffuf/ffuf/releases/tag/v2.1.0
    #   dalfox: https://github.com/hahwul/dalfox/releases/tag/v2.10.0
    #   sqlmap: pip-only (Python tool), no binary release hashes
    #   semgrep: pip/npm-only, no binary release hashes
    "nuclei_sha256": "8351b05772f37268fd172476de3f0c831ca9d9b9b1a6c64bacd38ef055e5d052",
    "httpx": "1.6.0",
    "httpx_sha256": "a209fbf6eb95cdfb3be9a90a1a57463c6dd1879a56ca32bb4a39cc55d9b0754d",
    "katana": "1.1.0",
    "katana_sha256": "a3af74515c79b0a3e877eab280987b7247161978c49fcad428f00f9452c5bd56",
    "subfinder": "2.6.6",
    "subfinder_sha256": "6fda32fe1f5750e63fa07c112b1b615d033e425c6dc6659ed8ec61035eb8eba2",
    "ffuf": "2.1.0",
    "ffuf_sha256": "fc2c82736c14dcbea4daf3d3cf3878c1c4773008ba45c2bc0fceba7d17b40bb5",
    "sqlmap": "1.8",
    # sqlmap is a Python tool installed via pip — no binary release hashes available
    "sqlmap_sha256": "",
    "dalfox": "2.10.0",
    "dalfox_sha256": "dc11d28cdd6479fe7659084d5cdbda965b8b134c2a530fd5c056733a22954e76",
    "semgrep": "1.59.0",
    # semgrep is installed via pip/npm — no binary release hashes available
    "semgrep_sha256": "",
}


class ToolCache:
    """Manages tool caching and version management."""

    def __init__(self):
        self.tools_dir = TOOL_CACHE_DIR
        self._ensure_tools_directory()

    def _ensure_tools_directory(self):
        """Ensure tool directories exist."""
        for tool_name in TOOL_VERSIONS:
            # Skip _sha256 keys (used for supply-chain integrity, not tool directories)
            if tool_name.endswith("_sha256"):
                continue
            tool_path = self.tools_dir / tool_name
            tool_path.mkdir(exist_ok=True)

    def is_cached(self, tool_name: str) -> bool:
        """Check if tool is cached."""
        tool_binary = self.tools_dir / tool_name / tool_name
        return tool_binary.exists()

    def get_tool_path(self, tool_name: str) -> Path | None:
        """Get path to cached tool."""
        if not self.is_cached(tool_name):
            return None
        return self.tools_dir / tool_name / tool_name

    def _validate_tool_name(self, tool_name: str) -> str:
        """Validate tool name to prevent command injection."""
        if not tool_name or not tool_name.strip():
            raise ValueError(f"Invalid tool name: {tool_name!r}")
        if "/" in tool_name or "\\" in tool_name or ".." in tool_name:
            raise ValueError(f"Tool name blocked (path traversal): {tool_name!r}")
        return tool_name.strip()

    def _validate_download_url(self, url: str) -> str:
        """Validate download URL to prevent injection."""
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError(
                f"Invalid download URL (must start with http:// or https://): {url!r}"
            )
        return url

    def cache_tool(self, tool_name: str, download_url: str | None = None) -> bool:
        """Download and cache a tool."""
        slog = ScanLogger("tool_cache")
        self._validate_tool_name(tool_name)

        if self.is_cached(tool_name):
            slog.info("Tool %s already cached", tool_name)
            logger.info("Tool %s already cached", tool_name)
            return True

        slog.tool_start("cache_tool", tool=tool_name)

        # Only allow known tools to be installed via pip (supply-chain safety)
        if tool_name in PIP_ALLOWLIST:
            try:
                version = TOOL_VERSIONS.get(tool_name)
                pip_cmd = ["pip", "install"]
                hashes_env = os.getenv("PIP_REQUIRE_HASHES", "")
                if hashes_env:
                    pip_cmd.extend(["--require-hashes", f"--hash={hashes_env}"])
                if version:
                    pip_cmd.append(f"{tool_name}=={version}")
                else:
                    pip_cmd.append(tool_name)
                result = subprocess.run(  # noqa: S603 — safe: pip_cmd built from allowlisted tool names
                    pip_cmd, capture_output=True, text=True, timeout=300
                )
                if result.returncode == 0:
                    slog.info(
                        f"Installed {tool_name} via pip (version={version or 'latest'})"
                    )
                    logger.info(
                        "Installed %s via pip (version=%s, hashes=%s)",
                        tool_name,
                        version or "latest",
                        "enabled" if hashes_env else "disabled",
                    )
                    # Verify installation succeeded by checking --version
                    verify = subprocess.run(  # noqa: S603 — safe: tool_name is from allowlist
                        [tool_name, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    slog.info("%s version: %s", tool_name, verify.stdout.strip())
                    logger.info(
                        "Installed %s version: %s", tool_name, verify.stdout.strip()
                    )
                    return True
                else:
                    slog.warn(
                        "pip install %s failed: %s", tool_name, result.stderr[:200]
                    )
                    logger.error(
                        "pip install %s failed: %s", tool_name, result.stderr[:500]
                    )
            except Exception as e:
                slog.warn("Failed to install %s via pip: %s", tool_name, e)
                logger.warning("Failed to install %s via pip: %s", tool_name, e)
        else:
            slog.info("%s not in pip allowlist, trying download", tool_name)
            logger.warning(
                "Tool %r is not in pip allowlist, skipping pip install", tool_name
            )

        # Otherwise download
        if download_url:
            try:
                self._validate_download_url(download_url)
                temp_dir = tempfile.mkdtemp()
                dl_path = f"{temp_dir}/{tool_name}"
                result = subprocess.run(  # noqa: S603 — safe: list form, URL is validated by _validate_download_url()
                    ["curl", "-L", "-o", dl_path, download_url],  # noqa: S607
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    # H-v3-16: Verify downloaded file integrity
                    dl_path_obj = Path(dl_path)
                    if not dl_path_obj.exists() or dl_path_obj.stat().st_size < 1024:
                        slog.warn(
                            f"Downloaded {tool_name} is too small or missing — possible corrupt download"
                        )
                        logger.warning(
                            "Downloaded %s from %s is too small (%d bytes) — rejecting",
                            tool_name,
                            download_url,
                            dl_path_obj.stat().st_size if dl_path_obj.exists() else 0,
                        )
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        return False

                    # Verify SHA256 checksum if a known hash is recorded
                    expected_hash = TOOL_VERSIONS.get(tool_name + "_sha256")
                    if expected_hash:
                        actual_hash = hashlib.sha256()
                        with open(dl_path, "rb") as f:
                            for chunk in iter(lambda: f.read(65536), b""):
                                actual_hash.update(chunk)
                        if actual_hash.hexdigest() != expected_hash:
                            slog.warn(
                                f"SHA256 mismatch for {tool_name} — expected {expected_hash}, got {actual_hash.hexdigest()}"
                            )
                            logger.error(
                                "SHA256 mismatch for %s downloaded from %s",
                                tool_name,
                                download_url,
                            )
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            return False
                        slog.info("SHA256 verification passed for %s", tool_name)

                    tool_path = self.tools_dir / tool_name / tool_name
                    shutil.move(dl_path, tool_path)
                    os.chmod(tool_path, 0o755)
                    slog.info("Cached %s from %s", tool_name, download_url)
                    logger.info("Cached %s from %s", tool_name, download_url)
                    return True
            except Exception as e:
                slog.warn("Failed to download %s: %s", tool_name, e)
                logger.error("Failed to download %s: %s", tool_name, e)

        return False

    def cleanup_old_versions(self, tool_name: str, keep_versions: int = 2):
        """Clean up old tool versions."""
        tool_dir = self.tools_dir / tool_name
        if not tool_dir.exists():
            return

        # Get versions by modification time
        versions = sorted(
            tool_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
        )

        # Remove old versions
        for old_version in versions[keep_versions:]:
            if old_version.is_file():
                old_version.unlink()
                logger.info("Removed old version: %s", old_version)

    def verify_tool(self, tool_name: str) -> bool:
        """Verify tool is working."""
        tool_path = self.get_tool_path(tool_name)
        if not tool_path:
            return False

        try:
            result = subprocess.run(  # noqa: S603 — safe: tool_path is from local cache directory
                [str(tool_path), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_tool_hash(self, tool_name: str) -> str | None:
        """Get SHA256 hash of cached tool."""
        tool_path = self.get_tool_path(tool_name)
        if not tool_path:
            return None

        sha256 = hashlib.sha256()
        with open(tool_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


# Global tool cache instance
tool_cache = ToolCache()


def get_cached_tool(tool_name: str) -> Path | None:
    """Get cached tool path."""
    cached = tool_cache.get_tool_path(tool_name)
    if cached:
        return cached

    # Try to cache if not available
    if tool_cache.is_cached(tool_name):
        return tool_cache.get_tool_path(tool_name)

    return None
