import json

from parsers.parsers.base import BaseParser


class HttpxParser(BaseParser):
    """Parser for httpx output"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse httpx output

        Args:
            raw_output: Httpx output (URL list or JSON)

        Returns:
            List of findings (endpoints)
        """
        findings = []

        for line in raw_output.split("\n"):
            if not line.strip():
                continue

            try:
                # Try parsing as JSON first
                data = json.loads(line)

                finding = {
                    "type": "HTTP_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": data.get("url", ""),
                    "evidence": {
                        "status_code": data.get("status_code"),
                        "content_length": data.get("content_length"),
                        "content_type": data.get("content_type"),
                        "title": data.get("title"),
                    },
                    "confidence": 1.0,  # High confidence for discovered endpoints
                    "tool": "httpx",
                }

                findings.append(finding)

            except json.JSONDecodeError:
                # Not JSON, treat as plain URL
                if line.startswith("http://") or line.startswith("https://"):
                    finding = {
                        "type": "HTTP_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": line.strip(),
                        "evidence": {},
                        "confidence": 1.0,
                        "tool": "httpx",
                    }
                    findings.append(finding)

        return findings
