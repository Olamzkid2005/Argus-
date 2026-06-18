"""
Port Scanner — PortScanner(AbstractTool) using naabu + nmap via ToolRunner.

Gated behind ARGUS_FF_PORT_SCANNER feature flag.
Runs during recon phase after subdomain discovery.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from feature_flags import is_enabled
from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult
from tools.tool_runner import ToolRunner
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

SERVICE_TEMPLATE_MAP: dict[str, list[str]] = {
    "http": ["nuclei", "nikto"],
    "https": ["nuclei", "nikto"],
    "http-proxy": ["nuclei", "nikto"],
    "ssh": ["nuclei-ssh"],
    "mysql": ["nuclei-database"],
    "mssql": ["nuclei-database"],
    "postgresql": ["nuclei-database"],
    "redis": ["nuclei-database"],
    "mongodb": ["nuclei-database"],
    "cassandra": ["nuclei-database"],
    "elasticsearch": ["nuclei-database"],
    "memcached": ["nuclei-database"],
}


@dataclass
class OpenPort:
    """Internal port representation used by parsing helpers."""

    port: int
    protocol: str
    service: str = ""
    version: str = ""
    state: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "protocol": self.protocol,
            "service": self.service,
            "version": self.version,
            "state": self.state,
        }


class PortScanner(AbstractTool):
    """
    Comprehensive port scanner — naabu (SYN scan) + nmap (service detection).

    Implements ``AbstractTool`` so it integrates with the standard tool lifecycle:
    timing, error handling, finding emission, and return as ``UnifiedToolResult``.

    Feature-gated by ``ARGUS_FF_PORT_SCANNER``.

    Calling convention::

        scanner = PortScanner()
        result = await scanner.run(ToolContext(target="example.com"))
        # result.ports  → list of port dicts
        # result.open_ports_count → len(result.ports)
    """

    tool_name: str = "port_scanner"

    NAABU_TIMEOUT = 600
    NMAP_TIMEOUT = 900
    DEFAULT_PORTS = "1-10000"

    def __init__(self) -> None:
        # ToolRunner handles locked environment, dangerous command detection,
        # circuit breaker, and output size limits.
        self._tool_runner = ToolRunner()

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        """
        Run port scan with naabu + nmap service detection.

        Args:
            ctx: ToolContext with ``target`` set to the host to scan.

        Returns:
            UnifiedToolResult with ``ports`` populated as list of dicts:
            ``{"port": 80, "protocol": "tcp", "service": "http", ...}``
        """
        target = ctx.target
        ports = self.DEFAULT_PORTS
        slog = ScanLogger(self.tool_name, engagement_id=target)
        slog.phase_header("PORT SCAN", f"target={target}, ports={ports}")

        result = UnifiedToolResult(
            tool_name=self.tool_name,
            target=target,
        )
        builder = FindingBuilder(source_tool=self.tool_name, engagement_id=target)

        # ── Feature flag gate ──────────────────────────────────────────
        if not is_enabled("PORT_SCANNER", default=False):
            slog.info("Port scanner disabled (ARGUS_FF_PORT_SCANNER not set)")
            logger.info("Port scanner disabled (ARGUS_FF_PORT_SCANNER not set)")
            result.status = ToolStatus.SKIPPED
            result.mark_finished()
            return result

        # ── Tool availability check ────────────────────────────────────
        tools_available = self._check_tools_available()
        if not tools_available.get("naabu", False):
            msg = "naabu not available — skipping port scan"
            logger.warning(msg)
            return UnifiedToolResult(
                tool_name=self.tool_name,
                target=target,
                status=ToolStatus.NONZERO_EXIT,
                error_message=msg,
            )

        live_ports: list[dict] = []

        # ── Phase 1: naabu SYN scan via ToolRunner ────────────────────
        slog.tool_start("naabu", f"target={target}, ports={ports}")
        try:
            naabu_result = self._tool_runner.run(
                "naabu",
                ["-host", target, "-ports", ports, "-json"],
                timeout=self.NAABU_TIMEOUT,
            )
            if naabu_result.success:
                live_ports = self._parse_naabu_ports(naabu_result.stdout)
                slog.tool_complete("naabu", success=True, findings=len(live_ports))
                logger.info("naabu found %d live ports", len(live_ports))
            else:
                slog.tool_complete("naabu", success=False)
                logger.warning(
                    "naabu failed: %s", naabu_result.error or naabu_result.stderr[:200]
                )
        except Exception as e:
            slog.tool_complete("naabu", success=False)
            logger.warning("naabu scan failed: %s", e)
            result.error_message = str(e)
            result.mark_finished()
            return result

        if not live_ports:
            result.mark_finished()
            return result

        # ── Phase 2: nmap service detection via ToolRunner ────────────
        port_list = ",".join(str(p.get("port")) for p in live_ports if p.get("port"))
        if not port_list:
            slog.warn("No live ports found for %s", target)
            result.mark_finished()
            return result

        slog.tool_start("nmap", f"target={target}, ports={port_list}")
        nmap_ports: dict[int, dict] = {}
        try:
            nmap_result = self._tool_runner.run(
                "nmap",
                ["-sV", "-sC", "-p", port_list, target, "-oX", "-"],
                timeout=self.NMAP_TIMEOUT,
            )
            if nmap_result.success:
                nmap_ports = self._parse_nmap_services(nmap_result.stdout)
                slog.tool_complete("nmap", success=True, findings=len(nmap_ports))
            else:
                slog.tool_complete("nmap", success=False)
                logger.warning(
                    "nmap service detection failed: %s",
                    nmap_result.error or nmap_result.stderr[:200],
                )
        except Exception as e:
            slog.tool_complete("nmap", success=False)
            logger.warning("nmap service detection failed: %s", e)

        # ── Merge results ────────────────────────────────────────────
        final_ports: list[dict] = []
        seen = set[int]()

        # nmap data first (has service details)
        for port_num in sorted(nmap_ports):
            final_ports.append(nmap_ports[port_num])
            seen.add(port_num)

        # naabu fills in any ports nmap didn't cover
        for p in live_ports:
            port_num = p.get("port", 0)
            if port_num not in seen:
                final_ports.append(
                    {
                        "port": port_num,
                        "protocol": p.get("protocol", "tcp"),
                        "service": "",
                        "version": "",
                        "state": "open",
                    }
                )
                seen.add(port_num)

        # Log open ports as findings
        for port_dict in final_ports:
            builder.info(
                "OPEN_PORT",
                f"{target}:{port_dict['port']}/{port_dict['protocol']}",
                port_dict,
            )

        result.ports = final_ports
        result.findings = builder.findings
        result.mark_finished()
        return result

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _check_tools_available() -> dict[str, bool]:
        """Check whether required external binaries are available."""
        from tool_definitions import is_tool_available

        return {
            "naabu": is_tool_available("naabu"),
            "nmap": is_tool_available("nmap"),
        }

    @staticmethod
    def _parse_naabu_ports(stdout: str) -> list[dict]:
        """Parse naabu JSONL output. Each line is a JSON object."""
        ports: list[dict] = []
        if not stdout or not stdout.strip():
            return ports
        for line in stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                port_num = entry.get("port")
                if port_num is not None:
                    ports.append(
                        {
                            "port": int(port_num),
                            "protocol": entry.get("protocol", "tcp"),
                            "ip": entry.get("ip", ""),
                            "host": entry.get("host", ""),
                        }
                    )
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug("Failed to parse naabu line: %s (%s)", line, e)
                continue
        return ports

    @staticmethod
    def _parse_nmap_services(xml_output: str) -> dict[int, dict]:
        """
        Parse nmap XML output (-oX -) into a dict of port → port dict.

        Returns:
            Mapping of port number to port dict with service details.
            ``{80: {"port": 80, "protocol": "tcp", "service": "http", ...}}``
        """
        result: dict[int, dict] = {}
        if not xml_output or not xml_output.strip():
            return result

        try:
            root = ET.fromstring(xml_output)
        except ET.ParseError as e:
            logger.warning("Failed to parse nmap XML: %s", e)
            return result

        for host_elem in root.iter("host"):
            status_elem = host_elem.find("status")
            if status_elem is not None and status_elem.get("state") != "up":
                continue

            ports_elem = host_elem.find("ports")
            if ports_elem is None:
                continue

            for port_elem in ports_elem.iter("port"):
                port_id = port_elem.get("portid")
                protocol = port_elem.get("protocol", "tcp")
                if port_id is None:
                    continue

                state_elem = port_elem.find("state")
                state = (
                    state_elem.get("state", "open")
                    if state_elem is not None
                    else "open"
                )

                service_elem = port_elem.find("service")
                service_name = ""
                service_version = ""
                if service_elem is not None:
                    service_name = service_elem.get("name", "")
                    svc_product = service_elem.get("product", "")
                    svc_version = service_elem.get("version", "")
                    svc_extrainfo = service_elem.get("extrainfo", "")
                    parts = [p for p in [svc_product, svc_version, svc_extrainfo] if p]
                    service_version = " ".join(parts)

                port_num = int(port_id)
                result[port_num] = {
                    "port": port_num,
                    "protocol": protocol,
                    "service": service_name,
                    "version": service_version,
                    "state": state,
                }

        return result


def get_recommended_templates(open_ports: list[OpenPort]) -> dict[str, list[str]]:
    """Map discovered services to vulnerability scanner templates."""
    recommendations: dict[str, list[str]] = {}
    for port in open_ports:
        svc_key = port.service.lower()
        if svc_key in SERVICE_TEMPLATE_MAP:
            for scanner in SERVICE_TEMPLATE_MAP[svc_key]:
                target_key = f"{port.port}/{port.protocol}"
                if target_key not in recommendations:
                    recommendations[target_key] = []
                if scanner not in recommendations[target_key]:
                    recommendations[target_key].append(scanner)
    return recommendations
