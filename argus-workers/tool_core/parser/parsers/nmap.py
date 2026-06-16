import xml.etree.ElementTree as ET

from ..normalizer import normalize_severity
from ..types import NormalizedFinding


def parse(output: str) -> list[NormalizedFinding]:
    findings = []
    try:
        root = ET.fromstring(output)
    except ET.ParseError:
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
            service_el = port.find("service")
            service_name = service_el.get("name", "") if service_el is not None else ""
            service_product = service_el.get("product", "") if service_el is not None else ""
            service_version = service_el.get("version", "") if service_el is not None else ""

            if state != "open":
                continue

            title = f"Open port: {port_id}/{protocol} ({service_name})"
            description = f"Found open port {port_id}/{protocol} running {service_name}"
            if service_product:
                description += f" - {service_product} {service_version}"

            findings.append(NormalizedFinding(
                title=title,
                severity=normalize_severity("info", 0),
                confidence=4,
                description=description,
                tool="nmap",
                evidence=[{
                    "type": "port",
                    "port": port_id,
                    "protocol": protocol,
                    "state": state,
                    "service": service_name,
                    "product": service_product,
                    "version": service_version,
                    "host": addr,
                    "hostname": hostname,
                }],
                subtype="port_open",
            ))

    return findings
