from parsers.parsers.base import BaseParser


class SqlmapParser(BaseParser):
    """Parser for sqlmap output"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse sqlmap output

        Args:
            raw_output: Sqlmap output

        Returns:
            List of SQL injection findings
        """
        findings = []

        # Look for SQL injection indicators in output
        if "sqlmap identified the following injection point" in raw_output.lower():
            finding = {
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "",  # Will be filled by normalizer
                "evidence": {
                    "raw_output": raw_output[:1000],  # First 1000 chars
                },
                "confidence": 0.9,  # High confidence for sqlmap
                "tool": "sqlmap",
            }
            findings.append(finding)

        return findings
