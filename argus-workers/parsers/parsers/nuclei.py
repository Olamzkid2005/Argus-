import json

from parsers.parsers.base import BaseParser


class NucleiParser(BaseParser):
    """Parser for nuclei JSON output"""

    def parse(self, raw_output: str) -> list[dict]:
        """
        Parse nuclei JSON lines output

        Args:
            raw_output: Nuclei output (JSON lines format)

        Returns:
            List of findings
        """
        findings = []

        for line in raw_output.split("\n"):
            if not line.strip():
                continue

            try:
                data = json.loads(line)

                # Extract finding information
                finding = {
                    "type": data.get("info", {}).get("name", "UNKNOWN"),
                    "severity": data.get("info", {}).get("severity", "INFO").upper(),
                    "endpoint": data.get("matched-at", ""),
                    "evidence": {
                        "template_id": data.get("template-id"),
                        "matcher_name": data.get("matcher-name"),
                        "extracted_results": data.get("extracted-results", []),
                        "curl_command": data.get("curl-command"),
                    },
                    "confidence": 0.8,  # Default confidence for nuclei
                    "tool": "nuclei",
                }

                findings.append(finding)

            except json.JSONDecodeError:
                # Skip lines that aren't valid JSON
                continue
            except Exception as e:
                # Log error but continue processing
                print(f"Error parsing nuclei line: {e}")
                continue

        return findings
