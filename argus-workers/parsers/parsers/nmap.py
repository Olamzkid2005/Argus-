"""
Parser for nmap XML output.

Nmap is invoked with `-oX -` (XML to stdout) during port scanning.
This parser extracts open ports, their service information, and host details
from the XML output.
"""

import logging
import xml.etree.ElementTree as ET
from typing import Any

from parsers.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class NmapParser(BaseParser):
    """Parser for nmap XML output — extracts open ports and service details."""

    def parse(self, raw_output: str) -> list[dict]:
        findings: list[dict[str, Any]] = []
        if not raw_output or not raw_output.strip():
            return findings

        try:
            root = ET.fromstring(raw_output)
        except ET.ParseError:
            logger.warning("nmap: failed to parse XML output")
            return findings

        for host in root.findall(".//host"):
            address_el = host.find("address")
            addr = address_el.get("addr", "") if address_el is not None else ""

            hostnames_el = host.find("hostnames")
            hostname = ""
            if hostnames_el is not None:
                hn = hostnames_el.find("hostname")
                if hn is not None:
                    hostname = hn.get("name", "")

            for port in host.findall(".//port"):
                port_id = port.get("portid", "")
                protocol = port.get("protocol", "")
                state_el = port.find("state")
                state = state_el.get("state", "") if state_el is not None else ""

                if state != "open":
                    continue

                service_el = port.find("service")
                service_name = (
                    service_el.get("name", "") if service_el is not None else ""
                )
                service_product = (
                    service_el.get("product", "") if service_el is not None else ""
                )
                service_version = (
                    service_el.get("version", "") if service_el is not None else ""
                )
                service_extrainfo = (
                    service_el.get("extrainfo", "") if service_el is not None else ""
                )

                endpoint = f"{addr}:{port_id}"
                title = f"Open port: {port_id}/{protocol} ({service_name})"
                description = f"Found open port {port_id}/{protocol} running {service_name}"
                if service_product:
                    description += f" - {service_product} {service_version}".strip()

                finding = {
                    "type": "OPEN_PORT",
                    "severity": "INFO",
                    "endpoint": endpoint,
                    "title": title,
                    "evidence": {
                        "host": addr,
                        "hostname": hostname,
                        "port": port_id,
                        "protocol": protocol,
                        "state": state,
                        "service": service_name,
                        "product": service_product,
                        "version": service_version,
                        "extrainfo": service_extrainfo,
                    },
                    "confidence": 0.90,
                    "tool": "nmap",
                }
                findings.append(finding)

        return findings
