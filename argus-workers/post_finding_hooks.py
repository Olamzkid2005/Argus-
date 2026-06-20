"""
Webhook Dispatch on New Finding Discovery.

Fires HTTP POST to configured webhooks when a finding is saved.
Filters to CRITICAL/HIGH severity by default to avoid notification spam.

Requires: webhooks table with columns (id, engagement_id, webhook_url, events, last_triggered)
Migration: 030_webhooks.sql
"""

import logging
import socket

import httpx

from utils.validation import is_private_ip

logger = logging.getLogger(__name__)


def fire_finding_webhooks(finding: dict, db_conn_string: str | None = None) -> None:
    """
    Called after a finding is saved to DB.
    Looks up matching webhooks and dispatches HTTP POST to each.

    Args:
        finding: Finding dict with keys: id, engagement_id, type, severity,
                endpoint, source_tool, confidence
        db_conn_string: Deprecated — no longer used. Internal functions resolve
                        the database URL from the environment via get_db().
    """
    # Only fire for high-value findings by default
    severity = finding.get("severity", "").upper()
    if severity not in ("CRITICAL", "HIGH"):
        return

    engagement_id = finding.get("engagement_id")
    if not engagement_id:
        return

    webhooks = _get_matching_webhooks(engagement_id)
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
        _dispatch(webhook["webhook_url"], payload, webhook["id"])


def _get_matching_webhooks(engagement_id: str) -> list[dict]:
    """
    Find webhooks that match this engagement.

    Matches webhooks that are either:
    - Linked directly to the engagement
    - Global webhooks (engagement_id IS NULL) within the same org
    - Have events array that includes 'finding_discovered' or is empty (all events)

    Uses the global connection pool (get_db()) — does not accept a custom
    connection string because all internal DB calls resolve from the env.
    """
    from database.connection import get_db

    conn = None
    cursor = None
    try:
        # Use connection pool to avoid max_connection exhaustion
        conn = get_db().get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT w.id, w.webhook_url
            FROM webhooks w
            JOIN engagements e ON e.id = %s
            WHERE (
                w.engagement_id = e.id
                OR (w.engagement_id IS NULL AND (w.org_id = e.org_id OR w.org_id IS NULL))
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
        logger.warning("Failed to query webhooks: %s", e)
        return []
    finally:
        if cursor:
            cursor.close()
        if conn:
            get_db().release_connection(conn)


# SSRF validation: block webhook URLs pointing to private/internal networks
_SSRF_BLOCKED_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "[::1]",
    "[::]",
    "169.254.169.254",  # cloud metadata endpoint
    "metadata.google.internal",
    "169.254.170.2",  # AWS ECS container metadata
    "100.100.100.200",  # Alibaba Cloud metadata
})
_SSRF_ALLOWED_SCHEMES = frozenset({"https"})


def _validate_webhook_url(url: str) -> bool:
    """
    Validate that a webhook URL is safe (no SSRF).

    Performs both static hostname checks and DNS resolution to prevent
    DNS rebinding attacks. Resolved IPs are checked via the shared
    is_private_ip() which handles:
    - IPv4 private ranges (RFC 1918, CGNAT, loopback, link-local)
    - IPv6 private ranges (ULA fc00::/7, link-local fe80::/10, loopback)
    - IPv4-mapped IPv6 addresses (::ffff:x.x.x.x)
    - Cloud metadata endpoints (169.254.x.x, 100.100.x.x)
    - Documentation/benchmarking ranges

    Only allows HTTPS scheme.

    Returns True if the URL is safe, False if it should be blocked.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Only allow HTTPS
    if parsed.scheme not in _SSRF_ALLOWED_SCHEMES:
        logger.warning("SSRF block: webhook URL uses disallowed scheme '%s': %s", parsed.scheme, url)
        return False

    # Check hostname against static blocklist
    hostname = (parsed.hostname or "").lower()
    if hostname in _SSRF_BLOCKED_HOSTS:
        logger.warning("SSRF block: webhook URL points to blocked host: %s", url)
        return False

    # If hostname is already an IP literal, check it directly
    try:
        ip = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)[0][4][0]
        if is_private_ip(ip):
            logger.warning(
                "SSRF block: webhook URL resolves to private/internal IP '%s': %s",
                ip, url,
            )
            return False
        return True
    except (socket.gaierror, OSError, IndexError):
        # Hostname that didn't resolve — still allow it (may be transient).
        # The static blocklist already caught known-bad names above.
        return True


def _dispatch(url: str, payload: dict, webhook_id: str) -> None:
    """
    Dispatch a webhook HTTP POST with timeout and SSRF protection.
    Updates last_triggered on success or failure.

    Note: DB connection is resolved via the global get_db() pool.
    """
    # SSRF guard: reject URLs pointing to private/internal networks
    if not _validate_webhook_url(url):
        logger.warning(
            "Webhook %s blocked: URL '%s' failed SSRF validation",
            webhook_id, url,
        )
        _mark_triggered(webhook_id, success=False)
        return

    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            r = client.post(url, json=payload)
            success = r.status_code < 400
            logger.info(
                "Webhook %s fired -> %s (%s)",
                webhook_id,
                r.status_code,
                "success" if success else "failed",
            )
        _mark_triggered(webhook_id, success=success)
    except Exception as e:
        logger.warning("Webhook %s dispatch failed: %s", webhook_id, e)
        _mark_triggered(webhook_id, success=False)


def _mark_triggered(webhook_id: str, success: bool = True) -> None:
    """Update last_triggered timestamp on the webhook record.

    Uses the global get_db() pool — no custom connection string needed.
    """
    conn = None
    cursor = None
    try:
        from database.connection import get_db

        conn = get_db().get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE webhooks SET last_triggered = NOW() WHERE id = %s",
            (webhook_id,),
        )
        conn.commit()
    except Exception as e:
        logger.warning("Failed to update webhook last_triggered: %s", e)
    finally:
        if cursor:
            cursor.close()
        if conn:
            get_db().release_connection(conn)
