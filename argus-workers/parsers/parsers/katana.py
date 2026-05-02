import json

from parsers.parsers.base import BaseParser, _safe_get


class KatanaParser(BaseParser):
    """Parser for katana output (web crawler)"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse katana JSON lines output

        Args:
            raw_output: Katana output (JSON lines format)

        Returns:
            List of findings
        """
        findings = []

        for line in raw_output.split("\n"):
            if not line.strip():
                continue

            try:
                data = json.loads(line)
                request = _safe_get(data, "request", default={})

                finding = {
                    "type": "CRAWLED_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": request.get("url", request.get("endpoint", "")),
                    "evidence": {
                        "method": request.get("method", "GET"),
                        "body": request.get("body"),
                        "header": request.get("header"),
                    },
                    "confidence": 0.85,
                    "tool": "katana",
                }
                findings.append(finding)

            except json.JSONDecodeError:
                # Try plain URL fallback
                if line.strip().startswith("http"):
                    findings.append(
                        {
                            "type": "CRAWLED_ENDPOINT",
                            "severity": "INFO",
                            "endpoint": line.strip(),
                            "evidence": {},
                            "confidence": 0.85,
                            "tool": "katana",
                        }
                    )
                continue

        return findings
