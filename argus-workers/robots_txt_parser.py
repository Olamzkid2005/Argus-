"""
Robots.txt parser for Argus Pentest Platform.

Fetches and parses robots.txt files to respect Crawl-delay directives.
"""

import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class RobotsTxtParser:
    """
    Parser for robots.txt files with caching.

    Fetches robots.txt from target domains and extracts Crawl-delay directive.
    Caches responses per domain to avoid repeated fetches.
    """

    def __init__(self, cache_ttl_seconds: int = 3600):
        """
        Initialize robots.txt parser.

        Args:
            cache_ttl_seconds: Time to live for cached robots.txt (default: 1 hour)
        """
        self.cache: dict[str, dict] = {}
        self.cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self.default_crawl_delay = 2.0  # Default 2 seconds if not specified

    async def get_crawl_delay(self, target_url: str) -> float:
        """
        Get crawl delay for target domain from robots.txt.

        Args:
            target_url: Target URL

        Returns:
            Crawl delay in seconds (default 2.0 if not specified or fetch fails)
        """
        # Extract domain from URL
        parsed = urlparse(target_url)
        domain = parsed.netloc or parsed.path

        # Check cache
        if domain in self.cache:
            cached = self.cache[domain]
            if datetime.now() - cached["timestamp"] < self.cache_ttl:
                logger.debug(
                    f"Using cached robots.txt for {domain}: "
                    f"{cached['crawl_delay']}s"
                )
                return cached["crawl_delay"]

        # Fetch robots.txt
        crawl_delay = await self._fetch_robots_txt(domain, parsed.scheme or "https")

        # Cache result
        self.cache[domain] = {
            "crawl_delay": crawl_delay,
            "timestamp": datetime.now()
        }

        return crawl_delay

    async def _fetch_robots_txt(self, domain: str, scheme: str) -> float:
        """
        Fetch and parse robots.txt from domain.

        Args:
            domain: Target domain
            scheme: URL scheme (http or https)

        Returns:
            Crawl delay in seconds
        """
        robots_url = f"{scheme}://{domain}/robots.txt"

        try:
            async with aiohttp.ClientSession() as session, session.get(
                robots_url,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"Failed to fetch robots.txt from {domain}: "
                        f"status {response.status}"
                    )
                    return self.default_crawl_delay

                content = await response.text()
                crawl_delay = self._parse_crawl_delay(content)

                logger.info(
                    f"Fetched robots.txt from {domain}: "
                    f"crawl delay {crawl_delay}s"
                )

                return crawl_delay

        except aiohttp.ClientError as e:
            logger.warning(
                f"Failed to fetch robots.txt from {domain}: {e}"
            )
            return self.default_crawl_delay

        except Exception as e:
            logger.error(
                f"Unexpected error fetching robots.txt from {domain}: {e}"
            )
            return self.default_crawl_delay

    def _parse_crawl_delay(self, content: str) -> float:
        """
        Parse Crawl-delay directive from robots.txt content.

        Args:
            content: robots.txt file content

        Returns:
            Crawl delay in seconds
        """
        # Look for Crawl-delay directive
        # Format: "Crawl-delay: <seconds>"
        for line in content.split("\n"):
            line = line.strip().lower()

            if line.startswith("crawl-delay:"):
                try:
                    # Extract delay value
                    delay_str = line.split(":", 1)[1].strip()
                    delay = float(delay_str)

                    # Validate delay is reasonable (0.1s to 60s)
                    if 0.1 <= delay <= 60.0:
                        return delay
                    else:
                        logger.warning(
                            f"Invalid crawl delay {delay}s, "
                            f"using default {self.default_crawl_delay}s"
                        )
                        return self.default_crawl_delay

                except (ValueError, IndexError) as e:
                    logger.warning(
                        f"Failed to parse crawl delay from '{line}': {e}"
                    )
                    continue

        # No Crawl-delay directive found
        logger.debug(
            f"No Crawl-delay directive found, "
            f"using default {self.default_crawl_delay}s"
        )
        return self.default_crawl_delay

    def clear_cache(self, domain: str | None = None) -> None:
        """
        Clear robots.txt cache.

        Args:
            domain: Specific domain to clear, or None to clear all
        """
        if domain:
            if domain in self.cache:
                del self.cache[domain]
                logger.info(f"Cleared robots.txt cache for {domain}")
        else:
            self.cache.clear()
            logger.info("Cleared all robots.txt cache")
