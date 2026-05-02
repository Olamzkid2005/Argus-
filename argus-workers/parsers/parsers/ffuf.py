import json

from parsers.parsers.base import BaseParser


class FfufParser(BaseParser):
    """Parser for ffuf output"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse ffuf JSON output

        Args:
            raw_output: Ffuf output (JSON format)

        Returns:
            List of findings
        """
        findings = []

        try:
            data = json.loads(raw_output)

            for result in data.get("results", []):
                finding = {
                    "type": "DIRECTORY_FOUND",
                    "severity": "INFO",
                    "endpoint": result.get("url", ""),
                    "evidence": {
                        "status_code": result.get("status"),
                        "length": result.get("length"),
                        "words": result.get("words"),
                        "lines": result.get("lines"),
                    },
                    "confidence": 0.7,
                    "tool": "ffuf",
                }
                findings.append(finding)

        except json.JSONDecodeError:
            # Ffuf output not in JSON format
            pass

        return findings
