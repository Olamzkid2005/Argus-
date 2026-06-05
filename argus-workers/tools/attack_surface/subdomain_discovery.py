"""Subdomain discovery combining multiple tools."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


class SubdomainDiscovery:
    """Discover subdomains using multiple techniques."""

    def __init__(self, tool_runner=None):
        self._tool_runner = tool_runner

    def discover(self, domain: str, timeout: int = 300) -> list[str]:
        """Discover subdomains using available tools.

        Returns list of unique subdomains.
        """
        subdomains: set[str] = set()

        if self._tool_runner:
            subdomains.update(self._run_subfinder(domain, timeout))
            subdomains.update(self._run_amass(domain, timeout))

        subdomains.add(domain)
        return sorted(subdomains)

    def _run_subfinder(self, domain: str, timeout: int) -> list[str]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "subfinder", ["-d", domain, "-silent", "-json"],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            subs = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    subs.append(data.get("host", line.strip()))
                except json.JSONDecodeError:
                    subs.append(line.strip())
            return subs
        except Exception as e:
            logger.debug("subfinder failed: %s", e)
            return []

    def _run_amass(self, domain: str, timeout: int) -> list[str]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "amass", ["enum", "-d", domain, "-json", "-timeout", str(timeout // 2)],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            subs = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    name = data.get("name", "")
                    if name:
                        subs.append(name)
                except json.JSONDecodeError:
                    pass
            return subs
        except Exception as e:
            logger.debug("amass failed: %s", e)
            return []
