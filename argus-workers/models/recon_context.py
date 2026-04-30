"""
ReconContext - Structured summary of reconnaissance findings for LLM consumption.

Distills raw recon findings into a compact dataclass the LLM can reason about
without being overwhelmed by thousands of raw output lines.
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class ReconContext:
    """Structured recon summary passed to the LLM agent for tool selection."""

    target_url: str = ""
    live_endpoints: List[str] = field(default_factory=list)
    subdomains: List[str] = field(default_factory=list)
    open_ports: List[Dict] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    crawled_paths: List[str] = field(default_factory=list)
    parameter_bearing_urls: List[str] = field(default_factory=list)
    auth_endpoints: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)
    findings_count: int = 0
    has_login_page: bool = False
    has_api: bool = False
    has_file_upload: bool = False

    def to_llm_summary(self) -> str:
        """Compact text summary for LLM context window. Max ~800 tokens."""
        lines = [
            f"=== RECON SUMMARY: {self.target_url} ===",
            f"Live endpoints: {len(self.live_endpoints)}",
            f"Subdomains: {len(self.subdomains)}",
            f"Open ports: {len(self.open_ports)}",
            f"Total raw findings: {self.findings_count}",
            "",
        ]

        if self.tech_stack:
            lines.append(f"Tech stack: {', '.join(self.tech_stack[:10])}")

        if self.open_ports:
            port_strs = []
            for p in self.open_ports[:10]:
                port = p.get("port", "?")
                service = p.get("service", "unknown")
                port_strs.append(f"{port}/{service}")
            lines.append(f"Ports: {', '.join(port_strs)}")

        flags = []
        if self.has_login_page:
            flags.append("LOGIN")
        if self.has_api:
            flags.append("API")
        if self.has_file_upload:
            flags.append("FILE_UPLOAD")
        if flags:
            lines.append(f"Detected: {', '.join(flags)}")

        if self.subdomains:
            lines.append(f"Subdomains (top 10): {', '.join(self.subdomains[:10])}")

        if self.parameter_bearing_urls:
            lines.append(f"Parameter URLs ({len(self.parameter_bearing_urls)}):")
            for url in self.parameter_bearing_urls[:10]:
                lines.append(f"  - {url}")

        if self.auth_endpoints:
            lines.append(f"Auth endpoints: {', '.join(self.auth_endpoints[:5])}")

        if self.api_endpoints:
            lines.append(f"API endpoints: {', '.join(self.api_endpoints[:10])}")

        if self.crawled_paths:
            lines.append(f"Interesting paths (top 10):")
            for path in self.crawled_paths[:10]:
                lines.append(f"  - {path}")

        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Serialize to dict for Redis storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "ReconContext":
        """Deserialize from dict (e.g., loaded from Redis)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
