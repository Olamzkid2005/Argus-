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

logger = logging.getLogger(__name__)

# Tool cache directory
TOOL_CACHE_DIR = Path("/tmp/argus_tool_cache")
TOOL_CACHE_DIR.mkdir(exist_ok=True)

# Tool versions for security
TOOL_VERSIONS = {
    "nuclei": "3.2.0",
    "httpx": "1.6.0",
    "katana": "1.1.0",
    "subfinder": "2.6.6",
    "ffuf": "2.1.0",
    "sqlmap": "1.8",
    "dalfox": "2.10.0",
    "semgrep": "1.59.0",
}


class ToolCache:
    """Manages tool caching and version management."""

    def __init__(self):
        self.tools_dir = TOOL_CACHE_DIR
        self._ensure_tools_directory()

    def _ensure_tools_directory(self):
        """Ensure tool directories exist."""
        for tool_name in TOOL_VERSIONS:
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
            raise ValueError(f"Invalid download URL (must start with http:// or https://): {url!r}")
        return url

    def cache_tool(self, tool_name: str, download_url: str | None = None) -> bool:
        """Download and cache a tool."""
        self._validate_tool_name(tool_name)

        if self.is_cached(tool_name):
            logger.info(f"Tool {tool_name} already cached")
            return True

        # Try to install via package manager first
        try:
            result = subprocess.run(
                ["pip", "install", tool_name],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                logger.info(f"Installed {tool_name} via pip")
                return True
        except Exception as e:
            logger.warning(f"Failed to install {tool_name} via pip: {e}")

        # Otherwise download
        if download_url:
            try:
                self._validate_download_url(download_url)
                temp_dir = tempfile.mkdtemp()
                result = subprocess.run(
                    ["curl", "-L", "-o", f"{temp_dir}/{tool_name}", download_url],
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    tool_path = self.tools_dir / tool_name / tool_name
                    shutil.move(f"{temp_dir}/{tool_name}", tool_path)
                    os.chmod(tool_path, 0o755)
                    logger.info(f"Cached {tool_name} from {download_url}")
                    return True
            except Exception as e:
                logger.error(f"Failed to download {tool_name}: {e}")

        return False

    def cleanup_old_versions(self, tool_name: str, keep_versions: int = 2):
        """Clean up old tool versions."""
        tool_dir = self.tools_dir / tool_name
        if not tool_dir.exists():
            return

        # Get versions by modification time
        versions = sorted(
            tool_dir.iterdir(),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )

        # Remove old versions
        for old_version in versions[keep_versions:]:
            if old_version.is_file():
                old_version.unlink()
                logger.info(f"Removed old version: {old_version}")

    def verify_tool(self, tool_name: str) -> bool:
        """Verify tool is working."""
        tool_path = self.get_tool_path(tool_name)
        if not tool_path:
            return False

        try:
            result = subprocess.run(
                [str(tool_path), "--version"],
                capture_output=True,
                text=True,
                timeout=10
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
