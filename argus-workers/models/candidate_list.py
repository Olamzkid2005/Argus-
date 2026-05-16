"""
CandidateList — structured scan output contract between scanner and LLM agent.

Formalises the data contract between deterministic tool execution and LLM
reasoning. Scanner tools write structured candidates into this object; the
agent reads a typed candidate list instead of raw prose.

Mirrors DeepSec's FileRecord contract pattern — typed, structured, sortable.
"""
from dataclasses import dataclass, field
from enum import StrEnum


class CandidateSource(StrEnum):
    """Source tool that flagged the candidate vulnerability."""
    NUCLEI_CVE     = "nuclei_cve"        # confirmed CVE template match
    NUCLEI_MISC    = "nuclei_misc"        # misconfiguration template
    DALFOX         = "dalfox"             # XSS hit
    SQLMAP         = "sqlmap"             # SQLi confirmed
    WEB_SCANNER    = "web_scanner"        # custom check
    RECON_ENDPOINT = "recon_endpoint"     # endpoint discovered, not yet tested
    CUSTOM_RULE    = "custom_rule"        # YAML rule match


# Source → quality ordering (lower = higher priority)
SOURCE_QUALITY: dict[CandidateSource, int] = {
    CandidateSource.NUCLEI_CVE: 0,
    CandidateSource.SQLMAP: 0,
    CandidateSource.DALFOX: 1,
    CandidateSource.WEB_SCANNER: 1,
    CandidateSource.NUCLEI_MISC: 2,
    CandidateSource.CUSTOM_RULE: 2,
    CandidateSource.RECON_ENDPOINT: 3,
}


@dataclass
class Candidate:
    """A specific location that warrants AI investigation.

    Tagged by source tool, vulnerability slug, and evidence snippet.
    """
    endpoint: str
    source: CandidateSource
    vuln_slug: str              # e.g. 'sql-injection', 'xss', 'idor'
    snippet: str                # raw tool output that flagged this
    line_hint: str | None = None
    confidence: float = 0.5


    @classmethod
    def from_finding(cls, finding: dict) -> "Candidate":
        """Create a Candidate from a raw finding dict (existing format, backward compat)."""
        tool = finding.get("source_tool") or finding.get("tool", "unknown")
        source = _map_tool_to_source(tool)

        return cls(
            endpoint=finding.get("endpoint", ""),
            source=source,
            vuln_slug=finding.get("type", "unknown").lower().replace("_", "-"),
            snippet=finding.get("evidence", {}).get("matched_text", "")
                or finding.get("evidence", {}).get("message", "")
                or str(finding.get("evidence", ""))[:200],
            confidence=finding.get("confidence", 0.5),
        )


@dataclass
class CandidateList:
    """Structured output from the scan phase for agent consumption.

    Typed, sortable by signal quality, with compact LLM prompt formatting.
    """
    target: str
    candidates: list[Candidate] = field(default_factory=list)

    @classmethod
    def from_findings(cls, target: str, findings: list[dict]) -> "CandidateList":
        """Build CandidateList from raw findings (existing format).

        Args:
            target: Target URL or path
            findings: List of finding dicts from tool execution

        Returns:
            CandidateList ready for agent consumption
        """
        return cls(
            target=target,
            candidates=[Candidate.from_finding(f) for f in findings],
        )

    def by_quality(self) -> list[Candidate]:
        """Return candidates sorted by signal quality — confirmed first."""
        return sorted(
            self.candidates,
            key=lambda c: SOURCE_QUALITY.get(c.source, 3),
        )

    def to_llm_summary(self) -> str:
        """Compact summary for injection into the agent user prompt.

        Groups candidates by vulnerability slug with endpoint counts.
        """
        if not self.candidates:
            return ""

        by_slug: dict[str, list[Candidate]] = {}
        for c in self.candidates:
            by_slug.setdefault(c.vuln_slug, []).append(c)

        lines = [f"=== SCAN CANDIDATES ({len(self.candidates)} total) ==="]
        for slug in sorted(by_slug):
            cands = by_slug[slug]
            endpoints = list({c.endpoint for c in cands})[:3]
            lines.append(
                f"{slug}: {len(cands)} hit(s) on {', '.join(endpoints)}"
            )
        return "\n".join(lines)


def _map_tool_to_source(tool_name: str) -> CandidateSource:
    """Map a tool name to its CandidateSource enum value."""
    mapping = {
        # Confirmed / high-reliability
        "nuclei": CandidateSource.NUCLEI_CVE,
        "web_scanner": CandidateSource.WEB_SCANNER,
        # Injection / SAST tools
        "dalfox": CandidateSource.DALFOX,
        "sqlmap": CandidateSource.SQLMAP,
        "jwt_tool": CandidateSource.WEB_SCANNER,
        "commix": CandidateSource.WEB_SCANNER,
        # SAST tools
        "semgrep": CandidateSource.CUSTOM_RULE,
        "gitleaks": CandidateSource.CUSTOM_RULE,
        "trufflehog": CandidateSource.CUSTOM_RULE,
        "bandit": CandidateSource.CUSTOM_RULE,
        "brakeman": CandidateSource.CUSTOM_RULE,
        "gosec": CandidateSource.CUSTOM_RULE,
        "eslint": CandidateSource.CUSTOM_RULE,
        "phpcs": CandidateSource.CUSTOM_RULE,
        "spotbugs": CandidateSource.CUSTOM_RULE,
        "trivy": CandidateSource.CUSTOM_RULE,
        # Misconfiguration / misc
        "nikto": CandidateSource.NUCLEI_MISC,
        # Recon tools
        "httpx": CandidateSource.RECON_ENDPOINT,
        "katana": CandidateSource.RECON_ENDPOINT,
        "ffuf": CandidateSource.RECON_ENDPOINT,
        "arjun": CandidateSource.RECON_ENDPOINT,
        "whatweb": CandidateSource.RECON_ENDPOINT,
        "naabu": CandidateSource.RECON_ENDPOINT,
        "amass": CandidateSource.RECON_ENDPOINT,
        "subfinder": CandidateSource.RECON_ENDPOINT,
        "gospider": CandidateSource.RECON_ENDPOINT,
        "gau": CandidateSource.RECON_ENDPOINT,
        "waybackurls": CandidateSource.RECON_ENDPOINT,
        "alterx": CandidateSource.RECON_ENDPOINT,
        "wpscan": CandidateSource.NUCLEI_MISC,
        "testssl": CandidateSource.NUCLEI_MISC,
        "custom_rule_engine": CandidateSource.CUSTOM_RULE,
    }
    return mapping.get(tool_name, CandidateSource.RECON_ENDPOINT)
