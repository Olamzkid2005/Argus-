"""Port discovery using naabu and nmap."""

from __future__ import annotations

import json
import logging
import subprocess
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class PortDiscovery:
    """Discover open ports using available tools.

    Falls back to direct subprocess calls when no tool_runner is provided,
    so the mapper works standalone without orchestrator context.
    """

    def __init__(self, tool_runner=None):
        self._tool_runner = tool_runner

    def discover(self, host: str, timeout: int = 300) -> list[dict]:
        """Discover open ports.

        Returns list of port dicts with port, protocol, service.
        """
        ports: dict[int, dict] = {}

        if self._tool_runner:
            for port in self._run_naabu(host, timeout):
                key = port["port"]
                if key not in ports:
                    ports[key] = port

            for port in self._run_nmap(host, list(ports.keys()), timeout):
                key = port["port"]
                if key in ports:
                    ports[key].update(port)
                else:
                    ports[key] = port
        else:
            # Standalone fallback — run naabu directly
            for port in self._run_naabu_direct(host, timeout):
                key = port["port"]
                if key not in ports:
                    ports[key] = port

        return sorted(ports.values(), key=lambda p: p.get("port", 0))

    def _run_naabu_direct(self, host: str, timeout: int) -> list[dict]:
        """Fallback: run naabu via direct subprocess when no tool_runner."""
        try:
            result = subprocess.run(
                ["naabu", "-host", host, "-json", "-silent"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                return []
            ports = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    ports.append(
                        {
                            "port": int(data.get("port", 0)),
                            "protocol": "tcp",
                            "service": data.get("service", ""),
                            "source": "naabu",
                        }
                    )
                except (json.JSONDecodeError, ValueError):
                    pass
            return ports
        except FileNotFoundError:
            logger.debug("naabu not installed, skipping")
            return []
        except Exception as e:
            logger.debug("naabu direct failed: %s", e)
            return []

    def _run_naabu(self, host: str, timeout: int) -> list[dict]:
        if not self._tool_runner:
            return []
        try:
            result = self._tool_runner.run(
                "naabu",
                ["-host", host, "-json", "-silent"],
                timeout=timeout,
            )
            if not result.status.is_ok:
                return []
            ports = []
            for line in result.stdout.strip().splitlines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    ports.append(
                        {
                            "port": int(data.get("port", 0)),
                            "protocol": "tcp",
                            "service": data.get("service", ""),
                            "source": "naabu",
                        }
                    )
                except (json.JSONDecodeError, ValueError):
                    pass
            return ports
        except Exception as e:
            logger.debug("naabu failed: %s", e)
            return []

    def _run_nmap(self, host: str, known_ports: list[int], timeout: int) -> list[dict]:
        if not self._tool_runner or not known_ports:
            return []
        port_str = ",".join(str(p) for p in known_ports[:100])
        try:
            result = self._tool_runner.run(
                "nmap",
                ["-sV", "-p", port_str, "-oX", "-", host],
                timeout=min(timeout, 120),
            )
            if not result.status.is_ok:
                return []
            try:
                root = ET.fromstring(result.stdout)
                ports = []
                for port_elem in root.findall(".//port"):
                    port_id = int(port_elem.get("portid", 0))
                    protocol = port_elem.get("protocol", "tcp")
                    service = port_elem.find("service")
                    service_name = (
                        service.get("name", "") if service is not None else ""
                    )
                    version = service.get("version", "") if service is not None else ""
                    ports.append(
                        {
                            "port": port_id,
                            "protocol": protocol,
                            "service": service_name,
                            "version": version,
                            "source": "nmap",
                        }
                    )
                return ports
            except ET.ParseError:
                return []
        except Exception as e:
            logger.debug("nmap failed: %s", e)
            return []
