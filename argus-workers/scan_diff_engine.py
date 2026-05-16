"""
ScanDiffEngine — compare findings across two scans of the same target.

Fingerprinting strategy:
  Primary:   sha256(type + endpoint + payload_hash[:8])
  Fallback:  sha256(type + endpoint) — used when evidence payload is empty

This means:
  - Same vuln type, same endpoint, same payload → SAME fingerprint (persistent)
  - Same vuln type, same endpoint, different payload → DIFFERENT fingerprint (new finding)
  - Missing evidence → falls back to type+endpoint only
"""

import contextlib
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class ScanDiffEngine:
    """Compares findings between two scans of the same target.

    Categorizes findings into: new, fixed, regressed, persistent, severity_changed.
    Used by the Continuous Monitoring feature (Steps 9-11).
    """

    CAT_NEW = "new"
    CAT_FIXED = "fixed"
    CAT_REGRESSED = "regressed"
    CAT_PERSISTENT = "persistent"
    CAT_SEVERITY_CHANGED = "severity_changed"

    def __init__(self, db_url: str | None = None):
        self.db_url = db_url

    # ── Fingerprinting ─────────────────────────────────────────────

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        """Normalize endpoint URL for stable fingerprinting across scans.

        Strips query parameters and fragments so the same vulnerability on
        the same path gets the same fingerprint even if query params differ
        (e.g., ?token=abc123 vs ?token=xyz789).
        """
        if not endpoint:
            return endpoint
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else parsed.path

    @staticmethod
    def _fallback_fingerprint(finding: dict) -> str:
        """Cross-scan fallback fingerprint using type+endpoint only."""
        finding_type = finding.get("type", "UNKNOWN")
        endpoint = ScanDiffEngine._normalize_endpoint(finding.get("endpoint", ""))
        key = f"{finding_type}:{endpoint}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _has_payload(finding: dict) -> bool:
        """Check if a finding has a meaningful evidence payload.

        Returns True if the finding's evidence contains a non-empty,
        non-None payload string. Used to distinguish payload-bearing
        findings from fallback-only entries.
        """
        evidence = finding.get("evidence", {}) or {}
        payload = ""
        if isinstance(evidence, dict):
            payload = evidence.get("payload", "")
        elif isinstance(evidence, str):
            payload = evidence
        return bool(payload and payload != "None")

    @staticmethod
    def _fingerprint(finding: dict) -> str:
        """Stable fingerprint for matching findings across scans.

        Multi-field to distinguish payload-level differences:
          primary:   sha256(type + normalized_endpoint + payload_hash[:8])
          fallback:  sha256(type + normalized_endpoint)

        Args:
            finding: Finding dict with type, endpoint, evidence fields

        Returns:
            16-character hex fingerprint string
        """
        finding_type = finding.get("type", "UNKNOWN")
        endpoint = ScanDiffEngine._normalize_endpoint(finding.get("endpoint", ""))

        # Extract payload from evidence
        evidence = finding.get("evidence", {}) or {}
        payload = ""
        if isinstance(evidence, dict):
            payload = evidence.get("payload", "")
        elif isinstance(evidence, str):
            payload = evidence

        if payload and payload != "None":
            payload_hash = hashlib.sha256(
                str(payload).encode()
            ).hexdigest()[:8]
            key = f"{finding_type}:{endpoint}:{payload_hash}"
        else:
            key = f"{finding_type}:{endpoint}"

        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @staticmethod
    def _load_fixed_fingerprints(profile: dict | None) -> set[str]:
        """Load fingerprints of findings previously marked as fixed.

        Args:
            profile: Target profile dict, or None

        Returns:
            Set of fingerprint strings
        """
        if not profile:
            return set()
        fixed = profile.get("fixed_finding_fingerprints", [])
        if isinstance(fixed, list):
            return set(fixed)
        return set()

    def _load_findings(self, engagement_id: str) -> dict[str, dict]:
        """Load findings for an engagement, keyed by fingerprint.

        Args:
            engagement_id: UUID of the engagement

        Returns:
            Dict mapping fingerprint → finding dict
        """
        from database.connection import connect

        conn = None
        try:
            conn = connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, type, severity, endpoint, evidence, confidence,
                       source_tool, cvss_score
                FROM findings
                WHERE engagement_id = %s
                """,
                (engagement_id,),
            )
            columns = [desc[0] for desc in cursor.description]
            findings: dict[str, dict] = {}
            for row in cursor.fetchall():
                finding = dict(zip(columns, row, strict=False))
                fp = self._fingerprint(finding)
                findings[fp] = finding
            return findings
        except Exception as e:
            logger.error(
                "Failed to load findings for %s: %s", engagement_id, e
            )
            return {}
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    # ── Core diff ──────────────────────────────────────────────────

    def diff(
        self,
        prev_id: str | None,
        curr_id: str,
        profile: dict | None = None,
    ) -> dict:
        """Compare findings between two engagements.

        Args:
            prev_id: Previous engagement ID. None means first scan (no previous).
            curr_id: Current engagement ID (must exist)
            profile: Optional target profile for fixed/regressed detection

        Returns:
            Diff dict with categories: new, fixed, regressed, persistent,
            severity_changed, and summary stats.
        """
        if prev_id is None:
            return {
                "new": [], "fixed": [], "regressed": [],
                "persistent": [], "severity_changed": [],
                "summary": {"new_count": 0, "fixed_count": 0, "regressed_count": 0,
                            "persistent_count": 0, "severity_changed_count": 0,
                            "action_required": False, "total_current": 0, "total_previous": 0},
            }
        prev = self._load_findings(prev_id)
        curr = self._load_findings(curr_id)
        fixed_fps = self._load_fixed_fingerprints(profile)

        result = {
            self.CAT_NEW: [],
            self.CAT_FIXED: [],
            self.CAT_REGRESSED: [],
            self.CAT_PERSISTENT: [],
            self.CAT_SEVERITY_CHANGED: [],
        }

        curr_fps = set(curr.keys())
        prev_fps = set(prev.keys())

        # Build fallback fingerprint maps for cross-scan matching
        curr_fallback = {self._fallback_fingerprint(f): fp for fp, f in curr.items()}
        prev_fallback = {self._fallback_fingerprint(f): fp for fp, f in prev.items()}

        # New: in current but not previous
        for fp in curr_fps - prev_fps:
            if fp in fixed_fps:
                result[self.CAT_REGRESSED].append(curr[fp])
            else:
                # Check fallback fingerprint for cross-scan matching.
                # Fallback is only valid when one or both sides lack a payload.
                # If BOTH sides have payloads, different primary fingerprints
                # mean genuinely different findings — not the same vuln.
                fb_fp = self._fallback_fingerprint(curr[fp])
                if fb_fp in prev_fallback:
                    prev_fp = prev_fallback[fb_fp]
                    prev_finding = prev[prev_fp]
                    curr_has_payload = self._has_payload(curr[fp])
                    prev_has_payload = self._has_payload(prev_finding)
                    if curr_has_payload and prev_has_payload:
                        # Both sides have payloads — different FP = different finding
                        result[self.CAT_NEW].append(curr[fp])
                    else:
                        # One or both sides missing payload — likely same vulnerability
                        result[self.CAT_PERSISTENT].append(curr[fp])
                else:
                    result[self.CAT_NEW].append(curr[fp])

        # Fixed: in previous but not current — cross-check via fallback fingerprint
        for fp in prev_fps - curr_fps:
            fb_fp = self._fallback_fingerprint(prev[fp])
            if fb_fp in curr_fallback:
                continue  # Already accounted as persistent in the New branch
            result[self.CAT_FIXED].append(prev[fp])

        # Changed: in both but severity differs
        for fp in curr_fps & prev_fps:
            if curr[fp].get("severity", "UNKNOWN") != prev[fp].get("severity", "UNKNOWN"):
                result[self.CAT_SEVERITY_CHANGED].append({
                    "finding": curr[fp],
                    "old_severity": prev[fp].get("severity", "UNKNOWN"),
                    "new_severity": curr[fp].get("severity", "UNKNOWN"),
                })
            else:
                result[self.CAT_PERSISTENT].append(curr[fp])

        # Summary
        result["summary"] = {
            "new_count": len(result[self.CAT_NEW]),
            "fixed_count": len(result[self.CAT_FIXED]),
            "regressed_count": len(result[self.CAT_REGRESSED]),
            "persistent_count": len(result[self.CAT_PERSISTENT]),
            "severity_changed_count": len(
                result[self.CAT_SEVERITY_CHANGED]
            ),
            "action_required": (
                len(result[self.CAT_NEW])
                + len(result[self.CAT_REGRESSED])
                + len(result[self.CAT_SEVERITY_CHANGED])
            ) > 0,
            "total_current": len(curr),
            "total_previous": len(prev),
        }

        return result

    # ── Auto-close ─────────────────────────────────────────────────

    def mark_fixed(
        self, finding_id: str, closed_in_engagement_id: str
    ) -> bool:
        """Mark a finding as fixed (soft-delete + record in engagement).

        Args:
            finding_id: UUID of finding to mark fixed
            closed_in_engagement_id: Engagement where the finding was confirmed fixed

        Returns:
            True if the finding was updated
        """
        conn = None
        try:
            from database.connection import connect

            conn = connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE findings
                SET status = 'fixed',
                    closed_at = NOW(),
                    closed_in_engagement_id = %s
                WHERE id = %s AND status != 'fixed'
                """,
                (closed_in_engagement_id, finding_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(
                "Failed to mark finding %s as fixed: %s",
                finding_id, e,
            )
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return False
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    def store_diff_in_profile(
        self, org_id: str, domain: str, diff: dict
    ) -> bool:
        """Store the diff summary in the target profile.

        Args:
            org_id: Organization ID
            domain: Target domain
            diff: Diff dict from diff() method

        Returns:
            True if stored successfully
        """
        conn = None
        try:
            from database.connection import connect

            conn = connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE target_profiles
                SET last_diff_summary = %s::jsonb,
                    updated_at = NOW()
                WHERE org_id = %s AND target_domain = %s
                """,
                (json.dumps(diff["summary"]), org_id, domain),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.warning(
                "Failed to store diff in profile: %s", e
            )
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return False
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()
