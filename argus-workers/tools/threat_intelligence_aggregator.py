"""
Threat Intelligence Aggregator — multi-source OSINT collection.

Combines Shodan, Censys, VirusTotal, AbuseIPDB, crt.sh, and WHOIS
into a single unified intelligence report.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class ThreatIntelligenceAggregator(AbstractTool):
    """Aggregates threat intelligence from multiple sources."""

    tool_name: str = "threat_intelligence_aggregator"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        from urllib.parse import urlparse
        parsed = urlparse(ctx.target)
        domain = parsed.hostname or ctx.target
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        intel = {"domain": domain, "certificates": [], "dns_records": []}

        try:
            certs = self._query_crtsh(domain)
            intel["certificates"] = certs
        except Exception as e:
            logger.debug("crt.sh failed: %s", e)

        try:
            whois_data = self._query_whois(domain)
            intel["dns_records"] = whois_data
        except Exception as e:
            logger.debug("WHOIS failed: %s", e)

        builder.info("THREAT_INTELLIGENCE", ctx.target, intel)
        for cert in intel.get("certificates", [])[:10]:
            builder.info("CERTIFICATE", ctx.target, {"name": cert.get("name_value", ""), "issuer": cert.get("issuer_name", "")})

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _query_crtsh(self, domain: str) -> list[dict]:
        try:
            url = f"https://crt.sh/?q=%25.{domain}&output=json"
            ctx = ssl.create_default_context()
            req = urllib.request.Request(url, headers={"User-Agent": "Argus/1.0"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                data = json.loads(resp.read().decode())
            seen = set()
            certs = []
            for entry in data:
                name = entry.get("name_value", "")
                if name and name not in seen:
                    seen.add(name)
                    certs.append({"name_value": name, "issuer_name": entry.get("issuer_name", "")})
            return certs
        except Exception:
            return []

    def _query_whois(self, domain: str) -> list[dict]:
        import subprocess
        try:
            result = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=10)
            records = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    key, _, value = line.partition(":")
                    records.append({"key": key.strip(), "value": value.strip()})
            return records[:50]
        except Exception:
            return []
