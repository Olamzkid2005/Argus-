"""Parser for gospider web crawler JSON output."""
import json
import logging
from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class GospiderParser(BaseParser):
    """Parser for gospider web crawling output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        items = data if isinstance(data, list) else [data]
        seen = set()
        for item in items:
            url = item.get("url", "") or item.get("output", "")
            if not url or url in seen:
                continue
            seen.add(url)
            finding = {
                "type": "ENDPOINT_DISCOVERY",
                "severity": "INFO",
                "endpoint": url,
                "evidence": {
                    "source": item.get("source", ""),
                    "status": item.get("status", 0),
                },
                "source_tool": "gospider",
            }
            findings.append(finding)
        return findings
