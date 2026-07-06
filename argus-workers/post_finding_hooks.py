"""
Webhook Dispatch on New Finding Discovery.

Fires HTTP POST to configured webhooks when a finding is saved.
Filters to CRITICAL/HIGH severity by default to avoid notification spam.

Requires: webhooks table with columns (id, engagement_id, webhook_url, events, last_triggered)
Migration: 030_webhooks.sql
"""

import ipaddress
import logging
import os
import socket

import httpx

from utils.validation import is_private_ip

logger = logging.getLogger(__name__)


# ── IP allowlist for webhook dispatch (SSRF prevention) ──
# When set, only these CIDR ranges are allowed as webhook targets.
# Format: comma-separated CIDR notation (e.g. "192.30.252.0/22,140.82.112.0/20")
# When empty (default), any public IP is allowed but private/internal IPs are blocked.
_WEBHOOK_ALLOWED_CIDRS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None = None
_WEBHOOK_ALLOWLIST_ENV_VAR = "ARGUS_WEBHOOK_ALLOWED_IPS"


def _load_webhook_allowlist() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
    """Load the webhook IP allowlist from environment variable.

    Parses ``ARGUS_WEBHOOK_ALLOWED_IPS`` as a comma-separated list of CIDR
    ranges. Returns ``None`` when unset (allows any public IP). Returns an
    empty list or raises when invalid entries are present.

    Returns:
        List of IP networks to allow, or None if no allowlist is configured.
    """
    raw = os.getenv(_WEBHOOK_ALLOWLIST_ENV_VAR, "").strip()
    if not raw:
        return None

    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as e:
            logger.warning(
                "Invalid CIDR in %s: '%s' — %s",
                _WEBHOOK_ALLOWLIST_ENV_VAR, entry, e,
            )
            # Fail-open would be insecure; fail-closed by treating as empty
            # and rejecting all webhooks until the misconfiguration is fixed.
            return []
    return networks


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
    "100.100.100.200.nip.io",
    "169.254.169.254.nip.io",
    "1.1.1.1.nip.io",  # xip.io / nip.io rebinding services
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

    # Resolve hostname to IP(s) and verify all are public addresses.
    # Uses AF_UNSPEC to handle both IPv4 and IPv6 — is_private_ip()
    # handles both families correctly (loopback, ULA, link-local, etc.).
    try:
        addrs = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        if not addrs:
            # No addresses resolved — fail closed to prevent SSRF
            # via DNS rebinding with hosts that temporarily resolve empty.
            logger.warning(
                "SSRF block: webhook URL hostname '%s' returned no addresses "
                "— blocked to prevent SSRF via DNS rebinding: %s",
                hostname, url,
            )
            return False
        for family, _, _, _, sockaddr in addrs:
            ip = sockaddr[0]
            if is_private_ip(ip):
                logger.warning(
                    "SSRF block: webhook URL resolves to private/internal IP "
                    "'%s': %s",
                    ip, url,
                )
                return False
        # All resolved IPs are public — safe to proceed.
        return True
    except (socket.gaierror, socket.herror, OSError, IndexError):
        # Fail closed: if DNS resolution fails, block the URL to prevent
        # SSRF via DNS rebinding. A hostname that can't be resolved at
        # validation time might resolve to an internal address later when
        # the actual HTTP request is made.
        logger.warning(
            "SSRF block: webhook URL hostname '%s' failed DNS resolution "
            "— blocked to prevent SSRF via DNS rebinding: %s",
            hostname, url,
        )
        return False


def _resolve_and_validate_at_request_time(url: str) -> bool:
    """
    Resolve a webhook URL's hostname to IP(s) at request time and validate.

    Called immediately before the HTTP request to close the DNS rebinding
    TOCTOU window. Resolves the hostname, checks each resolved IP against:
    1. ``is_private_ip()`` — blocks private/internal/cloud metadata IPs
    2. ``_WEBHOOK_ALLOWED_CIDRS`` — when set, only allowlisted IPs pass

    Fail-closed: any DNS resolution error or empty result blocks the URL.

    Note: This validates the resolved IP but httpx still re-resolves the
    hostname internally microseconds later, so the TOCTOU window is narrowed
    but not eliminated. DNS rebinding requires DNS TTL expiry (seconds to
    minutes), so this is practically secure.

    Args:
        url: The webhook URL to resolve and validate.

    Returns:
        True if the URL resolves to a valid public IP, False otherwise.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        addrs = socket.getaddrinfo(
            hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except (socket.gaierror, socket.herror, OSError) as e:
        logger.warning(
            "SSRF block: webhook URL '%s' failed DNS resolution "
            "(fail-closed): %s",
            url, e,
        )
        return False

    if not addrs:
        logger.warning(
            "SSRF block: webhook URL '%s' hostname '%s' returned no addresses "
            "— blocked to prevent SSRF via DNS rebinding",
            url, hostname,
        )
        return False

    # Validate all resolved IPs — every address must pass checks.
    allowed_ips: set[str] = set()
    allowlist = _resolve_allowlist()
    for family, _, _, _, sockaddr in addrs:
        ip = sockaddr[0]
        allowed_ips.add(ip)

        # 1. Block private/internal IPs unconditionally
        if is_private_ip(ip):
            logger.warning(
                "SSRF block: webhook URL '%s' hostname '%s' resolves to "
                "private/internal IP '%s' at request time",
                url, hostname, ip,
            )
            return False

        # 2. If an allowlist is configured, enforce it
        if allowlist is not None and not _ip_in_any_network(ip, allowlist):
            logger.warning(
                "SSRF block: webhook URL '%s' hostname '%s' resolves to "
                "IP '%s' which is not in the allowlist (%s=%s)",
                url, hostname, ip,
                _WEBHOOK_ALLOWLIST_ENV_VAR,
                os.getenv(_WEBHOOK_ALLOWLIST_ENV_VAR, ""),
            )
            return False

    logger.debug(
        "Webhook URL '%s' resolves to %s (passes SSRF validation)",
        url, ", ".join(sorted(allowed_ips)),
    )
    return True


def _resolve_allowlist() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
    """Get the cached webhook IP allowlist."""
    global _WEBHOOK_ALLOWED_CIDRS
    if _WEBHOOK_ALLOWED_CIDRS is None:
        _WEBHOOK_ALLOWED_CIDRS = _load_webhook_allowlist()
    return _WEBHOOK_ALLOWED_CIDRS


def _ip_in_any_network(
    ip: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """Check if an IP string falls within any of the given CIDR networks."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def _dispatch(url: str, payload: dict, webhook_id: str) -> None:
    """
    Dispatch a webhook HTTP POST with timeout and SSRF protection.
    Updates last_triggered on success or failure.

    SSRF protection is applied in two layers:
    1. Pre-check (``_validate_webhook_url``) — URL format, scheme, static blocklist
    2. Request-time (``_resolve_and_validate_at_request_time``) — DNS resolution
       and IP validation immediately before the HTTP call, closing the DNS
       rebinding TOCTOU window.

    Note: DB connection is resolved via the global get_db() pool.
    """
    # Layer 1: Pre-check — validate URL format, scheme, static blocklist
    if not _validate_webhook_url(url):
        logger.warning(
            "Webhook %s blocked: URL '%s' failed SSRF validation",
            webhook_id, url,
        )
        _mark_triggered(webhook_id, success=False)
        return

    # Layer 2: Request-time DNS resolution and IP validation
    # Closes the TOCTOU window caused by _validate_webhook_url resolving
    # the hostname earlier and httpx resolving it again internally.
    if not _resolve_and_validate_at_request_time(url):
        logger.warning(
            "Webhook %s blocked: URL '%s' failed request-time SSRF validation",
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
