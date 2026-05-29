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
from urllib.parse import urlparse

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
        parsed = urlparse(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.scheme else parsed.path

    @staticmethod
    def fallback_fingerprint(finding: dict) -> str:
        """Cross-scan fallback fingerprint using type+endpoint only."""
        finding_type = finding.get("type", "UNKNOWN")
        endpoint = ScanDiffEngine._normalize_endpoint(finding.get("endpoint", ""))
        key = f"{finding_type}:{endpoint}"
        return hashlib.sha256(key.encode()).hexdigest()[:24]

    # Backward-compatible alias
    _fallback_fingerprint = fallback_fingerprint

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
    def fingerprint(finding: dict) -> str:
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

        return hashlib.sha256(key.encode()).hexdigest()[:24]

    # Backward-compatible alias
    _fingerprint = fingerprint

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
            raise RuntimeError(f"Failed to load findings for engagement {engagement_id}: {e}") from e
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    # ── Core diff ──────────────────────────────────────────────────

    @staticmethod
    def _empty_diff() -> dict:
        """Return an empty diff result with zero counts and action_required=False."""
        return {
            "new": [], "fixed": [], "regressed": [],
            "persistent": [], "severity_changed": [],
            "summary": {"new_count": 0, "fixed_count": 0, "regressed_count": 0,
                        "persistent_count": 0, "severity_changed_count": 0,
                        "action_required": False, "total_current": 0, "total_previous": 0,
                        "_error": "load_failure"},
        }

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
        try:
            prev = self._load_findings(prev_id)
        except RuntimeError as e:
            logger.error("Diff aborted — failed to load previous findings: %s", e)
            return self._empty_diff()
        try:
            curr = self._load_findings(curr_id)
        except RuntimeError as e:
            logger.error("Diff aborted — failed to load current findings: %s", e)
            return self._empty_diff()
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

        # Build fallback fingerprint maps for cross-scan matching.
        # Use defaultdict(list) to handle collisions: multiple findings
        # of the same type on the same endpoint (no payload) will share
        # the same fallback fingerprint. We accumulate all matching
        # primary fingerprints so the diff can check all candidates.
        from collections import defaultdict
        curr_fallback: dict[str, list[str]] = defaultdict(list)
        for fp, f in curr.items():
            curr_fallback[self._fallback_fingerprint(f)].append(fp)
        prev_fallback: dict[str, list[str]] = defaultdict(list)
        for fp, f in prev.items():
            prev_fallback[self._fallback_fingerprint(f)].append(fp)

        # Build fallback fingerprints for fixed findings (L-02 fix).
        # This catches regressions where a fixed finding returns with a
        # different payload — the primary FP won't match, but the fallback
        # FP (type + endpoint only) will.
        fixed_fallback_fps: set[str] = set()
        for fp in fixed_fps:
            if fp in prev:
                fixed_fallback_fps.add(self._fallback_fingerprint(prev[fp]))
            elif fp in curr:
                fixed_fallback_fps.add(self._fallback_fingerprint(curr[fp]))

        # New: in current but not previous
        for fp in curr_fps - prev_fps:
            if fp in fixed_fps:
                result[self.CAT_REGRESSED].append(curr[fp])
                continue

            # L-02: Also check fallback fingerprint against fixed findings.
            # If a finding was fixed with a different payload (different primary
            # FP) but same type+endpoint, it's a regression.
            fb_fp = self._fallback_fingerprint(curr[fp])
            if fb_fp in fixed_fallback_fps:
                result[self.CAT_REGRESSED].append(curr[fp])
                continue

            if fb_fp not in prev_fallback:
                result[self.CAT_NEW].append(curr[fp])
                continue

            # Fallback fingerprint matched — check all candidates.
            # If BOTH sides have payloads and primary fingerprints differ,
            # they are genuinely different findings (not the same vuln).
            curr_has_payload = self._has_payload(curr[fp])
            matched_as_persistent = False
            for prev_fp in prev_fallback[fb_fp]:
                prev_finding = prev[prev_fp]
                prev_has_payload = self._has_payload(prev_finding)
                if curr_has_payload and prev_has_payload:
                    # Both have payloads but different FP — genuinely different
                    continue
                # One or both missing payload — likely same vulnerability
                result[self.CAT_PERSISTENT].append(curr[fp])
                # Remove from prev_fps so the "Fixed" branch doesn't
                # also report it — it was already accounted for.
                prev_fps.discard(prev_fp)
                matched_as_persistent = True
                break
            if not matched_as_persistent:
                result[self.CAT_NEW].append(curr[fp])

        # Fixed: in previous but not current — cross-check via fallback fingerprint
        for fp in prev_fps - curr_fps:
            fb_fp = self._fallback_fingerprint(prev[fp])
            if fb_fp in curr_fallback:
                # Already accounted as persistent in the New branch above,
                # or there's a genuine fallback collision. Check whether any
                # current finding with this fallback has a payload match.
                any_real_persistent = False
                for curr_fp in curr_fallback[fb_fp]:
                    prev_f = prev[fp]
                    curr_f = curr[curr_fp]
                    if self._has_payload(prev_f) and self._has_payload(curr_f):
                        # Both have payloads — different primary FP means
                        # genuinely different findings. Not persistent.
                        continue
                    any_real_persistent = True
                    break
                if any_real_persistent:
                    continue
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

        Uses SELECT ... FOR UPDATE to prevent concurrent diff tasks from
        racing on the same finding row and corrupting audit trails.

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
                SELECT id FROM findings
                WHERE id = %s AND status != 'fixed'
                FOR UPDATE
                """,
                (finding_id,),
            )
            if not cursor.fetchone():
                conn.rollback()
                return False
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

    def batch_mark_fixed(
        self, finding_ids: list[str], closed_in_engagement_id: str
    ) -> int:
        """
        Batch-mark multiple findings as fixed in a single transaction.

        Replaces N separate mark_fixed() calls with one bulk UPDATE,
        reducing N round-trips to 1.

        Args:
            finding_ids: List of finding UUIDs to mark fixed
            closed_in_engagement_id: Engagement where findings were confirmed fixed

        Returns:
            Number of findings updated
        """
        if not finding_ids:
            return 0

        conn = None
        try:
            from database.connection import connect

            conn = connect(self.db_url)
            cursor = conn.cursor()
            # Lock rows before updating to prevent concurrent diff tasks
            # from racing on the same findings (matches single-row mark_fixed).
            cursor.execute(
                """
                SELECT id FROM findings
                WHERE id = ANY(%s) AND status != 'fixed'
                FOR UPDATE
                """,
                (finding_ids,),
            )
            # Only update rows that were actually locked (still not fixed)
            locked_ids = [row[0] for row in cursor.fetchall()]
            if not locked_ids:
                conn.rollback()
                return 0
            cursor.execute(
                """
                UPDATE findings
                SET status = 'fixed',
                    closed_at = NOW(),
                    closed_in_engagement_id = %s
                WHERE id = ANY(%s) AND status != 'fixed'
                """,
                (closed_in_engagement_id, locked_ids),
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(
                "Failed to batch-mark %d findings as fixed: %s",
                len(finding_ids), e,
            )
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return 0
        finally:
            if conn:
                with contextlib.suppress(Exception):
                    conn.close()

    def batch_mark_fixed_with_fps(
        self,
        finding_ids: list[str],
        findings: list[dict],
        closed_in_engagement_id: str,
        org_id: str,
        domain: str,
    ) -> int:
        """
        Atomically mark findings as fixed AND update fixed fingerprints.

        L-09: Combines batch_mark_fixed and fingerprint update in a single
        transaction to prevent inconsistency where findings are marked fixed
        but the profile's fingerprint list isn't updated (or vice versa).

        Args:
            finding_ids: List of finding UUIDs to mark fixed
            findings: Finding dicts for computing fingerprints
            closed_in_engagement_id: Engagement where findings were confirmed fixed
            org_id: Organization ID for profile update
            domain: Target domain for profile update

        Returns:
            Number of findings updated
        """
        if not finding_ids:
            return 0

        # Compute fingerprints for the findings being fixed.
        # R-06: Store BOTH primary and fallback fingerprints so regression
        # detection works regardless of whether the returning finding has
        # the same payload or a different one.
        fps = set()
        for f in findings:
            if f.get("id") in finding_ids:
                fps.add(self._fingerprint(f))
                fps.add(self._fallback_fingerprint(f))
        fps = list(fps)
        if not fps:
            fps = []

        conn = None
        try:
            from database.connection import connect

            conn = connect(self.db_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id FROM findings
                WHERE id = ANY(%s) AND status != 'fixed'
                FOR UPDATE
                """,
                (finding_ids,),
            )
            locked_ids = [row[0] for row in cursor.fetchall()]
            if not locked_ids:
                conn.rollback()
                return 0
            cursor.execute(
                """
                UPDATE findings
                SET status = 'fixed',
                    closed_at = NOW(),
                    closed_in_engagement_id = %s
                WHERE id = ANY(%s) AND status != 'fixed'
                """,
                (closed_in_engagement_id, locked_ids),
            )
            updated = cursor.rowcount

            # L-09: Update fixed fingerprints in the same transaction
            if fps and domain:
                cursor.execute(
                    """
                    UPDATE target_profiles
                    SET fixed_finding_fingerprints = (
                        SELECT jsonb_agg(elem ORDER BY elem)
                        FROM (
                            SELECT DISTINCT elem
                            FROM jsonb_array_elements(
                                COALESCE(fixed_finding_fingerprints, '[]'::jsonb) || %s::jsonb
                            ) AS elem
                            ORDER BY elem DESC
                            LIMIT 1000
                        ) deduped
                    ),
                    updated_at = NOW()
                    WHERE org_id = %s AND target_domain = %s
                    """,
                    (json.dumps(fps), org_id, domain),
                )

            conn.commit()
            return updated
        except Exception as e:
            logger.error(
                "Failed to batch-mark %d findings as fixed with fps: %s",
                len(finding_ids), e,
            )
            if conn:
                with contextlib.suppress(Exception):
                    conn.rollback()
            return 0
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
