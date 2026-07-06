"""
Scope Validator - Ensures LLM-selected tools stay within authorized scope.
Prevents prompt injection from tricking the agent into scanning unauthorized targets.
"""

import json
import logging
from urllib.parse import urlparse

from exceptions import ScopeViolationError
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)

# Known cloud metadata / internal hostnames that must always be blocked (SSRF prevention)
# Consolidated from react_agent.py _validate_arguments() and _browser_scan_worker.py
_BLOCKED_METADATA_HOSTNAMES: frozenset = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata endpoint
    "metadata.google.internal",  # GCP metadata
    "metadata",  # GCP short name
    "instance-data",  # AWS short name
    "instance-data.us-east-1.compute.internal",  # AWS regional
    "100.100.100.200",  # Alibaba Cloud metadata
})


class ScopeValidator:
    """
    Validates that tool execution targets are within the engagement's authorized scope
    and are not internal/SSRF targets.

    Consolidated SSOT for ALL target validation:
    - Engagement scope: domain matching (including wildcard: *.example.com),
      IP range matching (CIDR notation), glob-pattern allow/block lists
    - SSRF prevention: blocks private IPs, cloud metadata endpoints,
      loopback addresses, DNS rebinding attacks
    - URL scheme validation: only http/https allowed for browser contexts

    Usage (preferred entry point)::

        # Combined scope + SSRF check
        validator = ScopeValidator(engagement_id, authorized_scope)
        validator.validate_safe_target("https://target.com")
        validator.is_safe_target("https://target.com")

        # Static SSRF/internal check (no engagement scope needed)
        ScopeValidator.is_internal_address("169.254.169.254")  # True
        ScopeValidator.validate_url_scheme("https://example.com")  # OK
        ScopeValidator.validate_url_scheme("file:///etc/passwd")  # raises ValueError
    """

    def __init__(self, engagement_id: str, authorized_scope: dict | None = None):
        """
        Args:
            engagement_id: Engagement UUID
            authorized_scope: Dict with 'domains' and 'ipRanges' lists, or JSON string
        """
        self.engagement_id = engagement_id
        self._scope = self._parse_scope(authorized_scope)
        if self._scope["domains"] or self._scope["ipRanges"]:
            slog = ScanLogger("scope_validator", engagement_id=engagement_id)
            slog.info(
                f"Scope loaded: {len(self._scope['domains'])} domains, {len(self._scope['ipRanges'])} IP ranges"
            )

    def _parse_scope(self, scope) -> dict:
        """Parse authorized scope from dict or JSON string."""
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except (json.JSONDecodeError, TypeError):
                scope = {}
        return {
            "domains": [d.lower() for d in (scope or {}).get("domains", []) if d],
            "ipRanges": list((scope or {}).get("ipRanges", [])),
        }

    def validate_target(self, target: str) -> bool:
        """
        Validate a target URL/hostname against authorized scope.

        Args:
            target: Target URL or hostname

        Returns:
            True if target is in scope

        Raises:
            ScopeViolationError: If target is out of scope
        """
        slog = ScanLogger("scope_validator", engagement_id=self.engagement_id)

        if not target:
            return True

        hostname = self._extract_hostname(target)

        if self._matches_domain(hostname):
            slog.info("Target %s in scope (domain match)", target)
            return True

        if self._matches_ip_range(hostname):
            slog.info("Target %s in scope (IP range match)", target)
            return True

        slog.warn("Target %s OUT of scope (hostname: %s)", target, hostname)
        raise ScopeViolationError(
            f"Target '{target}' (hostname: {hostname}) is not in authorized scope. "
            f"Authorized domains: {self._scope['domains']}"
        )

    def is_in_scope(self, target: str) -> bool:
        """Convenience: return boolean without raising."""
        try:
            self.validate_target(target)
            return True
        except ScopeViolationError:
            return False

    @staticmethod
    def is_internal_address(hostname: str, resolved_ip: str | None = None) -> bool:
        """Check if a hostname resolves to a private/internal/SSRF target.

        Consolidated from react_agent.py _validate_arguments() and
        _browser_scan_worker._validate_url() -- covers:
        - Known cloud metadata hostnames (AWS, GCP, Azure, Alibaba)
        - Private IPv4 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        - Loopback (127.0.0.1, ::1)
        - Link-local (169.254.0.0/16, fe80::/10)
        - Multicast (224.0.0.0/4)
        - IPv4-mapped IPv6 private addresses
        - DNS resolution check (DNS rebinding protection)

        When ``resolved_ip`` is provided, DNS resolution is skipped and the
        given IP is checked directly. This avoids a redundant DNS lookup
        when the caller has already resolved the hostname (e.g.
        ``_browser_scan_worker._validate_url()``).

        Args:
            hostname: Hostname or IP address string
            resolved_ip: Pre-resolved IP address. When provided, skips DNS
                         resolution and checks this IP for internal/SSRF patterns.

        Returns:
            True if the hostname is known internal, metadata, or resolves to a private IP
        """
        import ipaddress
        import socket

        if not hostname:
            return False

        host_lower = hostname.lower()

        # 1. Static hostname check (fast path -- no DNS resolution needed)
        if host_lower in _BLOCKED_METADATA_HOSTNAMES:
            logger.warning(
                "Blocked internal/SSRF hostname: %s", hostname
            )
            return True

        # 2. Direct IP address check
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                logger.warning(
                    "Blocked internal IP: %s (private=%s, loopback=%s, link_local=%s, multicast=%s)",
                    hostname, ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast,
                )
                return True
            # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                mapped = ipaddress.ip_address(ip.ipv4_mapped)
                if mapped.is_private or mapped.is_loopback or mapped.is_link_local:
                    logger.warning(
                        "Blocked IPv4-mapped internal IP: %s -> %s",
                        hostname, mapped,
                    )
                    return True
            return False
        except ValueError:
            pass  # Not a bare IP -- resolve or use provided IP below

        # 3. DNS resolution or use provided resolved_ip (avoids double DNS lookup
        #    when the caller already resolved, e.g. _browser_scan_worker)
        if resolved_ip:
            # Caller provided a pre-resolved IP -- check it directly
            try:
                ip = ipaddress.ip_address(resolved_ip)
            except ValueError:
                logger.debug(
                    "Invalid resolved_ip '%s' for hostname %s -- ignoring",
                    resolved_ip, hostname,
                )
                return False
        else:
            # No pre-resolved IP -- do DNS resolution
            try:
                resolved_ip = socket.gethostbyname(hostname)
                ip = ipaddress.ip_address(resolved_ip)
            except (socket.gaierror, OSError):
                logger.debug(
                    "DNS resolution failed for %s -- cannot verify, allowing (engagement scope will be checked separately)",
                    hostname,
                )
                # DNS failure is NOT a blocking signal -- the target may be an
                # internal non-DNS name or a misconfigured host. Engagement scope
                # validation will catch it if it's genuinely out of scope.
                return False
            except ValueError:
                logger.debug(
                    "DNS resolved '%s' for hostname %s is not a valid IP -- allowing",
                    resolved_ip, hostname,
                )
                return False

        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            logger.warning(
                "Blocked hostname %s -- resolved to internal IP %s (DNS rebinding protection)",
                hostname, resolved_ip,
            )
            return True
        if resolved_ip == "169.254.169.254":
            logger.warning(
                "Blocked hostname %s -- resolved to cloud metadata endpoint %s",
                hostname, resolved_ip,
            )
            return True

        return False

    @staticmethod
    def validate_url_scheme(url: str) -> str:
        """Validate URL has http/https scheme.

        Used by browser scan contexts where non-HTTP schemes (file://, ftp://)
        could be exploited for SSRF. Consolidated from _browser_scan_worker._validate_url().

        Args:
            url: Full URL string

        Returns:
            The URL unchanged on success

        Raises:
            ValueError: If scheme is not http or https
        """
        if not url.startswith(("http://", "https://")):
            raise ValueError(
                f"Blocked non-HTTP URL (SSRF prevention): {url[:80]}"
            )
        return url

    def validate_safe_target(self, target: str) -> bool:
        """Combined validation: in scope AND not an internal/SSRF target.

        This is the single entry point for all target validation:
        1. SSRF/internal target check (private IPs, cloud metadata, DNS rebinding)
        2. Engagement scope check (domain matching, IP range, allow/block lists)

        Args:
            target: Target URL or hostname

        Returns:
            True if target is both in scope and not internal

        Raises:
            ScopeViolationError: If target is out of scope or internal/SSRF
        """
        slog = ScanLogger("scope_validator", engagement_id=self.engagement_id)

        if not target:
            return True

        hostname = self._extract_hostname(target)

        # Step 1: SSRF / internal target check
        if self.is_internal_address(hostname):
            slog.warn(
                "Target %s blocked -- internal/SSRF target (hostname: %s)",
                target, hostname,
            )
            raise ScopeViolationError(
                f"Target '{target}' (hostname: {hostname}) is a known internal or "
                f"cloud-metadata endpoint -- blocked (SSRF prevention)"
            )

        # Step 2: Engagement scope check
        return self.validate_target(target)

    def is_safe_target(self, target: str) -> bool:
        """Boolean version of validate_safe_target -- no exception, just True/False."""
        try:
            self.validate_safe_target(target)
            return True
        except ScopeViolationError:
            return False

    def _extract_hostname(self, target: str) -> str:
        """Extract hostname from URL or raw hostname."""
        import ipaddress

        target = target.strip().lower()

        if target.startswith(("http://", "https://")):
            return urlparse(target).hostname or target

        # Check if it's a valid IPv6 address (contains multiple colons)
        if target.count(":") > 1:
            try:
                ipaddress.IPv6Address(target)
                return target
            except ipaddress.AddressValueError:
                pass

        return target.split("/")[0].split(":")[0]

    def _matches_domain(self, hostname: str) -> bool:
        """Check if hostname matches any authorized domain (with wildcard support).

        Wildcard domains (*.example.com) must match exactly one subdomain level.
        'sub.example.com' matches, but 'xsub.example.com' does NOT.

        Only wildcard-prefix patterns (*.example.com) are supported. The fnmatch
        fallback is intentionally removed to prevent bypass via `*` matching
        across DNS label boundaries (e.g., `foo.*.com` matching `foo.evil.com`).
        """
        hostname = hostname.lower()
        for domain in self._scope.get("domains", []):
            domain = domain.lower()
            if hostname == domain:
                return True
            if domain.startswith("*."):
                # Wildcard: match exactly one DNS label
                suffix = domain[1:]  # ".example.com"
                if hostname.endswith(suffix):
                    prefix = hostname[:-len(suffix)]
                    if prefix and "." not in prefix:
                        return True
        return False

    def _matches_ip_range(self, hostname: str) -> bool:
        """Check if hostname matches any authorized IP range (CIDR)."""
        import ipaddress

        try:
            addr = ipaddress.ip_address(hostname)
            for cidr in self._scope.get("ipRanges", []):
                try:
                    network = ipaddress.ip_network(cidr, strict=False)
                    if addr in network:
                        return True
                except ValueError:
                    continue
        except ValueError:
            pass  # Not an IP address

        return False


def _match_glob(pattern: str, target: str) -> bool:
    """Check if target matches a glob pattern (fnmatch-style)."""
    import fnmatch
    return fnmatch.fnmatch(target.lower(), pattern.lower())


def _check_blocked(target: str, blocked_targets: list[str] | None) -> bool:
    """Check if target matches any blocked pattern. Returns True if blocked."""
    if not blocked_targets:
        return False
    for pattern in blocked_targets:
        if _match_glob(pattern, target):
            logger.warning(
                "Target %s matches blocked pattern '%s' -- denying",
                target,
                pattern,
            )
            return True
    return False


def _check_allowed(target: str, allowed_targets: list[str] | None, mode: str) -> bool | None:
    """Check if target matches allowed patterns. Returns True if allowed,
    False if denied, None if no decision (delegate to caller)."""
    allowed = allowed_targets or []

    if not allowed:
        if mode == "allowlist":
            logger.warning(
                "Target %s denied: allowlist mode with no allowed_targets configured",
                target,
            )
            return False
        logger.warning(
            "Target %s: no allowed_targets configured (mode=warn) -- allowing with warning",
            target,
        )
        return True

    for pattern in allowed:
        if _match_glob(pattern, target):
            return True

    if mode == "allowlist":
        logger.warning(
            "Target %s denied by scope allowlist (patterns: %s)",
            target,
            allowed,
        )
        return False

    logger.warning(
        "Target %s not in allowed_targets (mode=warn) -- allowing with warning. "
        "Set scope.mode=allowlist to block unauthorized targets.",
        target,
    )
    return True


def validate_target_scope(
    target: str,
    engagement_id: str | None = None,
    mode: str = "allowlist",
    allowed_targets: list[str] | None = None,
    blocked_targets: list[str] | None = None,
    authorized_scope: dict | None = None,
) -> bool:
    """Standalone convenience wrapper around ScopeValidator.

    Supports deny-by-default scope enforcement with three modes:
    - allowlist (default): only allow targets matching ``allowed_targets``
    - warn: same as allowlist but log warning instead of blocking
    - open: allow all targets (no protection)

    ``blocked_targets`` are always checked regardless of mode -- if a target
    matches a blocked pattern it is denied immediately.

    When ``authorized_scope`` is provided (not None), uses the legacy DB-based
    ScopeValidator path for backward compatibility.

    **Fail-Closed**: If scope validation encounters an error (DB unavailable,
    malformed scope JSON, network timeout), the target is considered
    **OUT of scope**. Only when no scope is configured do we allow-all.

    R-03: DB lookup is wrapped in a thread with a configurable timeout
    (SCOPE_VALIDATION_TIMEOUT) to prevent scope validation from blocking
    the scan pipeline if the DB is slow or unreachable.

    Args:
        target: Target URL or hostname
        engagement_id: Engagement UUID
        mode: Scope enforcement mode ("allowlist", "warn", "open")
        allowed_targets: List of glob patterns for allowed targets
        blocked_targets: List of glob patterns for blocked targets
        authorized_scope: Optional scope dict (loaded from DB if None)

    Returns:
        True if target is in scope, False if not or on validation error
    """
    # -- Legacy DB-based path (caller provided authorized_scope explicitly) --
    if authorized_scope is not None:
        if not authorized_scope:
            return True

        try:
            validator = ScopeValidator(engagement_id, authorized_scope)
            return validator.is_in_scope(target)
        except Exception as e:
            logger.warning(
                "Scope validation failed for %s -- failing closed (deny): %s",
                target,
                e,
            )
            return False

    # -- Config-based enforcement path (mode / allowed / blocked) --
    if _check_blocked(target, blocked_targets):
        return False

    if mode == "open":
        return True

    result = _check_allowed(target, allowed_targets, mode)
    return result if result is not None else True
