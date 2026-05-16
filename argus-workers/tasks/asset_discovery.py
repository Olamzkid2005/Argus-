"""
Celery task for automatic asset discovery and classification

Requirements: 28.1, 28.2, 28.3, 28.4
"""

import logging
import os

from celery_app import app
from database.connection import connect
from tracing import TracingManager

logger = logging.getLogger(__name__)


@app.task(bind=True, name="tasks.asset_discovery.run_asset_discovery")
def run_asset_discovery(
    self, engagement_id: str, target: str, trace_id: str = None, org_id: str = None
):
    """
    Execute automatic asset discovery for an engagement.

    Discovers domains, IPs, endpoints, and classifies assets by type.

    Args:
        engagement_id: Engagement ID
        target: Primary target URL/domain
        trace_id: Optional trace ID
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Self-resolve org_id from engagement if not already provided
    if org_id is None:
        try:
            from database.connection import db_cursor

            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT org_id FROM engagements WHERE id = %s", (engagement_id,)
                )
                row = cursor.fetchone()
                org_id = str(row[0]) if row else None
        except Exception as e:
            logger.warning(
                "Could not resolve org_id for engagement %s: %s", engagement_id, e
            )

    if not org_id:
        logger.warning(
            "No org_id found for engagement %s, skipping asset discovery", engagement_id
        )
        return {"status": "skipped", "reason": "no_org_id"}

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    with tracing_manager.trace_execution(engagement_id, "asset_discovery", trace_id):
        assets_discovered = []

        conn = None
        cursor = None
        try:
            conn = connect(db_conn_string)
            cursor = conn.cursor()

            # Discover domain asset
            # Use urlparse to safely extract netloc, handling URLs with
            # embedded credentials (user:pass@host), ports, etc.
            from urllib.parse import urlparse
            parsed = urlparse(target)
            domain = parsed.netloc or parsed.path.split("/")[0]
            cursor.execute(
                """
                INSERT INTO assets (org_id, engagement_id, asset_type, identifier, display_name, attributes, lifecycle_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (org_id, engagement_id, "domain", domain, domain, "{}", "active"),
            )
            row = cursor.fetchone()
            if row:
                assets_discovered.append(
                    {"id": row[0], "type": "domain", "identifier": domain}
                )

            # Discover endpoint asset
            if target.startswith("http"):
                cursor.execute(
                    """
                    INSERT INTO assets (org_id, engagement_id, asset_type, identifier, display_name, attributes, lifecycle_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (org_id, engagement_id, "endpoint", target, target, "{}", "active"),
                )
                row = cursor.fetchone()
                if row:
                    assets_discovered.append(
                        {"id": row[0], "type": "endpoint", "identifier": target}
                    )

            # Basic classification: mark web assets
            cursor.execute(
                """
                UPDATE assets
                SET attributes = jsonb_set(COALESCE(attributes, '{}'), '{discovered_by}', '"asset_discovery_task"'),
                    last_scanned_at = NOW()
                WHERE engagement_id = %s
                """,
                (engagement_id,),
            )

            conn.commit()

            return {
                "status": "completed",
                "assets_discovered": len(assets_discovered),
                "assets": assets_discovered,
                "trace_id": trace_id,
            }

        except Exception as e:
            if conn:
                conn.rollback()
            return {
                "status": "failed",
                "error": str(e),
                "trace_id": trace_id,
            }
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


@app.task(bind=True, name="tasks.asset_discovery.update_asset_risk_scores")
def update_asset_risk_scores(self, org_id: str):
    """
    Update risk scores for all assets based on associated findings.

    Uses the same severity-weight methodology as the findings page's
    security rating system:
      CRITICAL → weight 10 (CVSS ~9.5)
      HIGH     → weight 5  (CVSS ~7.5)
      MEDIUM   → weight 2  (CVSS ~5.0)
      LOW      → weight 1  (CVSS ~3.0)
      INFO     → weight 0.25 (CVSS ~0.0)

    The asset risk_score is clamped to 0.00–10.00 scale.

    Args:
        org_id: Organization ID
    """
    db_conn_string = os.getenv("DATABASE_URL")

    # Severity penalty weights — mirrors security-rating.ts
    severity_weights = {
        "CRITICAL": 10.0,
        "HIGH": 5.0,
        "MEDIUM": 2.0,
        "LOW": 1.0,
        "INFO": 0.25,
    }

    # Estimate CVSS per severity — mirrors attack_graph._estimate_cvss
    severity_cvss = {
        "CRITICAL": 9.5,
        "HIGH": 7.5,
        "MEDIUM": 5.0,
        "LOW": 3.0,
        "INFO": 0.0,
    }

    try:
        conn = connect(db_conn_string)
        cursor = conn.cursor()

        # Get all assets with their engagement findings by severity
        cursor.execute(
            """
            SELECT a.id,
                   COUNT(f.id) FILTER (WHERE f.severity = 'CRITICAL') as critical_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'HIGH') as high_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'MEDIUM') as medium_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'LOW') as low_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'INFO') as info_count,
                   COALESCE(MAX(f.cvss_score), 0) as max_cvss
            FROM assets a
            LEFT JOIN engagements e ON a.engagement_id = e.id
            LEFT JOIN findings f ON e.id = f.engagement_id
            WHERE a.org_id = %s
            GROUP BY a.id
            """,
            (org_id,),
        )

        rows = cursor.fetchall()
        scored_count = 0
        for row in rows:
            (
                asset_id,
                critical_count,
                high_count,
                medium_count,
                low_count,
                info_count,
                max_cvss,
            ) = row

            # Use CVSS score if available, otherwise estimate from highest severity
            if max_cvss and max_cvss > 0:
                cvss_based = float(max_cvss)
                # Convert to 0-10 scale if stored as 0-1
                if cvss_based <= 1.0:
                    cvss_based = cvss_based * 10.0
            else:
                # Pick the CVSS equivalent of the highest severity present
                if critical_count > 0:
                    cvss_based = severity_cvss["CRITICAL"]
                elif high_count > 0:
                    cvss_based = severity_cvss["HIGH"]
                elif medium_count > 0:
                    cvss_based = severity_cvss["MEDIUM"]
                elif low_count > 0:
                    cvss_based = severity_cvss["LOW"]
                else:
                    cvss_based = severity_cvss["INFO"]

            # Apply severity-weight penalty (same method as security-rating.ts)
            total_weight = (
                critical_count * severity_weights["CRITICAL"]
                + high_count * severity_weights["HIGH"]
                + medium_count * severity_weights["MEDIUM"]
                + low_count * severity_weights["LOW"]
                + info_count * severity_weights["INFO"]
            )

            # Final score blends CVSS base with volume penalty, clamped to 0–10
            risk_score = round(
                min(10.0, max(0.0, cvss_based + (total_weight * 0.05))), 2
            )

            risk_level = "LOW"
            if risk_score >= 7.0:
                risk_level = "CRITICAL"
            elif risk_score >= 5.0:
                risk_level = "HIGH"
            elif risk_score >= 2.0:
                risk_level = "MEDIUM"

            cursor.execute(
                """
                UPDATE assets
                SET risk_score = %s, risk_level = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (risk_score, risk_level, asset_id),
            )
            scored_count += 1

        conn.commit()
        cursor.close()
        conn.close()

        return {"status": "completed", "assets_scored": scored_count}

    except Exception as e:
        return {"status": "failed", "error": str(e)}
