"""Parser for trufflehog JSON output (trufflehog git --json)."""
import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class TrufflehogParser(BaseParser):
    """Parser for trufflehog secret scanner output."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            for line in raw_output.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue

                severity = "CRITICAL" if item.get("verified", False) else "HIGH"
                finding = {
                    "type": f"TRUFFLEHOG_{item.get('detector_name', 'UNKNOWN').upper().replace(' ', '_')}",
                    "severity": severity,
                    "endpoint": f"commit:{item.get('commit', '')}:{item.get('path', '')}",
                    "evidence": {
                        "commit": item.get("commit", ""),
                        "path": item.get("path", ""),
                        "detector": item.get("detector_name", ""),
                        "verified": item.get("verified", False),
                        "redacted": item.get("redacted", ""),
                    },
                    "confidence": 0.95 if item.get("verified", False) else 0.75,
                    "tool": "trufflehog",
                }
                findings.append(finding)
        except Exception as e:
            logger.warning("trufflehog parse error: %s", e)

        return findings
