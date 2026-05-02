import json

from parsers.parsers.base import BaseParser


class NiktoParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        try:
            items = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings
        if not isinstance(items, list):
            return findings
        for item in items:
            msg = item.get("msg", "")
            osvdb = item.get("OSVDB", "")
            url = item.get("url", "")
            severity = "MEDIUM"
            if any(kw in msg.lower() for kw in ["critical", "high"]):
                severity = "HIGH"
            elif any(kw in msg.lower() for kw in ["info", "note"]):
                severity = "INFO"
            finding = {
                "type": "WEB_SERVER_VULNERABILITY",
                "severity": severity,
                "endpoint": url,
                "evidence": {
                    "message": msg,
                    "osvdb": osvdb,
                    "nikto_item": item,
                },
                "confidence": 0.70,
                "tool": "nikto",
            }
            findings.append(finding)
        return findings
