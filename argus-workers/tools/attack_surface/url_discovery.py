"""URL discovery using katana, gau, and waybackurls."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class URLDiscovery:
    """Discover URLs using multiple sources."""

    def __init__(self, tool_runner=None):
        self._tool_runner = tool_runner

    def discover(self, target: str, timeout: int = 300) -> list[str]:
        """Discover URLs from multiple sources.

        Returns sorted list of unique URLs.
        """
        urls: set[str] = set()

        if self._tool_runner:
            urls.update(self._run_katana(target, timeout))
            urls.update(self._run_gau(target, timeout))
            urls.update(self._run_waybackurls(target, timeout))

        return sorted(urls)

    def _run_katana(self, target: str, timeout: int) -> list[str]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "katana", ["-u", target, "-jsonl", "-silent", "-d", "3"],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            urls = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    url = data.get("url", "")
                    if url:
                        urls.append(url)
                except json.JSONDecodeError:
                    if line.startswith("http"):
                        urls.append(line.strip())
            return urls
        except Exception as e:
            logger.debug("katana failed: %s", e)
            return []

    def _run_gau(self, target: str, timeout: int) -> list[str]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "gau", ["--json", target],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            urls = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    url = data.get("url", "")
                    if url:
                        urls.append(url)
                except json.JSONDecodeError:
                    pass
            return urls
        except Exception as e:
            logger.debug("gau failed: %s", e)
            return []

    def _run_waybackurls(self, target: str, timeout: int) -> list[str]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "waybackurls", [target],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            return [line.strip() for line in result.stdout.strip().splitlines() if line.strip().startswith("http")]
        except Exception as e:
            logger.debug("waybackurls failed: %s", e)
            return []
