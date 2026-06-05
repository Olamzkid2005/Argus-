"""
Attack Surface Mapper — combines 8 tools into unified asset discovery.

Replaces independent runs of subfinder, amass, dnsx, httpx, naabu,
katana, gau, waybackurls with a single orchestrated tool.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

from .attack_surface.asset_graph import AssetGraph
from .attack_surface.port_discovery import PortDiscovery
from .attack_surface.subdomain_discovery import SubdomainDiscovery
from .attack_surface.url_discovery import URLDiscovery

logger = logging.getLogger(__name__)


class AttackSurfaceMapper(AbstractTool):
    """Maps the complete attack surface of a target using multiple tools."""

    tool_name: str = "attack_surface_mapper"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=ctx.target,
        )

        from urllib.parse import urlparse
        parsed = urlparse(ctx.target)
        domain = parsed.hostname or ctx.target

        tool_runner = getattr(ctx, "_tool_runner", None)

        subdomain_disc = SubdomainDiscovery(tool_runner)
        port_disc = PortDiscovery(tool_runner)
        url_disc = URLDiscovery(tool_runner)

        graph = AssetGraph()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(subdomain_disc.discover, domain, ctx.timeout): "subdomains",
                executor.submit(port_disc.discover, domain, ctx.timeout): "ports",
                executor.submit(url_disc.discover, ctx.target, ctx.timeout): "urls",
            }

            for future in as_completed(futures):
                task = futures[future]
                try:
                    data = future.result()
                    if task == "subdomains":
                        for sub in data:
                            graph.add_subdomain(sub)
                    elif task == "ports":
                        for port_info in data:
                            host = domain
                            graph.add_port(host, port_info)
                    elif task == "urls":
                        for url in data:
                            graph.add_url(url)
                            from urllib.parse import urlparse as _up
                            try:
                                path = _up(url).path
                                if "/api" in path.lower():
                                    graph.add_api_endpoint(url)
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning("Attack surface %s failed: %s", task, e)

        asset_dict = graph.to_dict()

        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        builder.info(
            "ATTACK_SURFACE",
            ctx.target,
            asset_dict,
        )

        for sub in list(graph.subdomains)[:20]:
            builder.info("SUBDOMAIN", sub, {"domain": sub})

        for host, ports in graph.ports.items():
            for port_info in ports:
                builder.info(
                    "OPEN_PORT",
                    host,
                    {"port": port_info.get("port"), "service": port_info.get("service", "")},
                )

        result.findings = builder.findings
        result.findings_count = len(builder.findings)

        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result
