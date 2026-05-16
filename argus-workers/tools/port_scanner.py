"""
Port Scanner — naabu (SYN scan) + nmap (service detection) via subprocess.

Gated behind ARGUS_FF_PORT_SCANNER feature flag.
Runs during recon phase after subdomain discovery.
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from feature_flags import is_enabled
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


@dataclass
class PortScanResult:
    target: str
    open_ports: list[OpenPort] = field(default_factory=list)
    service_map: dict[int, OpenPort] = field(default_factory=dict)
    scan_duration: float = 0.0

    @property
    def suggested_templates(self) -> dict[str, list[str]]:
        templates: dict[str, list[str]] = {}
        for port in self.open_ports:
            svc = port.service.lower()
            if svc in SERVICE_TEMPLATE_MAP:
                if self.target not in templates:
                    templates[self.target] = []
                for scanner in SERVICE_TEMPLATE_MAP[svc]:
                    if scanner not in templates[self.target]:
                        templates[self.target].append(scanner)
        return templates

    def _service_name_lower(self, port: OpenPort | None = None) -> str:
        if port is None:
            return ""
        return port.service.lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "open_ports": [p.to_dict() for p in self.open_ports],
            "service_map": {str(k): v.to_dict() for k, v in self.service_map.items()},
            "scan_duration": self.scan_duration,
            "suggested_templates": self.suggested_templates,
        }


class PortScanner:
    """Comprehensive port scanning with service detection via ToolRunner."""

    NAABU_TIMEOUT = 600
    NMAP_TIMEOUT = 900

    def __init__(self):
        # ToolRunner handles locked environment, dangerous command detection,
        # circuit breaker, and output size limits (unlike raw subprocess.run).
        self._tool_runner = ToolRunner()

    def scan(self, target: str, ports: str = "1-10000") -> PortScanResult:
        """
        Run port scan with naabu + nmap service detection via ToolRunner.

        1. Feature-gated by ARGUS_FF_PORT_SCANNER.
        2. Fast SYN scan via naabu with JSONL output.
        3. Service detection via nmap -sV -sC on live ports.
        4. Returns structured PortScanResult.

        All subprocess calls go through ToolRunner which provides safety checks,
        environment locking, circuit breaker, and output size enforcement.
        """
        slog = ScanLogger("port_scanner", engagement_id=target)
        slog.phase_header("PORT SCAN", f"target={target}, ports={ports}")

        result = PortScanResult(target=target)
        start = time.time()

        if not is_enabled("PORT_SCANNER", default=False):
            slog.info("Port scanner disabled (ARGUS_FF_PORT_SCANNER not set)")
            logger.info("Port scanner disabled (ARGUS_FF_PORT_SCANNER not set)")
            return result

        live_ports: list[dict] = []

        # --- Phase 1: naabu SYN scan via ToolRunner ---
        slog.tool_start("naabu", f"target={target}, ports={ports}")
        try:
            naabu_result = self._tool_runner.run(
                "naabu", ["-host", target, "-ports", ports, "-json"],
                timeout=self.NAABU_TIMEOUT,
            )
            if naabu_result.success:
                live_ports = self._parse_naabu_ports(naabu_result.stdout)
                slog.tool_complete("naabu", success=True, findings=len(live_ports))
                logger.info("naabu found %d live ports", len(live_ports))
            else:
                slog.tool_complete("naabu", success=False)
                logger.warning("naabu failed: %s", naabu_result.error or naabu_result.stderr[:200])
        except Exception as e:
            slog.tool_complete("naabu", success=False)
            logger.warning("naabu scan failed: %s", e)
            return result

        if not live_ports:
            result.scan_duration = time.time() - start
            return result

        # --- Phase 2: nmap service detection via ToolRunner ---
        port_list = ",".join(str(p.get("port")) for p in live_ports if p.get("port"))
        if not port_list:
            slog.warn(f"No live ports found for {target}")
            result.scan_duration = time.time() - start
            return result

        slog.tool_start("nmap", f"target={target}, ports={port_list}")
        try:
            nmap_result = self._tool_runner.run(
                "nmap", ["-sV", "-sC", "-p", port_list, target, "-oX", "-"],
                timeout=self.NMAP_TIMEOUT,
            )
            if nmap_result.success:
                result = self._parse_nmap_services(nmap_result.stdout, result)
                slog.tool_complete("nmap", success=True, findings=len(result.open_ports))
            else:
                slog.tool_complete("nmap", success=False)
                logger.warning("nmap service detection failed: %s", nmap_result.error or nmap_result.stderr[:200])
        except Exception as e:
            slog.tool_complete("nmap", success=False)
            logger.warning("nmap service detection failed: %s", e)

        # Build result from naabu data even if nmap failed
        for p in live_ports:
            op = OpenPort(
                port=p.get("port", 0),
                protocol=p.get("protocol", "tcp"),
                state="open",
            )
            if op.port not in result.service_map:
                result.open_ports.append(op)
                result.service_map[op.port] = op

        result.scan_duration = time.time() - start
        return result

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
                    ports.append({
                        "port": int(port_num),
                        "protocol": entry.get("protocol", "tcp"),
                        "ip": entry.get("ip", ""),
                        "host": entry.get("host", ""),
                    })
            except (json.JSONDecodeError, ValueError) as e:
                logger.debug("Failed to parse naabu line: %s (%s)", line, e)
                continue
        return ports

    @staticmethod
    def _parse_nmap_services(xml_output: str, result: PortScanResult) -> PortScanResult:
        """Parse nmap XML output (-oX -) into PortScanResult."""
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
                state = state_elem.get("state", "open") if state_elem is not None else "open"

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

                op = OpenPort(
                    port=int(port_id),
                    protocol=protocol,
                    service=service_name,
                    version=service_version,
                    state=state,
                )
                result.open_ports.append(op)
                result.service_map[op.port] = op

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
