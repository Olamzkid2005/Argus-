import json
import logging

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class DalfoxParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                vuln_type = obj.get("type", "")
                data = obj.get("data", {}) or {}
                finding = {
                    "type": "XSS",
                    "severity": "HIGH",
                    "endpoint": data.get("url", ""),
                    "evidence": {
                        "param": data.get("param", ""),
                        "payload": data.get("payload", ""),
                        "vuln_type": vuln_type,
                    },
                    "confidence": 0.85,
                    "tool": "dalfox",
                }
                findings.append(finding)
            except json.JSONDecodeError:
                logger.warning("Non-JSON line encountered in Dalfox output, skipping: %s", line[:200])
                continue
        return findings
