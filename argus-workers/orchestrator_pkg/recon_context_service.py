"""ReconContextService — builds and persists ReconContext from repo scan findings.

Extracted from Orchestrator.run_repo_scan() to reduce orchestrator.py's scope.
"""

from __future__ import annotations

import logging
import os

from models.recon_context import ReconContext
from tasks.utils import save_recon_context

logger = logging.getLogger(__name__)

# Maps file extensions to display names for language detection
_LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rb": "Ruby",
    ".php": "PHP",
    ".rs": "Rust",
    ".cs": "C#",
    ".swift": "Swift",
}

# Substrings for framework detection in file paths
_FRAMEWORK_PATTERNS: list[tuple[str, str]] = [
    ("flask", "Flask"),
    ("django", "Django"),
    ("express", "Express"),
    ("nestjs", "Express"),
    ("spring", "Spring"),
    ("laravel", "Laravel"),
    ("rails", "Rails"),
    ("fastapi", "FastAPI"),
]


class ReconContextService:
    """Builds and persists a ReconContext from repository scan findings."""

    @staticmethod
    def build_and_save(
        engagement_id: str,
        findings: list[dict],
        repo_url: str,
    ) -> ReconContext | None:
        """Build a ReconContext from repo findings and persist it.

        Returns the ReconContext on success, or None on failure.
        """
        try:
            vuln_types = list({f.get("type", "UNKNOWN") for f in findings})
            severity_breakdown: dict[str, int] = {}
            critical_files: list[str] = []
            has_secrets = False
            dep_vulns = 0

            for f in findings:
                sev = f.get("severity", "INFO")
                severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
                if sev in ("CRITICAL", "HIGH"):
                    fp = f.get("file_path") or f.get("endpoint", "")
                    if fp and fp not in critical_files:
                        critical_files.append(fp)
                if f.get("type") in (
                    "EXPOSED_SECRET",
                    "COMMITTED_SECRET",
                    "HARDCODED_SECRET",
                ):
                    has_secrets = True
                if f.get("type") == "DEPENDENCY_VULNERABILITY":
                    dep_vulns += 1

            # ── Language detection ──
            detected_langs: set[str] = set()
            for f in findings:
                fp = f.get("file_path") or f.get("endpoint", "")
                ext = os.path.splitext(fp)[1]
                if ext in _LANG_EXTENSIONS:
                    detected_langs.add(_LANG_EXTENSIONS[ext])

            # ── Framework detection ──
            frameworks: list[str] = []
            for f in findings:
                fp = (f.get("file_path") or f.get("endpoint", "")).lower()
                for keyword, framework in _FRAMEWORK_PATTERNS:
                    if keyword in fp:
                        frameworks.append(framework)

            # ── AI surface analysis ──
            ai_surface_findings = [f for f in findings if f.get("source_tool") == "ai-surface"]
            ai_categories: set[str] = set()
            confirmed_risks = 0
            likely_risks = 0
            has_mcp = False
            has_agents = False
            has_vector = False
            has_gateway = False

            for f in ai_surface_findings:
                category = f.get("ai_surface_category") or ""
                if category:
                    ai_categories.add(category)
                verdict = f.get("ai_surface_verdict")
                if verdict == "confirmed":
                    confirmed_risks += 1
                elif verdict == "likely":
                    likely_risks += 1
                has_mcp = has_mcp or category == "mcp-server"
                has_agents = has_agents or category == "agent-framework"
                has_vector = has_vector or category == "vector-store"
                has_gateway = has_gateway or category == "model-gateway"

            ctx = ReconContext(
                target_url=repo_url,
                scan_type="repo",
                repo_url=repo_url,
                findings_count=len(findings),
                repo_clone_success=True,
                languages_detected=sorted(detected_langs),
                vulnerability_types=sorted(set(vuln_types)),
                severity_breakdown=severity_breakdown,
                critical_files=critical_files[:20],
                frameworks_detected=list(set(frameworks)),
                has_hardcoded_secrets=has_secrets,
                dependency_vulns_count=dep_vulns,
                has_source_access=True,
                ai_surface_categories=sorted(ai_categories),
                ai_surface_confirmed_risk_count=confirmed_risks,
                ai_surface_likely_risk_count=likely_risks,
                has_mcp_servers=has_mcp,
                has_agent_frameworks=has_agents,
                has_vector_stores=has_vector,
                has_model_gateways=has_gateway,
            )
            save_recon_context(engagement_id, ctx)
            logger.info(
                "Saved repo recon context for %s: %d languages, %d vuln types",
                engagement_id,
                len(detected_langs),
                len(vuln_types),
            )
            return ctx
        except Exception as e:
            logger.warning(
                "Failed to build repo recon context (non-fatal): %s",
                e,
            )
            return None
