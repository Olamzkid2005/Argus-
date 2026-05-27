"""
Compliance Posture Scorer - Continuous compliance posture scoring.

Maps findings to regulatory frameworks (OWASP Top 10, PCI DSS, SOC 2)
and computes a composite posture score that evolves as findings are
discovered, fixed, or regressed.

Posture score is 0-100 where:
  100 = fully compliant (no active findings)
  0   = severely non-compliant

Scores are computed per-framework and as a composite across all frameworks.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from compliance_reporting import ComplianceMapper

logger = logging.getLogger(__name__)

# Severity weights used in posture score calculation
SEVERITY_WEIGHTS = {
    "CRITICAL": 10.0,
    "HIGH": 5.0,
    "MEDIUM": 2.0,
    "LOW": 0.5,
    "INFO": 0.1,
}

MAX_PENALTY_PER_FRAMEWORK = 100.0
MIN_POSTURE_SCORE = 0.0


@dataclass
class FrameworkPosture:
    """Posture snapshot for a single compliance framework."""
    framework: str  # "owasp_top10", "pci_dss", "soc2"
    score: float  # 0-100
    total_findings: int
    critical_count: int
    high_count: int
    medium_count: int
    finding_breakdown: dict[str, list[dict]] = field(default_factory=dict)
    """Maps compliance_ref -> list of finding dicts contributing to that ref."""
    computed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class PostureSnapshot:
    """Full posture snapshot for an engagement at a point in time."""
    engagement_id: str
    composite_score: float  # 0-100 average across all frameworks
    frameworks: dict[str, FrameworkPosture] = field(default_factory=dict)
    total_findings: int = 0
    trend: str = "stable"  # "improving", "declining", "stable"
    previous_score: float | None = None
    computed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CompliancePostureScorer:
    """
    Continuously computes compliance posture scores as findings are saved.

    Uses the existing ComplianceMapper for framework mappings and computes
    weighted posture scores that reflect the finding landscape for each
    regulatory framework supported by Argus.
    """

    SUPPORTED_FRAMEWORKS = ["owasp_top10", "pci_dss", "soc2", "nist_csf", "hipaa", "iso_27001"]

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._mapper = ComplianceMapper()
        self._previous_score: float | None = None

    # ── Mapping helpers ──

    def _map_finding(self, finding: dict) -> dict[str, str | None]:
        """Map a finding to all supported compliance frameworks.

        Returns:
            Dict mapping framework name -> compliance reference string.
        """
        finding_type = finding.get("type", "UNKNOWN")
        owasp = self._mapper.map_to_owasp(finding_type)
        pci = self._mapper.map_to_pci(finding_type)
        soc2 = self._mapper.map_to_soc2(finding_type)
        return {
            "owasp_top10": owasp,
            "pci_dss": pci,
            "soc2": soc2,
        }

    def _map_finding_full(self, finding: dict) -> dict[str, str | None]:
        """Map a finding to ALL supported compliance frameworks."""
        finding_type = finding.get("type", "UNKNOWN")
        return {
            "owasp_top10": self._mapper.map_to_owasp(finding_type),
            "pci_dss": self._mapper.map_to_pci(finding_type),
            "soc2": self._mapper.map_to_soc2(finding_type),
            "nist_csf": self._mapper.map_to_nist_csf(finding_type),
            "hipaa": self._mapper.map_to_hipaa(finding_type),
            "iso_27001": self._mapper.map_to_iso_27001(finding_type),
        }

    # ── Score computation ──

    def _compute_framework_score(
        self,
        findings: list[dict],
        mapper_fn,
    ) -> FrameworkPosture:
        """Compute posture score for a single compliance framework.

        Scoring formula:
            base_score = 100
            for each finding:
                penalty = severity_weight * (1.0 / (1.0 + count_of_same_ref))
            final_score = max(0, base_score - total_penalty)

        The penalty for multiple findings in the same compliance ref is
        logarithmically dampened to prevent a single ref from dominating.

        Args:
            findings: All engagement findings.
            mapper_fn: Function that maps a finding type to a compliance ref.

        Returns:
            FrameworkPosture for this framework.
        """
        breakdown: dict[str, list[dict]] = {}
        type_ref_map: dict[str, str] = {}  # cache: finding_type -> ref

        critical = 0
        high = 0
        medium = 0
        total_penalty = 0.0

        # Count findings per compliance ref for dampening
        ref_counts: dict[str, int] = {}

        for f in findings:
            ftype = f.get("type", "UNKNOWN")
            if ftype not in type_ref_map:
                type_ref_map[ftype] = mapper_fn(ftype)
            ref = type_ref_map[ftype]

            if ref not in breakdown:
                breakdown[ref] = []
            breakdown[ref].append(f)
            ref_counts[ref] = ref_counts.get(ref, 0) + 1

            severity = f.get("severity", "INFO")
            if severity == "CRITICAL":
                critical += 1
            elif severity == "HIGH":
                high += 1
            elif severity == "MEDIUM":
                medium += 1

            # Apply dampened penalty: severity_weight / sqrt(ref_count)
            weight = SEVERITY_WEIGHTS.get(severity, 0.1)
            dampener = max(1.0, ref_counts[ref] ** 0.5)
            total_penalty += weight / dampener

        # Cap penalty
        total_penalty = min(total_penalty, MAX_PENALTY_PER_FRAMEWORK)
        score = max(MIN_POSTURE_SCORE, 100.0 - total_penalty)

        return FrameworkPosture(
            framework=self._framework_name(mapper_fn),
            score=round(score, 1),
            total_findings=len(findings),
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            finding_breakdown=breakdown,
        )

    @staticmethod
    def _framework_name(mapper_fn) -> str:
        """Extract framework name from a mapper function."""
        name_map = {
            ComplianceMapper.map_to_owasp: "owasp_top10",
            ComplianceMapper.map_to_pci: "pci_dss",
            ComplianceMapper.map_to_soc2: "soc2",
            ComplianceMapper.map_to_nist_csf: "nist_csf",
            ComplianceMapper.map_to_hipaa: "hipaa",
            ComplianceMapper.map_to_iso_27001: "iso_27001",
        }
        return name_map.get(mapper_fn, "unknown")

    def compute(self, findings: list[dict]) -> PostureSnapshot:
        """Compute a full posture snapshot from a list of findings.

        Args:
            findings: List of finding dicts with at minimum 'type' and 'severity'.

        Returns:
            PostureSnapshot with composite and per-framework scores.
        """
        if not findings:
            snapshot = PostureSnapshot(
                engagement_id=self.engagement_id,
                composite_score=100.0,
                frameworks={
                    fw: FrameworkPosture(
                        framework=fw, score=100.0, total_findings=0,
                        critical_count=0, high_count=0, medium_count=0,
                    )
                    for fw in self.SUPPORTED_FRAMEWORKS
                },
                total_findings=0,
                previous_score=self._previous_score,
            )
            self._update_trend(snapshot)
            return snapshot

        # Compute scores for each framework
        frameworks = {}
        for framework, mapper_fn in [
            ("owasp_top10", ComplianceMapper.map_to_owasp),
            ("pci_dss", ComplianceMapper.map_to_pci),
            ("soc2", ComplianceMapper.map_to_soc2),
            ("nist_csf", ComplianceMapper.map_to_nist_csf),
            ("hipaa", ComplianceMapper.map_to_hipaa),
            ("iso_27001", ComplianceMapper.map_to_iso_27001),
        ]:
            frameworks[framework] = self._compute_framework_score(findings, mapper_fn)

        # Composite score: weighted average across frameworks
        # Equal weight for each framework
        composite = round(
            sum(fw.score for fw in frameworks.values()) / len(frameworks),
            1,
        )

        snapshot = PostureSnapshot(
            engagement_id=self.engagement_id,
            composite_score=composite,
            frameworks=frameworks,
            total_findings=len(findings),
            previous_score=self._previous_score,
        )
        self._update_trend(snapshot)
        self._previous_score = composite
        return snapshot

    def _update_trend(self, snapshot: PostureSnapshot) -> None:
        """Determine trend direction based on score change."""
        if snapshot.previous_score is None:
            snapshot.trend = "stable"
            return

        diff = snapshot.composite_score - snapshot.previous_score
        if diff >= 2.0:
            snapshot.trend = "improving"
        elif diff <= -2.0:
            snapshot.trend = "declining"
        else:
            snapshot.trend = "stable"

    # ── Persistence ──

    @staticmethod
    def get_db_cursor():
        """Get a database cursor for the posture snapshots table."""
        from database.connection import db_cursor
        return db_cursor()

    def save_snapshot(self, snapshot: PostureSnapshot) -> str | None:
        """Persist a posture snapshot to the database.

        Returns:
            The ID of the saved snapshot, or None if persistence failed.
        """
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO compliance_posture_snapshots
                        (engagement_id, composite_score, framework_scores,
                         total_findings, trend, previous_score)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self.engagement_id,
                        snapshot.composite_score,
                        json.dumps({
                            fw: {
                                "score": fp.score,
                                "total_findings": fp.total_findings,
                                "critical_count": fp.critical_count,
                                "high_count": fp.high_count,
                                "medium_count": fp.medium_count,
                                "finding_breakdown": fp.finding_breakdown,
                            }
                            for fw, fp in snapshot.frameworks.items()
                        }),
                        snapshot.total_findings,
                        snapshot.trend,
                        snapshot.previous_score,
                    ),
                )
                row = cursor.fetchone()
                if row:
                    return str(row[0])
                return None
        except Exception as e:
            logger.warning(
                "Failed to save compliance posture snapshot for %s: %s",
                self.engagement_id, e,
            )
            return None

    @staticmethod
    def load_latest_snapshot(engagement_id: str) -> dict | None:
        """Load the most recent posture snapshot for an engagement.

        Args:
            engagement_id: Engagement UUID.

        Returns:
            Snapshot dict or None if no snapshot exists.
        """
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, engagement_id, composite_score, framework_scores,
                           total_findings, trend, previous_score, computed_at
                    FROM compliance_posture_snapshots
                    WHERE engagement_id = %s
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """,
                    (engagement_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                columns = [
                    "id", "engagement_id", "composite_score", "framework_scores",
                    "total_findings", "trend", "previous_score", "computed_at",
                ]
                result = dict(zip(columns, row, strict=False))
                if isinstance(result.get("framework_scores"), str):
                    result["framework_scores"] = json.loads(result["framework_scores"])
                if isinstance(result.get("computed_at"), datetime):
                    result["computed_at"] = result["computed_at"].isoformat()
                return result
        except Exception as e:
            logger.warning(
                "Failed to load compliance posture snapshot for %s: %s",
                engagement_id, e,
            )
            return None

    @staticmethod
    def load_snapshot_history(
        engagement_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Load posture snapshot history for an engagement.

        Args:
            engagement_id: Engagement UUID.
            limit: Max snapshots to return (most recent first).

        Returns:
            List of snapshot dicts in reverse chronological order.
        """
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, engagement_id, composite_score, framework_scores,
                           total_findings, trend, computed_at
                    FROM compliance_posture_snapshots
                    WHERE engagement_id = %s
                    ORDER BY computed_at DESC
                    LIMIT %s
                    """,
                    (engagement_id, limit),
                )
                rows = cursor.fetchall()
                columns = [
                    "id", "engagement_id", "composite_score", "framework_scores",
                    "total_findings", "trend", "computed_at",
                ]
                results = []
                for row in rows:
                    snap = dict(zip(columns, row, strict=False))
                    if isinstance(snap.get("framework_scores"), str):
                        snap["framework_scores"] = json.loads(snap["framework_scores"])
                    if isinstance(snap.get("computed_at"), datetime):
                        snap["computed_at"] = snap["computed_at"].isoformat()
                    results.append(snap)
                return results
        except Exception as e:
            logger.warning(
                "Failed to load posture history for %s: %s",
                engagement_id, e,
            )
            return []

    @staticmethod
    def get_org_posture_summary(org_id: str) -> dict:
        """Get an aggregate posture summary across all engagements in an org.

        Args:
            org_id: Organization UUID.

        Returns:
            Dict with average composite score, total findings by severity,
            and list of worst-performing engagements.
        """
        try:
            from database.connection import db_cursor
            with db_cursor() as cursor:
                # Latest snapshot per engagement
                cursor.execute(
                    """
                    SELECT DISTINCT ON (cps.engagement_id)
                        cps.engagement_id,
                        e.target_url,
                        cps.composite_score,
                        cps.total_findings,
                        cps.trend,
                        cps.computed_at
                    FROM compliance_posture_snapshots cps
                    JOIN engagements e ON cps.engagement_id = e.id
                    WHERE e.org_id = %s
                    ORDER BY cps.engagement_id, cps.computed_at DESC
                    """,
                    (org_id,),
                )
                rows = cursor.fetchall()
                columns = [
                    "engagement_id", "target_url", "composite_score",
                    "total_findings", "trend", "computed_at",
                ]
                engagements = []
                total_score = 0.0
                for row in rows:
                    snap = dict(zip(columns, row, strict=False))
                    if isinstance(snap.get("computed_at"), datetime):
                        snap["computed_at"] = snap["computed_at"].isoformat()
                    engagements.append(snap)
                    total_score += float(snap.get("composite_score", 0))

                avg_score = round(total_score / len(engagements), 1) if engagements else 100.0
                worst = sorted(engagements, key=lambda e: e.get("composite_score", 100))[:5]

                return {
                    "org_id": org_id,
                    "average_composite_score": avg_score,
                    "total_engagements": len(engagements),
                    "engagements": engagements,
                    "worst_performers": worst,
                    "computed_at": datetime.now(UTC).isoformat(),
                }
        except Exception as e:
            logger.warning(
                "Failed to load org posture summary for %s: %s",
                org_id, e,
            )
            return {
                "org_id": org_id,
                "average_composite_score": 100.0,
                "total_engagements": 0,
                "engagements": [],
                "worst_performers": [],
                "error": str(e),
                "computed_at": datetime.now(UTC).isoformat(),
            }

    # ── Per-control tracking ──

    def save_control_scores(
        self,
        snapshot: PostureSnapshot,
        findings: list[dict],
        org_id: str | None = None,
    ) -> int:
        """Persist per-control compliance status to the compliance_scores table.

        Maps each finding to its compliance controls across all supported
        frameworks, then upserts the control-level status. This enables
        drill-down reporting ("your PCI DSS score is 71% because
        Requirement 6.3 is failing").

        Args:
            snapshot: The computed PostureSnapshot.
            findings: List of finding dicts with type, severity.
            org_id: Organization UUID (resolved from engagement if not provided).

        Returns:
            Number of control rows upserted.
        """
        if not findings:
            return 0

        # Resolve org_id from engagement if not provided
        if not org_id:
            try:
                from database.connection import db_cursor
                with db_cursor() as cursor:
                    cursor.execute(
                        "SELECT org_id FROM engagements WHERE id = %s",
                        (self.engagement_id,),
                    )
                    row = cursor.fetchone()
                    if row:
                        org_id = str(row[0])
            except Exception:
                logger.warning("Could not resolve org_id for control scoring")
                return 0

        if not org_id:
            return 0

        saved = 0
        try:
            from database.connection import db_cursor

            # Map: framework -> control_id -> worst_severity, finding_count
            control_map: dict[str, dict[str, dict]] = {}
            for fw_name, mapper_fn in [
                ("owasp_top10", ComplianceMapper.map_to_owasp),
                ("pci_dss", ComplianceMapper.map_to_pci),
                ("soc2", ComplianceMapper.map_to_soc2),
                ("nist_csf", ComplianceMapper.map_to_nist_csf),
                ("hipaa", ComplianceMapper.map_to_hipaa),
                ("iso_27001", ComplianceMapper.map_to_iso_27001),
            ]:
                control_map[fw_name] = {}
                for f in findings:
                    ref = mapper_fn(f.get("type", "UNKNOWN"))
                    if ref not in control_map[fw_name]:
                        control_map[fw_name][ref] = {
                            "worst_severity": "INFO",
                            "count": 0,
                            "last_finding_at": None,
                        }
                    ctrl = control_map[fw_name][ref]
                    sev = f.get("severity", "INFO")
                    severity_order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
                    if severity_order.index(sev) > severity_order.index(ctrl["worst_severity"]):
                        ctrl["worst_severity"] = sev
                    ctrl["count"] += 1
                    ctrl["last_finding_at"] = max(
                        ctrl["last_finding_at"] or "",
                        f.get("discovered_at") or "",
                    )

            # Upsert each control row
            with db_cursor() as cursor:
                for framework, controls in control_map.items():
                    for control_ref, data in controls.items():
                        # Parse control_id and control_name from ref (e.g. "6.5.1 - Injection flaws")
                        parts = control_ref.split(" - ", 1)
                        control_id = parts[0] if parts else control_ref
                        control_name = parts[1] if len(parts) > 1 else control_ref

                        cursor.execute(
                            """
                            INSERT INTO compliance_scores
                                (org_id, engagement_id, framework, control_id, control_name,
                                 status, severity, finding_count, last_finding_at, computed_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (org_id, engagement_id, framework, control_id)
                            DO UPDATE SET
                                status = EXCLUDED.status,
                                severity = EXCLUDED.severity,
                                finding_count = EXCLUDED.finding_count,
                                last_finding_at = EXCLUDED.last_finding_at,
                                computed_at = NOW()
                            """,
                            (
                                org_id,
                                self.engagement_id,
                                framework,
                                control_id,
                                control_name,
                                "failing",  # If a finding maps to it, it's failing
                                data["worst_severity"],
                                data["count"],
                                data["last_finding_at"] or None,
                            ),
                        )
                        saved += 1

                # Also mark controls that had findings before but are now clean as 'compliant'
                # This is handled by the next full scan updating their status.
                # Controls that no findings map to remain at their previous status
                # until explicitly marked 'not_tested'.

            logger.info(
                "Saved %d control-level compliance scores for engagement %s",
                saved, self.engagement_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to save compliance control scores for %s: %s",
                self.engagement_id, e,
            )
        return saved

    # ── Convenience: compute and save in one call ──

    def compute_and_save(self, findings: list[dict], org_id: str | None = None) -> PostureSnapshot:
        """Compute posture snapshot and persist it to the database.

        Also persists per-control scores to the compliance_scores table
        for drill-down reporting.

        Args:
            findings: List of finding dicts.
            org_id: Organization UUID (resolved from engagement if not provided).

        Returns:
            The computed PostureSnapshot.
        """
        snapshot = self.compute(findings)
        self.save_snapshot(snapshot)
        self.save_control_scores(snapshot, findings, org_id)

        # Publish real-time posture update
        try:
            from websocket_events import get_websocket_publisher
            ws = get_websocket_publisher()
            ws.publish_posture_update(
                engagement_id=self.engagement_id,
                composite_score=snapshot.composite_score,
                framework_scores={fw: fp.score for fw, fp in snapshot.frameworks.items()},
                trend=snapshot.trend,
                total_findings=snapshot.total_findings,
            )
        except Exception as e:
            logger.debug("Failed to publish posture update (non-fatal): %s", e)

        return snapshot

    def to_api_dict(self, snapshot: PostureSnapshot) -> dict:
        """Serialize a PostureSnapshot to an API-friendly dict."""
        return {
            "engagement_id": snapshot.engagement_id,
            "composite_score": snapshot.composite_score,
            "trend": snapshot.trend,
            "previous_score": snapshot.previous_score,
            "total_findings": snapshot.total_findings,
            "computed_at": snapshot.computed_at,
            "frameworks": {
                fw: {
                    "framework": fp.framework,
                    "score": fp.score,
                    "total_findings": fp.total_findings,
                    "critical_count": fp.critical_count,
                    "high_count": fp.high_count,
                    "medium_count": fp.medium_count,
                    "finding_breakdown": {
                        ref: [
                            {
                                "id": f.get("_saved_id") or f.get("id", ""),
                                "type": f.get("type", ""),
                                "severity": f.get("severity", ""),
                                "endpoint": f.get("endpoint", ""),
                            }
                            for f in findings
                        ]
                        for ref, findings in fp.finding_breakdown.items()
                    },
                }
                for fw, fp in snapshot.frameworks.items()
            },
        }
