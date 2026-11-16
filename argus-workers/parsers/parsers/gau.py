from parsers.parsers.base import BaseParser, structured_findings


class GauParser(BaseParser):
    """Parser for gau output (GetAllUrls)"""

    def parse(self, raw_output: str) -> list[dict]:
        structured = structured_findings(raw_output)
        if structured:
            return structured
        """
        Parse gau plain URL output

        Args:
            raw_output: Gau output (plain URLs)

        Returns:
            List of findings
        """
        findings = []

        for line in raw_output.splitlines():
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
