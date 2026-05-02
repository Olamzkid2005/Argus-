import csv
import io

from parsers.parsers.base import BaseParser


class NiktoParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        reader = csv.reader(io.StringIO(raw_output))
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            finding = {
                "type": "WEB_SERVER_VULNERABILITY",
                "severity": "MEDIUM",
                "endpoint": row[0] if len(row) > 0 else "",
                "evidence": {
                    "csv_row": row,
                },
                "confidence": 0.70,
                "tool": "nikto",
            }
            findings.append(finding)
        return findings
