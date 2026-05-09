"""
ReconContext - Structured summary of reconnaissance findings for LLM consumption.

Distills raw recon findings into a compact dataclass the LLM can reason about
without being overwhelmed by thousands of raw output lines.
"""
from dataclasses import asdict, dataclass, field


@dataclass
class ReconContext:
    """Structured recon summary passed to the LLM agent for tool selection."""

    target_url: str = ""
    live_endpoints: list[str] = field(default_factory=list)
    subdomains: list[str] = field(default_factory=list)
    open_ports: list[dict] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    crawled_paths: list[str] = field(default_factory=list)
    parameter_bearing_urls: list[str] = field(default_factory=list)
    auth_endpoints: list[str] = field(default_factory=list)
    api_endpoints: list[str] = field(default_factory=list)
    findings_count: int = 0
    has_login_page: bool = False
    has_api: bool = False
    has_file_upload: bool = False

    # Repo scan fields
    scan_type: str = "url"  # "url" or "repo"
    repo_url: str = ""
    languages_detected: list[str] = field(default_factory=list)
    vulnerability_types: list[str] = field(default_factory=list)
    severity_breakdown: dict[str, int] = field(default_factory=dict)
    critical_files: list[str] = field(default_factory=list)
    frameworks_detected: list[str] = field(default_factory=list)
    has_hardcoded_secrets: bool = False
    dependency_vulns_count: int = 0
    repo_clone_success: bool = False
    target_profile: dict | None = None  # From target_profiles table, for cross-scan learning

    def to_llm_structured(self) -> str:
        """Return structured recon data as JSON for LLM tool selection."""
        import json

        data = {
            "target": self.target_url,
            "live_endpoints_count": len(self.live_endpoints),
            "parameter_bearing_urls": (self.parameter_bearing_urls or [])[:10],
            "auth_endpoints": (self.auth_endpoints or [])[:5],
            "api_endpoints": (self.api_endpoints or [])[:5],
            "open_ports": [p.get("port") for p in (self.open_ports or [])[:5]],
            "tech_stack": (self.tech_stack or [])[:10],
            "has_login_page": self.has_login_page,
            "has_api": self.has_api,
            "has_file_upload": self.has_file_upload,
            "findings_count": self.findings_count,
        }

        # Add target memory if available
        if self.target_profile:
            p = self.target_profile
            data["target_memory"] = {
                "prior_scans": p.get("total_scans", 0),
                "best_tools": p.get("best_tools", [])[:5],
                "noisy_tools": p.get("noisy_tools", [])[:5],
                "confirmed_vulnerability_types": p.get("confirmed_finding_types", [])[:10],
                "high_value_endpoints": p.get("high_value_endpoints", [])[:10],
            }

        return json.dumps(data, indent=2)

    def to_llm_summary(self) -> str:
        """Compact text summary for LLM context window. Max ~800 tokens."""
        lines = [
            f"=== RECON SUMMARY: {self.target_url} ===",
            f"Scan type: {self.scan_type.upper()}",
            f"Total raw findings: {self.findings_count}",
            "",
        ]

        if self.scan_type == "repo":
            lines.append(f"Repository: {self.repo_url}")
            if self.languages_detected:
                lines.append(f"Languages: {', '.join(self.languages_detected)}")
            if self.frameworks_detected:
                lines.append(f"Frameworks: {', '.join(self.frameworks_detected)}")
            if self.repo_clone_success:
                lines.append("Clone: successful")
            if self.severity_breakdown:
                parts = [f"{k}: {v}" for k, v in sorted(self.severity_breakdown.items())]
                lines.append(f"Severity: {' | '.join(parts)}")
            if self.vulnerability_types:
                lines.append(f"Vuln types: {', '.join(self.vulnerability_types[:15])}")
            if self.critical_files:
                lines.append(f"Critical files ({len(self.critical_files)}):")
                for f in self.critical_files[:10]:
                    lines.append(f"  - {f}")
            if self.has_hardcoded_secrets:
                lines.append("⚠ HARDCODED SECRETS DETECTED")
            if self.dependency_vulns_count > 0:
                lines.append(f"Dependency vulns: {self.dependency_vulns_count}")
        else:
            lines.extend([
                f"Live endpoints: {len(self.live_endpoints)}",
                f"Subdomains: {len(self.subdomains)}",
                f"Open ports: {len(self.open_ports)}",
            ])
            if self.tech_stack:
                lines.append(f"Tech stack: {', '.join(self.tech_stack[:10])}")
            if self.open_ports:
                port_strs = [f"{p.get('port', '?')}/{p.get('service', 'unknown')}" for p in self.open_ports[:10]]
                lines.append(f"Ports: {', '.join(port_strs)}")
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
                lines.append("Interesting paths (top 10):")
                for path in self.crawled_paths[:10]:
                    lines.append(f"  - {path}")

        flags = []
        if self.has_login_page:
            flags.append("LOGIN")
        if self.has_api:
            flags.append("API")
        if self.has_file_upload:
            flags.append("FILE_UPLOAD")
        if flags:
            lines.append(f"Detected: {', '.join(flags)}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize to dict for Redis storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ReconContext":
        """Deserialize from dict (e.g., loaded from Redis)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
