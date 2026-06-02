from parsers.parsers.base import BaseParser


class WaybackurlsParser(BaseParser):
    """Parser for waybackurls output"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse waybackurls plain URL output

        Args:
            raw_output: Waybackurls output (plain URLs)

        Returns:
            List of findings
        """
        findings = []

        for line in raw_output.split("\n"):
            if not line.strip():
                continue

            url = line.strip()
            if url.startswith("http://") or url.startswith("https://"):
                finding = {
                    "type": "HISTORICAL_URL",
                    "severity": "INFO",
                    "endpoint": url,
                    "evidence": {
                        "source": "wayback",
                    },
                    "confidence": 0.70,
                    "tool": "waybackurls",
                }
                findings.append(finding)

        return findings
