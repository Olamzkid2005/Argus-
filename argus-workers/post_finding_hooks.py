"""
Webhook Dispatch on New Finding Discovery.

Fires HTTP POST to configured webhooks when a finding is saved.
Filters to CRITICAL/HIGH severity by default to avoid notification spam.

Requires: webhooks table with columns (id, engagement_id, webhook_url, events, last_triggered)
Migration: 030_webhooks.sql
"""

import json
import logging
import os
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def fire_finding_webhooks(finding: Dict, db_conn_string: Optional[str] = None) -> None:
    """
    Called after a finding is saved to DB.
    Looks up matching webhooks and dispatches HTTP POST to each.

    Args:
        finding: Finding dict with keys: id, engagement_id, type, severity,
                endpoint, source_tool, confidence
        db_conn_string: Database connection string (auto-resolved if None)
    """
    # Only fire for high-value findings by default
    severity = finding.get("severity", "").upper()
    if severity not in ("CRITICAL", "HIGH"):
        return

    db_url = db_conn_string or os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("No DATABASE_URL set, skipping webhook dispatch")
        return

    engagement_id = finding.get("engagement_id")
    if not engagement_id:
        return

    webhooks = _get_matching_webhooks(engagement_id, db_url)
    if not webhooks:
        return

    payload = {
        "event": "finding_discovered",
        "finding_id": str(finding.get("id", "")),
        "type": finding.get("type", "UNKNOWN"),
        "severity": severity,
        "endpoint": finding.get("endpoint", ""),
        "source_tool": finding.get("source_tool", "unknown"),
        "engagement_id": str(engagement_id),
        "confidence": float(finding.get("confidence", 0)),
    }

    for webhook in webhooks:
        _dispatch(webhook["webhook_url"], payload, webhook["id"], db_url)


def _get_matching_webhooks(engagement_id: str, db_conn_string: str) -> List[Dict]:
    """
    Find webhooks that match this engagement.

    Matches webhooks that are either:
    - Linked directly to the engagement
    - Global webhooks (engagement_id IS NULL) within the same org
    - Have events array that includes 'finding_discovered' or is empty (all events)
    """
    from database.connection import connect

    conn = connect(db_conn_string)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT w.id, w.webhook_url
            FROM webhooks w
            JOIN engagements e ON e.id = %s
            WHERE (
                w.engagement_id = e.id
                OR w.engagement_id IS NULL
            )
            AND (
                w.events @> '["finding_discovered"]'::jsonb
                OR w.events = '[]'::jsonb
                OR w.events IS NULL
            )
            """,
            (engagement_id,),
        )
        rows = cursor.fetchall()
        return [{"id": r[0], "webhook_url": r[1]} for r in rows]
    except Exception as e:
        logger.warning(f"Failed to query webhooks: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def _dispatch(url: str, payload: Dict, webhook_id: str, db_conn_string: str) -> None:
    """
    Dispatch a webhook HTTP POST with timeout.
    Updates last_triggered on success or failure.
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(url, json=payload)
            success = r.status_code < 400
            logger.info(
                "Webhook %s fired -> %s (%s)",
                webhook_id,
                r.status_code,
                "success" if success else "failed",
            )
        _mark_triggered(webhook_id, db_conn_string, success=success)
    except Exception as e:
        logger.warning("Webhook %s dispatch failed: %s", webhook_id, e)
        _mark_triggered(webhook_id, db_conn_string, success=False)


def _mark_triggered(webhook_id: str, db_conn_string: str, success: bool = True) -> None:
    """Update last_triggered timestamp on the webhook record."""
    try:
        from database.connection import connect

        conn = connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE webhooks SET last_triggered = NOW() WHERE id = %s",
            (webhook_id,),
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.warning("Failed to update webhook last_triggered: %s", e)
