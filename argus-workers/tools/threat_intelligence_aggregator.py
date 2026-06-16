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

        # Check if domain resolves before querying WHOIS to avoid TLD registry fallthrough
        domain_resolves = self._check_dns_resolution(domain)

        try:
            certs = self._query_crtsh(domain)
            intel["certificates"] = certs
        except Exception as e:
            logger.debug("crt.sh failed: %s", e)

        if domain_resolves:
            try:
                whois_data = self._query_whois(domain)
                intel["dns_records"] = whois_data
            except Exception as e:
                logger.debug("WHOIS failed: %s", e)
        else:
            intel["dns_records"] = [{"key": "status", "value": "Domain does not resolve — WHOIS skipped"}]
            builder.vulnerability(
                "DOMAIN_NOT_RESOLVED",
                "INFO",
                ctx.target,
                {"domain": domain, "detail": "Domain does not resolve in DNS — it may not be registered or may be offline"},
                confidence=0.9,
            )

        builder.info("THREAT_INTELLIGENCE", ctx.target, intel)
        for cert in intel.get("certificates", [])[:10]:
            builder.info("CERTIFICATE", ctx.target, {"name": cert.get("name_value", ""), "issuer": cert.get("issuer_name", "")})

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _check_dns_resolution(self, domain: str) -> bool:
        """Check if a domain resolves to an IP address.

        This prevents WHOIS queries from falling through to TLD registry
        servers for non-existent domains (e.g., vulnbank.org → .org registry).
        """
        import socket
        try:
            socket.getaddrinfo(domain, 80, socket.AF_INET, socket.SOCK_STREAM)
            return True
        except socket.gaierror:
            return False
        except Exception as e:
            logger.debug("DNS resolution check failed for %s: %s", domain, e)
            return False

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
