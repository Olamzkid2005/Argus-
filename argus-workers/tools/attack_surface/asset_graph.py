"""Unified asset model for attack surface mapping."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Asset:
    asset_type: str
    value: str
    metadata: dict = field(default_factory=dict)


class AssetGraph:
    """Unified asset model combining subdomains, ports, URLs, and technologies."""

    def __init__(self):
        self.subdomains: set[str] = set()
        self.ports: dict[str, list[dict]] = defaultdict(list)
        self.urls: set[str] = set()
        self.technologies: set[str] = set()
        self.api_endpoints: set[str] = set()

    def add_subdomain(self, subdomain: str) -> None:
        self.subdomains.add(subdomain)

    def add_port(self, host: str, port_info: dict) -> None:
        self.ports[host].append(port_info)

    def add_url(self, url: str) -> None:
        self.urls.add(url)

    def add_technology(self, tech: str) -> None:
        self.technologies.add(tech)

    def add_api_endpoint(self, endpoint: str) -> None:
        self.api_endpoints.add(endpoint)

    def to_dict(self) -> dict:
        return {
            "subdomains": sorted(self.subdomains),
            "ports": {k: sorted(v, key=lambda p: p.get("port", 0)) for k, v in self.ports.items()},
            "urls": sorted(self.urls),
            "technologies": sorted(self.technologies),
            "api_endpoints": sorted(self.api_endpoints),
            "stats": {
                "subdomain_count": len(self.subdomains),
                "url_count": len(self.urls),
                "port_count": sum(len(v) for v in self.ports.values()),
                "technology_count": len(self.technologies),
                "api_endpoint_count": len(self.api_endpoints),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")
