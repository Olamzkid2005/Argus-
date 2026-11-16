import json
from typing import Any

from parsers.parsers.base import BaseParser


class ArjunParser(BaseParser):
    def parse(self, raw_output: str) -> list[dict]:
        findings: list[dict[str, Any]] = []
        try:
            data = json.loads(raw_output)
        except json.JSONDecodeError:
            return findings

        # Our parameter-discovery shim reports already-structured findings
        # (so a clean negative can say so explicitly, with attribution); arjun's
        # own -oJ output is the {endpoint: [params]} mapping handled below.
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and (item.get("title") or item.get("description")):
                    findings.append(item)
            return findings

        if isinstance(data, dict) and not data.get("findings"):
            for endpoint, params in data.items():
                if isinstance(params, list):
                    finding = {
                        "type": "PARAMETER_DISCOVERY",
                        "severity": "INFO",
                        "endpoint": endpoint,
                        "evidence": {
                            "parameters": params,
                        },
                        "confidence": 0.75,
                        "tool": "arjun",
                    }
                    findings.append(finding)
                elif isinstance(params, dict):
                    param_list = list(params.keys())
                    finding = {
                        "type": "PARAMETER_DISCOVERY",
                        "severity": "INFO",
                        "endpoint": endpoint,
                        "evidence": {
                            "parameters": param_list,
                        },
                        "confidence": 0.75,
                        "tool": "arjun",
                    }
                    findings.append(finding)
        return findings
