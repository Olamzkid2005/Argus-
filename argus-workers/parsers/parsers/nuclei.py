import json
import logging
from parsers.parsers.base import BaseParser
from parsers.schemas.nuclei_schema import validate_nuclei_finding

logger = logging.getLogger(__name__)


class NucleiParser(BaseParser):
    """Parser for nuclei JSONL output with schema validation."""

    def parse(self, raw_output: str) -> list[dict]:
        findings = []
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                validated = validate_nuclei_finding(data)
                if validated:
                    findings.append(validated)
                else:
                    logger.debug(f"Skipping invalid nuclei finding: {data.get('template-id', 'unknown')}")
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON nuclei output line")
                continue
            except Exception as e:
                logger.warning(f"Error parsing nuclei line: {e}")
                continue
        return findings
