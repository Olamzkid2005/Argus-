"""Parser for gospider web crawler output."""
import json
import logging
from urllib.parse import urlparse

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


def _is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(parsed.scheme) and bool(parsed.netloc)


class GospiderParser(BaseParser):
    """Parser for gospider web crawling output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        seen = set()
        for line in raw_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            url = None
            source = ""
            item_type = ""
            # Try JSON first
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    url = data.get("output") or data.get("url") or ""
                    source = data.get("source", "")
                    item_type = data.get("type", "")
            except (json.JSONDecodeError, ValueError):
                # Treat as plain URL if valid
                if _is_valid_url(line):
                    url = line

            if url and url not in seen:
                seen.add(url)
                evidence = {}
                if source:
                    evidence["source"] = source
                if item_type:
                    evidence["type"] = item_type
                finding = {
                    "type": "DISCOVERED_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": url,
                    "evidence": evidence if evidence else {"source": "crawler"},
                    "tool": "gospider",
                }
                findings.append(finding)
        return findings
