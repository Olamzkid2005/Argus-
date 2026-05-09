"""
Repository for per-target intelligence profiles (Target Memory feature).

Thread-safe: each method acquires its own connection from the pool.
Pure-function reads: the profile is a snapshot, not a live cursor.
"""

import contextlib
import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class TargetProfileRepository:
    """Per-domain intelligence profile builder and reader.

    Builds a persistent profile per target domain after each scan.
    Profiles are used by the LLM agent to select better tools on rescan.
    """

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string

    # ── Domain extraction ───────────────────────────────────────────

    @staticmethod
    def _extract_domain(target_url: str) -> str:
        """Normalize a URL to a stable domain key.

        Args:
            target_url: Full URL (e.g. 'https://www.example.com/path')

        Returns:
            Domain string (e.g. 'www.example.com')
        """
        parsed = urlparse(target_url)
        return parsed.netloc or target_url.split("/")[0]

    # ── Profile persistence ─────────────────────────────────────────

    def upsert_from_engagement(
        self,
        org_id: str,
        target_url: str,
        engagement_id: str,
        recon_context: dict | None,
        findings: list[dict],
        tool_accuracy_fp_rates: dict[str, float] | None = None,
    ) -> dict | None:
        """Create or update the target profile after a scan completes.

        Stats are pure functions of the scan output — no side effects,
        no mutable state. Merges into existing profile using JSONB operations.

        Args:
            org_id: Organization ID
            target_url: Target URL for domain extraction
            engagement_id: Just-completed engagement ID
            recon_context: ReconContext dict or None
            findings: Full list of findings from this engagement
            tool_accuracy_fp_rates: {tool: fp_rate} for noisy-tool detection

        Returns:
            Updated profile dict, or None on failure
        """
        domain = self._extract_domain(target_url)
        if not domain or not org_id:
            return None

        # Build profile parts from this scan
        endpoints = list({
            f.get("endpoint", "") for f in findings if f.get("endpoint")
        })[:100]

        tech_stack = []
        if recon_context and isinstance(recon_context, dict):
            tech_stack = recon_context.get("tech_stack", [])[:20]

        # Finding type stats
        type_counts: dict[str, int] = {}
        high_value_endpoints: list[str] = []
        for f in findings:
            ft = f.get("type", "UNKNOWN")
            type_counts[ft] = type_counts.get(ft, 0) + 1
            if f.get("severity") in ("HIGH", "CRITICAL"):
                ep = f.get("endpoint", "")
                if ep and ep not in high_value_endpoints:
                    high_value_endpoints.append(ep)

        # Tool performance: which tools found actual findings
        tool_counts: dict[str, int] = {}
        for f in findings:
            tool = f.get("source_tool") or f.get("tool", "unknown")
            if f.get("severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
                tool_counts[tool] = tool_counts.get(tool, 0) + 1

        best_tools = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
        best_tools_list = [
            {"tool": t, "finding_count": c,
             "last_seen": datetime.now(UTC).isoformat()}
            for t, c in best_tools
        ]

        # Noisy tools from tool_accuracy
        noisy_tools_list: list[str] = []
        if tool_accuracy_fp_rates:
            for tool, fp_rate in tool_accuracy_fp_rates.items():
                if fp_rate > 0.5:
                    noisy_tools_list.append(tool)

        # Persist (upsert with JSONB merge)
        conn = None
        try:
            from database.connection import connect

            conn = connect(self.connection_string)
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO target_profiles (
                    org_id, target_domain,
                    known_endpoints, known_tech_stack,
                    confirmed_finding_types,
                    high_value_endpoints,
                    best_tools, noisy_tools,
                    total_scans, last_scan_at, last_findings_count,
                    scan_ids
                ) VALUES (
                    %s, %s,
                    %s::jsonb, %s::jsonb,
                    %s::jsonb,
                    %s::jsonb,
                    %s::jsonb, %s::jsonb,
                    1, NOW(), %s,
                    %s::jsonb
                )
                ON CONFLICT (org_id, target_domain) DO UPDATE SET
                    known_endpoints = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            target_profiles.known_endpoints || EXCLUDED.known_endpoints
                        ) AS x
                        LIMIT 100
                    ),
                    known_tech_stack = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            target_profiles.known_tech_stack
                            || EXCLUDED.known_tech_stack
                        ) AS x
                        LIMIT 20
                    ),
                    confirmed_finding_types = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            target_profiles.confirmed_finding_types
                            || EXCLUDED.confirmed_finding_types
                        ) AS x
                        LIMIT 30
                    ),
                    high_value_endpoints = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            target_profiles.high_value_endpoints
                            || EXCLUDED.high_value_endpoints
                        ) AS x
                        LIMIT 20
                    ),
                    best_tools = CASE
                        WHEN jsonb_array_length(EXCLUDED.best_tools) > 0
                        THEN EXCLUDED.best_tools
                        ELSE target_profiles.best_tools
                    END,
                    noisy_tools = (
                        SELECT jsonb_agg(DISTINCT x)
                        FROM jsonb_array_elements_text(
                            target_profiles.noisy_tools || EXCLUDED.noisy_tools
                        ) AS x
                    ),
                    total_scans = target_profiles.total_scans + 1,
                    last_scan_at = NOW(),
                    last_findings_count = %s,
                    scan_ids = (
                        SELECT jsonb_agg(x) FROM (
                            SELECT DISTINCT x FROM (
                                SELECT jsonb_array_elements_text(
                                    target_profiles.scan_ids || %s::jsonb
                                ) AS x
                            ) sub LIMIT 20
                        ) sub2
                    ),
                    updated_at = NOW()
                """,
                (
                    org_id, domain,
                    json.dumps(endpoints), json.dumps(tech_stack),
                    json.dumps(list(type_counts.keys())),
                    json.dumps(high_value_endpoints[:20]),
                    json.dumps(best_tools_list), json.dumps(noisy_tools_list),
                    len(findings),
                    json.dumps([engagement_id]),
                    len(findings),
                    json.dumps([engagement_id]),
                ),
            )
            conn.commit()

            # Fetch and return the full profile
            cursor.execute(
                "SELECT * FROM target_profiles WHERE org_id = %s AND target_domain = %s",
                (org_id, domain),
            )
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row, strict=False)) if row else None

        except Exception as e:
            logger.error("Failed to upsert target profile for %s: %s", domain, e)
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return None
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    # ── Profile reading ─────────────────────────────────────────────

    def get_profile(self, org_id: str, target_domain: str) -> dict | None:
        """Get profile dict or None (first scan or error). Never raises.

        Args:
            org_id: Organization ID
            target_domain: Domain string (e.g. 'www.example.com')

        Returns:
            Profile dict, or None
        """
        if not org_id or not target_domain:
            return None

        conn = None
        try:
            from database.connection import connect

            conn = connect(self.connection_string)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM target_profiles WHERE org_id = %s AND target_domain = %s",
                (org_id, target_domain),
            )
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            return dict(zip(columns, row, strict=False)) if row else None
        except Exception as e:
            logger.warning("Could not load target profile: %s", e)
            return None
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    # ── LLM prompt section builder ──────────────────────────────────

    def to_llm_context(self, profile: dict) -> str:
        """Convert a profile to a compact prompt section (<800 tokens).

        Returns empty string if profile has no prior scans — zero prompt
        overhead on first scan.

        Args:
            profile: Profile dict from target_profiles table

        Returns:
            Formatted prompt section string, or empty string
        """
        if not profile or profile.get("total_scans", 0) == 0:
            return ""

        lines = [
            f"=== WHAT WE KNOW ABOUT THIS TARGET"
            f" ({profile['total_scans']} prior scans) ===",
        ]

        best = profile.get("best_tools", [])
        if best:
            tools_str = ", ".join(
                f"{t['tool']} ({t['finding_count']} findings)"
                for t in best[:4]
            )
            lines.append(f"Tools that found real issues: {tools_str}")

        noisy = profile.get("noisy_tools", [])
        if noisy:
            lines.append(
                f"Tools that were noisy/FP: {', '.join(noisy[:4])}"
            )

        finding_types = profile.get("confirmed_finding_types", [])
        if finding_types:
            lines.append(
                f"Confirmed vulnerability types:"
                f" {', '.join(finding_types[:6])}"
            )

        hot = profile.get("high_value_endpoints", [])
        if hot:
            lines.append("Previously vulnerable endpoints:")
            lines.extend(f"  - {e}" for e in hot[:5])

        lines.append(
            "INSTRUCTION: Prioritise tools that worked before. "
            "Skip tools marked noisy unless all better options are exhausted."
        )

        return "\n".join(lines)
