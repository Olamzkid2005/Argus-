"""
Celery task for automatic asset discovery and classification

Requirements: 28.1, 28.2, 28.3, 28.4
"""
from celery_app import app
import psycopg2
from database.connection import connect

from loader import load_module

_tracing = load_module("tracing")
TracingManager = _tracing.TracingManager

import psycopg2
from database.connection import connect


@app.task(bind=True, name="tasks.asset_discovery.run_asset_discovery")
def run_asset_discovery(self, engagement_id: str, target: str, org_id: str, trace_id: str = None):
    """
    Execute automatic asset discovery for an engagement.
    
    Discovers domains, IPs, endpoints, and classifies assets by type.
    
    Args:
        engagement_id: Engagement ID
        target: Primary target URL/domain
        org_id: Organization ID
        trace_id: Optional trace ID
    """
    db_conn_string = os.getenv("DATABASE_URL")
    
    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()
    
    with tracing_manager.trace_execution(engagement_id, "asset_discovery", trace_id):
        assets_discovered = []
        
        try:
            conn = connect(db_conn_string)
            cursor = conn.cursor()
            
            # Discover domain asset
            domain = target.replace("https://", "").replace("http://", "").split("/")[0]
            cursor.execute(
                """
                INSERT INTO assets (org_id, engagement_id, asset_type, identifier, display_name, attributes, lifecycle_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (org_id, engagement_id, "domain", domain, domain, "{}", "active")
            )
            row = cursor.fetchone()
            if row:
                assets_discovered.append({"id": row[0], "type": "domain", "identifier": domain})
            
            # Discover endpoint asset
            if target.startswith("http"):
                cursor.execute(
                    """
                    INSERT INTO assets (org_id, engagement_id, asset_type, identifier, display_name, attributes, lifecycle_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (org_id, engagement_id, "endpoint", target, target, "{}", "active")
                )
                row = cursor.fetchone()
                if row:
                    assets_discovered.append({"id": row[0], "type": "endpoint", "identifier": target})
            
            # Basic classification: mark web assets
            cursor.execute(
                """
                UPDATE assets
                SET attributes = jsonb_set(COALESCE(attributes, '{}'), '{discovered_by}', '"asset_discovery_task"'),
                    last_scanned_at = NOW()
                WHERE engagement_id = %s
                """,
                (engagement_id,)
            )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            return {
                "status": "completed",
                "assets_discovered": len(assets_discovered),
                "assets": assets_discovered,
                "trace_id": trace_id,
            }
            
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
                "trace_id": trace_id,
            }


@app.task(bind=True, name="tasks.asset_discovery.update_asset_risk_scores")
def update_asset_risk_scores(self, org_id: str):
    """
    Update risk scores for all assets based on associated findings.
    
    Args:
        org_id: Organization ID
    """
    db_conn_string = os.getenv("DATABASE_URL")
    
    try:
        conn = connect(db_conn_string)
        cursor = conn.cursor()
        
        # Get all assets with their engagement findings
        cursor.execute(
            """
            SELECT a.id, a.asset_type, a.identifier,
                   COUNT(f.id) as finding_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'CRITICAL') as critical_count,
                   COUNT(f.id) FILTER (WHERE f.severity = 'HIGH') as high_count
            FROM assets a
            LEFT JOIN engagements e ON a.engagement_id = e.id
            LEFT JOIN findings f ON e.id = f.engagement_id
            WHERE a.org_id = %s
            GROUP BY a.id
            """,
            (org_id,)
        )
        
        rows = cursor.fetchall()
        for row in rows:
            asset_id, asset_type, identifier, finding_count, critical_count, high_count = row
            
            # Simple risk scoring formula
            risk_score = min(10.0, (critical_count * 3.0) + (high_count * 1.5) + (finding_count * 0.1))
            
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
                (risk_score, risk_level, asset_id)
            )
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return {"status": "completed", "assets_scored": len(rows)}
        
    except Exception as e:
        return {"status": "failed", "error": str(e)}
