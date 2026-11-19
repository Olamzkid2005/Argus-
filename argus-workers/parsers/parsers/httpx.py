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

        for line in raw_output.splitlines():
            if not line.strip():
                continue

            try:
                # Try parsing as JSON first
                data = json.loads(line)

                tech = data.get("tech") or data.get("technologies") or []
                if isinstance(tech, str):
                    tech = [t.strip() for t in tech.split(",") if t.strip()]

                finding = {
                    "type": "HTTP_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": data.get("url", ""),
                    "evidence": {
                        "status_code": data.get("status_code"),
                        "content_length": data.get("content_length"),
                        "content_type": data.get("content_type"),
                        "title": data.get("title"),
                        "webserver": data.get("webserver"),
                        "host": data.get("host"),
                        "tech": list(tech),
                    },
                    "confidence": 1.0,  # High confidence for discovered endpoints
                    "tool": "httpx",
                }

                findings.append(finding)

                # The technology/webserver fingerprint is the part later phases
                # plan against (which exploits apply to Flask/PHP/Werkzeug vs a
                # static host). It used to be dropped here, so httpx output only
                # ever reached the report as a bare "Endpoint: /".
                fingerprint = list(tech)
                if data.get("webserver"):
                    fingerprint.append(str(data["webserver"]))
                if fingerprint:
                    findings.append(
                        {
                            "type": "TECH_DETECTED",
                            "severity": "INFO",
                            "endpoint": data.get("url", ""),
                            "description": ", ".join(fingerprint),
                            "evidence": {
                                "technologies": list(tech),
                                "webserver": data.get("webserver"),
                                "title": data.get("title"),
                                "host": data.get("host"),
                            },
                            "confidence": 1.0,
                            "tool": "httpx",
                        }
                    )

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
