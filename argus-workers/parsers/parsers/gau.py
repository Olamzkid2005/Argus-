from parsers.parsers.base import BaseParser


class GauParser(BaseParser):
    """Parser for gau output (GetAllUrls)"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse gau plain URL output

        Args:
            raw_output: Gau output (plain URLs)

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
                    "type": "KNOWN_URL",
                    "severity": "INFO",
                    "endpoint": url,
                    "evidence": {
                        "source": "gau",
                    },
                    "confidence": 0.75,
                    "tool": "gau",
                }
                findings.append(finding)

        return findings
