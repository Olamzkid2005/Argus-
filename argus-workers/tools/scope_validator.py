"""
Scope Validator - Ensures LLM-selected tools stay within authorized scope.
Prevents prompt injection from tricking the agent into scanning unauthorized targets.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from exceptions import ScopeViolationError
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


def _log_internal_target(hostname: str, detail: str) -> None:
    """Note an internal/SSRF target on the way to a decision.

    ``is_internal_address`` is a classifier. It is called both by the guards
    that block a target and by callers that permit one — an authorized target
    with ``ARGUS_ALLOW_INTERNAL_TARGETS`` set — so announcing "Blocked ..."
    here claimed a decision the caller had not made yet. Measured: a local run
    logged "Blocked internal/SSRF hostname: 127.0.0.1" three times and then
    scanned the target successfully. Every caller that really blocks a target
    logs its own warning with the reason.
    """
    logger.debug("Internal/SSRF target: %s (%s)", hostname, detail)


# Known cloud metadata / internal hostnames that must always be blocked (SSRF prevention)
# Consolidated from react_agent.py _validate_arguments() and _browser_scan_worker.py
_BLOCKED_METADATA_HOSTNAMES: frozenset = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "::",  # IPv6 unspecified address
    "0.0.0.0",
    "169.254.169.254",  # AWS metadata endpoint
    "metadata.google.internal",  # GCP metadata
    "metadata",  # GCP short name
    "instance-data",  # AWS short name
    "instance-data.us-east-1.compute.internal",  # AWS regional
    "100.100.100.200",  # Alibaba Cloud metadata
})

# Genuine cloud metadata services. These are never legitimate scan targets and
# stay blocked even when the operator explicitly opts in to internal targets
# (ARGUS_ALLOW_INTERNAL_TARGETS). Loopback and RFC1918 addresses are deliberately
# NOT in this set: they are internal-but-scannable lab/staging targets, gated
# separately by ScopeValidator.is_blocked_internal_target().
_ALWAYS_BLOCKED_METADATA_HOSTNAMES: frozenset = frozenset({
    "169.254.169.254",  # AWS/GCP/Azure IMDS
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
        validator = ScopeValidator(engagement_id or "", authorized_scope)
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
        self._unscoped_allowed = os.environ.get("ARGUS_ALLOW_UNSCOPED", "").lower() in ("1", "true")
        self._slog = ScanLogger("scope_validator", engagement_id=engagement_id)
        if self._scope["domains"] or self._scope["ipRanges"]:
            self._slog.info(
                f"Scope loaded: {len(self._scope['domains'])} domains, {len(self._scope['ipRanges'])} IP ranges"
            )
        else:
            if not self._unscoped_allowed:
                self._slog.warn(
                    "NO SCOPE CONFIGURED — ALL TARGETS WILL BE REJECTED. "
                    "To allow scanning without a scope, set ARGUS_ALLOW_UNSCOPED=1 or "
                    "configure 'authorized_scope' in the engagement configuration."
                )
            else:
                self._slog.warn(
                    "NO SCOPE CONFIGURED — all targets allowed (ARGUS_ALLOW_UNSCOPED=1). "
                    "This is acceptable only for development/testing. "
                    "For production, set 'authorized_scope' with domains/IP ranges."
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

        # Fail-closed: if no scope is configured and ARGUS_ALLOW_UNSCOPED is not set,
        # reject all targets. This prevents accidental scanning of unauthorized targets
        # when scope configuration is missing.
        if not self._scope["domains"] and not self._scope["ipRanges"]:
            if self._unscoped_allowed:
                slog.info("Target %s allowed (unscoped mode via ARGUS_ALLOW_UNSCOPED=1)", target)
                return True
            slog.warn(
                "Target %s REJECTED — no scope configured. "
                "Set authorized_scope or ARGUS_ALLOW_UNSCOPED=1 to proceed.",
                target,
            )
            raise ScopeViolationError(
                f"Target '{target}' rejected: no authorized_scope configured. "
                f"Set authorized_scope in engagement config or "
                f"ARGUS_ALLOW_UNSCOPED=1 env var to allow unscoped scanning."
            )

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
    def _is_additional_blocked_ip(ip_str: str) -> bool:
        """Check additional IP ranges not covered by `ipaddress` properties.

        Python 3.10's ``ipaddress`` module does not flag CGNAT (RFC 6598,
        100.64.0.0/10) or benchmarking (RFC 2544, 198.18.0.0/15) as private.
        These ranges should still be blocked for SSRF prevention (fail-closed).
        Consolidated from the former ``utils/validation.py:is_private_ip()``
        which had hand-rolled checks for these ranges.

        Args:
            ip_str: Bare IP address string (IPv4 or IPv6)

        Returns:
            True if the IP is in a blocked range that ``ipaddress`` misses
        """
        import ipaddress

        try:
            ip = ipaddress.ip_address(ip_str)
            if isinstance(ip, ipaddress.IPv4Address):
                octets = str(ip).split(".")
                if len(octets) == 4:
                    # CGNAT (RFC 6598): 100.64.0.0/10
                    if octets[0] == "100" and 64 <= int(octets[1]) <= 127:
                        return True
                    # Benchmarking (RFC 2544): 198.18.0.0/15
                    if octets[0] == "198" and octets[1] in ("18", "19"):
                        return True
        except ValueError:
            pass
        return False

    @staticmethod
    def internal_targets_opt_in() -> bool:
        """True when the operator explicitly opted in to scanning internal targets.

        Read from ``ARGUS_ALLOW_INTERNAL_TARGETS`` (default off) — following the
        same explicit-opt-in convention as ``ARGUS_ALLOW_UNSCOPED``.
        """
        return os.environ.get("ARGUS_ALLOW_INTERNAL_TARGETS", "").lower() in (
            "1",
            "true",
        )

    @staticmethod
    def is_always_blocked_target(
        hostname: str, resolved_ip: str | None = None
    ) -> bool:
        """Cloud metadata / link-local target — blocked under every configuration.

        Unlike private and loopback ranges, cloud metadata services are not
        legitimate scan targets in any engagement, so the internal-target opt-in
        does not apply to them.
        """
        host = (hostname or "").lower().strip()
        if not host:
            return False
        if host in _ALWAYS_BLOCKED_METADATA_HOSTNAMES:
            return True

        # Link-local (169.254.0.0/16, fe80::/10) hosts the IMDS range too.
        import ipaddress

        for candidate in (resolved_ip, host):
            if not candidate:
                continue
            try:
                if ipaddress.ip_address(candidate).is_link_local:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def is_blocked_internal_target(
        hostname: str,
        resolved_ip: str | None = None,
        authorized: bool = False,
    ) -> bool:
        """Decide whether an internal address must block a scan target.

        Internal targets (loopback, RFC1918, CGNAT) remain blocked by default as
        SSRF defense. They are permitted only when **both** conditions hold:

        1. the operator opted in via ``ARGUS_ALLOW_INTERNAL_TARGETS``, and
        2. ``authorized`` is True — i.e. the caller established that the target is
           explicitly listed in the engagement's authorized scope.

        Cloud metadata / link-local targets are always blocked (see
        ``is_always_blocked_target``).

        Args:
            hostname: Hostname or IP being considered.
            resolved_ip: Pre-resolved IP, when the caller already has it.
            authorized: Whether the target is explicitly authorized in scope.

        Returns:
            True if the target must be blocked.
        """
        if not ScopeValidator.is_internal_address(hostname, resolved_ip):
            return False
        if ScopeValidator.is_always_blocked_target(hostname, resolved_ip):
            return True
        return not (authorized and ScopeValidator.internal_targets_opt_in())

    @staticmethod
    def is_internal_address(hostname: str, resolved_ip: str | None = None) -> bool:
        """Check if a hostname resolves to a private/internal/SSRF target.

        Consolidated from react_agent.py _validate_arguments() and
        _browser_scan_worker._validate_url() -- covers:
        - Known cloud metadata hostnames (AWS, GCP, Azure, Alibaba)
        - Private IPv4 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        - CGNAT (100.64.0.0/10, RFC 6598)
        - Benchmarking (198.18.0.0/15, RFC 2544)
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
            _log_internal_target(hostname, "metadata hostname")
            return True

        # 2. Direct IP address check
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                _log_internal_target(
                    hostname,
                    f"private={ip.is_private} loopback={ip.is_loopback} "
                    f"link_local={ip.is_link_local} multicast={ip.is_multicast}",
                )
                return True
            # Check additional ranges not covered by ipaddress module (CGNAT, benchmarking)
            if ScopeValidator._is_additional_blocked_ip(hostname):
                _log_internal_target(hostname, "CGNAT/benchmarking range")
                return True
            # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                mapped = ipaddress.ip_address(ip.ipv4_mapped)
                if mapped.is_private or mapped.is_loopback or mapped.is_link_local:
                    _log_internal_target(hostname, f"IPv4-mapped {mapped}")
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

            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                _log_internal_target(
                    hostname, f"resolved to internal IP {resolved_ip}"
                )
                return True
            # Check additional ranges not covered by ipaddress module
            if ScopeValidator._is_additional_blocked_ip(resolved_ip):
                _log_internal_target(
                    hostname, f"resolved to CGNAT/benchmarking IP {resolved_ip}"
                )
                return True
            if resolved_ip == "169.254.169.254":
                _log_internal_target(
                    hostname, f"resolved to cloud metadata endpoint {resolved_ip}"
                )
                return True
            return False
        else:
            # No pre-resolved IP -- do DNS resolution via getaddrinfo so we
            # check all resolved addresses (IPv4 + IPv6), matching the original
            # _is_private_ip behavior in web_scanner.py.
            try:
                addrs = socket.getaddrinfo(hostname, None)
            except (socket.gaierror, OSError):
                logger.debug(
                    "DNS resolution failed for %s -- cannot verify, allowing (engagement scope will be checked separately)",
                    hostname,
                )
                return False

            for family, _, _, _, sockaddr in addrs:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                        _log_internal_target(
                            hostname, f"resolved to internal IP {ip_str}"
                        )
                        return True
                    # Check additional ranges not covered by ipaddress module
                    if ScopeValidator._is_additional_blocked_ip(ip_str):
                        _log_internal_target(
                            hostname, f"resolved to CGNAT/benchmarking IP {ip_str}"
                        )
                        return True
                    # Check IPv4-mapped IPv6 addresses (e.g. ::ffff:10.0.0.1)
                    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                        mapped = ipaddress.ip_address(ip.ipv4_mapped)
                        if mapped.is_private or mapped.is_loopback or mapped.is_link_local:
                            _log_internal_target(
                                hostname, f"resolved to IPv4-mapped {ip_str} -> {mapped}"
                            )
                            return True
                except ValueError:
                    continue
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
        from urllib.parse import urlparse

        hostname = hostname.lower()
        for domain in self._scope.get("domains", []):
            domain = str(domain).strip().lower()
            # The job schema and the harness allow an exact origin as a scope
            # entry; comparing it as a literal hostname rejected the run's own
            # target. Typed origin permissions are enforced by
            # _target_authorized_by on the destination path.
            if "://" in domain:
                domain = urlparse(domain).hostname or ""
            if not domain:
                continue
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


# ── Parsed targets and typed permissions ─────────────────────────────
#
# Authorization used to be decided by string comparison: a target was
# authorized when an allowed pattern was a prefix of it (``startswith(pattern
# + "/")``), or when its hostname equalled the host of an allowed URL. Both
# tests are textual, and both cross an authorization boundary — a prefix test
# ignores scheme and port, and the derived bare host let one host:port
# permission authorize every other port on that host. Parsing the target once
# and asking a typed permission about its components (scheme, host, port,
# path) removes both, because nothing is compared as a string any more.

_MAX_PORT = 65535
_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-._")


class TargetParseError(ValueError):
    """Target cannot be authorized: malformed, scheme-less, or unsupported."""


@dataclass(frozen=True)
class ParsedTarget:
    """A target reduced to the parts authorization compares."""

    hostname: str
    scheme: str = ""
    port: int | None = None
    path: str = "/"
    url: str | None = None
    host_form: bool = False

    @property
    def request_target(self) -> str:
        """The normalized target handed to the scope checks."""
        if self.url:
            return self.url
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return f"{host}:{self.port}" if self.port is not None else host


def _valid_hostname(host: str) -> bool:
    """Whether a parsed host is a plausible DNS name or IP literal."""
    if not host or len(host) > 253:
        return False
    if ":" in host:  # IPv6 literal
        import ipaddress

        try:
            ipaddress.IPv6Address(host)
            return True
        except ValueError:
            return False
    if not set(host) <= _NAME_CHARS:
        return False
    return all(
        label and not label.startswith("-") and not label.endswith("-")
        for label in host.split(".")
    )


def parse_target(
    raw: str, base_url: str | None = None, require_http_scheme: bool = True
) -> ParsedTarget:
    """Parse a CLI target argument, a discovered URL, or a redirect Location.

    One parser for every target shape the pipeline handles, so no caller has to
    invent its own comparison. A relative reference is resolved against
    ``base_url`` first (redirect ``Location`` headers), and everything else is
    validated rather than interpreted leniently.

    Raises:
        TargetParseError: empty input, whitespace or control characters, an
        unsupported scheme, a missing or malformed host, an out-of-range port,
        or a scheme-less value that is more than ``host[:port]``
        (``example.com/path`` cannot be authorized: its scheme is unknown).
    """
    if not isinstance(raw, str):
        raise TargetParseError(f"target must be a string, got {type(raw).__name__}")
    text = raw.strip()
    if not text:
        raise TargetParseError("empty target")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise TargetParseError(
            f"target contains control characters: {text[:80]!r}"
        )
    if "://" not in text and any(ch.isspace() for ch in text):
        raise TargetParseError(
            f"scheme-less target contains whitespace: {text[:80]!r}"
        )
    if "\\" in text:
        raise TargetParseError(f"target contains a backslash: {text[:80]!r}")

    if base_url and "://" not in text:
        text = urljoin(base_url, text)

    if "://" in text:
        parsed = urlparse(text)
        scheme = (parsed.scheme or "").lower()
        if require_http_scheme and scheme not in ("http", "https"):
            raise TargetParseError(f"unsupported URL scheme {scheme!r}")
        if not scheme:
            raise TargetParseError(f"missing URL scheme: {text[:80]!r}")
        if parsed.username or parsed.password:
            raise TargetParseError("targets carrying credentials are not authorized")
        host = (parsed.hostname or "").rstrip(".").lower()
        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise TargetParseError(f"invalid port in {text[:80]!r}") from exc
        if not _valid_hostname(host):
            raise TargetParseError(f"invalid host {host!r} in {text[:80]!r}")
        if explicit_port is not None and not (0 < explicit_port <= _MAX_PORT):
            raise TargetParseError(f"port out of range in {text[:80]!r}")
        default_port = 443 if scheme == "https" else 80
        port = explicit_port if explicit_port is not None else (
            default_port if scheme in ("http", "https") else None
        )
        path = parsed.path or "/"
        host_for_url = f"[{host}]" if ":" in host else host
        netloc = host_for_url if explicit_port is None else f"{host_for_url}:{explicit_port}"
        url = f"{scheme}://{netloc}{path}"
        if parsed.query:
            url = f"{url}?{parsed.query}"
        return ParsedTarget(
            hostname=host, scheme=scheme, port=port, path=path, url=url
        )

    # Host form: what a port scanner or a bare CLI target looks like.
    if any(ch in text for ch in "/?#@"):
        raise TargetParseError(
            f"scheme-less target with a path or query is not valid: {text[:80]!r}"
        )
    if text.startswith("["):
        end = text.find("]")
        if end == -1:
            raise TargetParseError(f"unterminated IPv6 literal: {text[:80]!r}")
        host = text[1:end].lower()
        remainder = text[end + 1 :]
        if remainder and not remainder.startswith(":"):
            raise TargetParseError(f"invalid port in {text[:80]!r}")
        port_text = remainder[1:] if remainder else ""
    else:
        host, _, port_text = text.partition(":")
        host = host.rstrip(".").lower()
    if not _valid_hostname(host):
        raise TargetParseError(f"invalid host {host!r} in {text[:80]!r}")
    if port_text:
        if not port_text.isdigit() or not (0 < int(port_text) <= _MAX_PORT):
            raise TargetParseError(f"invalid port {port_text!r} in {text[:80]!r}")
        port = int(port_text)
    else:
        port = None
    return ParsedTarget(hostname=host, port=port, host_form=True)


@dataclass(frozen=True)
class TargetPermission:
    """One authorized scope entry, interpreted as the kind of grant it states."""

    kind: str  # "origin" | "host" | "path"
    hostname: str
    scheme: str | None = None
    port: int | None = None
    path: str = "/"
    pattern: str = ""


def parse_scope_entry(entry: str) -> TargetPermission | None:
    """Interpret one allowed scope entry, or None when it is an explicit glob.

    ``None`` means the operator wrote a wildcard pattern (``*example.com*``);
    the caller applies it as a glob, which is an explicit statement of intent
    rather than an incidental substring test on a parsed target.
    """
    text = str(entry or "").strip()
    if not text:
        return None
    if text.startswith("*.") and "://" not in text:
        host = text[2:].rstrip(".").lower()
        if not host or "*" in host or "?" in host:
            return None
        return TargetPermission(
            kind="host", hostname=f"*.{host}", pattern=text
        )
    if "*" in text or "?" in text or "[" in text:
        return None
    try:
        parsed = parse_target(text, require_http_scheme=False)
    except TargetParseError:
        return None
    if parsed.host_form:
        return TargetPermission(
            kind="host", hostname=parsed.hostname, port=parsed.port, pattern=text
        )
    after_scheme = text.split("://", 1)[1]
    slash = after_scheme.find("/")
    path = after_scheme[slash:] if slash != -1 else ""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if path and path != "/":
        return TargetPermission(
            kind="path",
            hostname=parsed.hostname,
            scheme=parsed.scheme,
            port=parsed.port,
            path=path,
            pattern=text,
        )
    return TargetPermission(
        kind="origin",
        hostname=parsed.hostname,
        scheme=parsed.scheme,
        port=parsed.port,
        pattern=text,
    )


def _host_matches_permission(permission_host: str, hostname: str) -> bool:
    """Exact host, or exactly one DNS label for a ``*.example.com`` entry."""
    if permission_host == hostname:
        return True
    if permission_host.startswith("*."):
        suffix = permission_host[1:]
        if hostname.endswith(suffix):
            prefix = hostname[: -len(suffix)]
            return bool(prefix) and "." not in prefix
    return False


def permission_authorizes(permission: TargetPermission, target: ParsedTarget) -> bool:
    """Whether one typed permission authorizes one parsed target.

    * **origin** (``https://example.com``, ``https://example.com:8443``) grants
      scheme + host + port for any path. It does not grant another scheme,
      another port, or a sibling origin such as ``https://api.example.com``.
    * **host** (``example.com``, ``example.com:8443``, ``*.example.com``) grants
      that host for any scheme and any path, restricted to the stated port when
      one is given.
    * **path** (``https://example.com/app``) grants the origin plus that path on
      a segment boundary: ``/app/x`` matches, ``/application`` does not.
    """
    if not _host_matches_permission(permission.hostname, target.hostname):
        return False
    if permission.kind == "host":
        return not (
            permission.port is not None
            and target.port is not None
            and permission.port != target.port
        )

    # Origin and path permissions name exactly one origin.
    if target.scheme and target.scheme != permission.scheme:
        return False
    if target.port is None:
        # Deliberate, pinned exception: a port scanner is handed a bare host
        # rather than a URL, so it cannot name a port to compare. The entry's
        # port is inherited rather than treated as "any port", and
        # ``authorize_target`` reports it as ``inherited_port`` so the caller
        # uses that port instead of choosing its own; a target that names any
        # port must still match the entry exactly (checked just below).
        # Without this the earlier measured behaviour returns: sqlmap-style
        # URLs, ffuf and every port scanner were skipped in an authorized run.
        return permission.kind == "origin"
    if target.port != permission.port:
        return False
    if permission.kind == "origin":
        return True
    base = permission.path.rstrip("/")
    return target.path == base or target.path.startswith(base + "/")


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


def _target_authorized_by(pattern: str, target: str) -> bool:
    """Whether one allowed entry authorizes a target.

    The entry is interpreted as a typed permission (see ``parse_scope_entry``)
    and compared component by component against the parsed target. Strings are
    never compared by prefix: ``http://127.0.0.1:8877`` authorizes the paths of
    that origin, not ``127.0.0.1:8877.evil.test`` and not another port, and it
    authorizes a bare ``127.0.0.1`` only because a port-scanner target inherits
    the entry's port rather than opening every port on the host.

    Tools are handed derived resources rather than the base an operator typed,
    which is why an origin permission covers any path (``/FUZZ``,
    ``/user?id=1``) and a bare host without a port is accepted — denying those
    silently removed sqlmap-style URLs, ffuf and every port scanner from an
    authorized run. An entry that is itself a wildcard pattern is applied as a
    glob, because that is the operator explicitly stating intent.
    """
    try:
        parsed_target = parse_target(target, require_http_scheme=False)
    except TargetParseError as exc:
        logger.warning("Target %r rejected: %s", target, exc)
        return False

    permission = parse_scope_entry(pattern)
    if permission is None:
        return _match_glob(pattern, target) or _match_glob(
            pattern, parsed_target.hostname
        )
    return permission_authorizes(permission, parsed_target)


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
        if _target_authorized_by(pattern, target):
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


# ── Run scope published by the orchestrator ──────────────────────────
#
# A run's authorization is stated in the job payload (the local CLI sends
# ``{"mode": "allowlist", "allowed_targets": [target]}``), but tools execute
# several layers below the code that reads that payload. The orchestrator
# publishes the scope here on arrival and the tool-level guards consult it, so a
# run cannot be authorized at the phase level and then denied at the tool level
# — which is what happened on the SQLite/local path, where no engagement record
# ever carried a scope (found by running step 1 of docs/DEMO-READINESS-PLAN.md).
_run_scopes: dict[str, dict[str, Any]] = {}


def _scope_key(engagement_id: str | None) -> str:
    return str(engagement_id or "").strip()


def set_process_scope(
    engagement_id: str,
    mode: str = "allowlist",
    allowed_targets: list[str] | None = None,
    blocked_targets: list[str] | None = None,
) -> None:
    """Publish one engagement's run scope for this process.

    Called by the orchestrator when it reads the job payload, following the
    same run-level-config convention as ``config.llm_env.set_worker_llm_config``.

    The scope is keyed by engagement: a single-slot process-global value let a
    concurrent run inherit whichever authorization was published last, so a
    caller could be authorized by another engagement's scope. A publication
    without an owner is refused rather than stored unkeyed.
    """
    key = _scope_key(engagement_id)
    if not key:
        raise ValueError(
            "set_process_scope requires an engagement_id: an authorization "
            "without an owner could be borrowed by the next run in this process"
        )
    _run_scopes[key] = {
        "mode": mode or "allowlist",
        "allowed_targets": list(allowed_targets or []),
        "blocked_targets": list(blocked_targets or []),
    }


def clear_process_scope(engagement_id: str | None = None) -> None:
    """Forget one engagement's published scope, or every one (tests/teardown)."""
    if engagement_id is None:
        _run_scopes.clear()
    else:
        _run_scopes.pop(_scope_key(engagement_id), None)


def process_scope(engagement_id: str | None = None) -> dict[str, Any] | None:
    """The scope published for this engagement, or None.

    There is deliberately no unkeyed lookup: a caller that cannot name its
    engagement has no published authorization it may borrow.
    """
    key = _scope_key(engagement_id)
    if not key:
        return None
    scope = _run_scopes.get(key)
    return dict(scope) if scope else None


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
            _unscoped = os.environ.get("ARGUS_ALLOW_UNSCOPED", "").lower() in ("1", "true")
            if _unscoped:
                logger.warning(
                    "authorized_scope is empty — ALLOWING ALL TARGETS (ARGUS_ALLOW_UNSCOPED=1). "
                    "This is acceptable only for development/testing. "
                    "For production, set authorized_scope with domains/IP ranges."
                )
                return True
            logger.warning(
                "authorized_scope is empty — REJECTING ALL TARGETS. "
                "Set authorized_scope with domains/IP ranges, or set "
                "ARGUS_ALLOW_UNSCOPED=1 to allow scanning without scope."
            )
            return False

        try:
            validator = ScopeValidator(engagement_id or "", authorized_scope)
            return validator.is_in_scope(target)
        except Exception as e:
            logger.warning(
                "Scope validation failed for %s -- failing closed (deny): %s",
                target,
                e,
            )
            return False

    # -- Config-based enforcement path (mode / allowed / blocked) --
    # A caller that brings no rules of its own (the tool-level guards do not have
    # the job payload) means "use this run's scope". Without this fallback such a
    # call would deny every target under the default allowlist mode.
    if allowed_targets is None and blocked_targets is None:
        published = process_scope(engagement_id)
        if published:
            mode = published.get("mode", mode)
            allowed_targets = published.get("allowed_targets")
            blocked_targets = published.get("blocked_targets")

    # A target that cannot be parsed cannot be authorized, in any mode: the
    # old code let an unparseable string fall through to string matching, where
    # a lookalike could land inside an allowed pattern's text.
    try:
        parse_target(target, require_http_scheme=False)
    except TargetParseError as exc:
        logger.warning("Target %r rejected: %s", target, exc)
        return False

    if _check_blocked(target, blocked_targets):
        return False

    if mode == "open":
        return True

    result = _check_allowed(target, allowed_targets, mode)
    return result if result is not None else True


@dataclass(frozen=True)
class TargetAuthorization:
    """The decision for one target, plus the parsed target it was made about."""

    authorized: bool
    target: ParsedTarget | None
    reason: str
    #: Port a port-less host target inherits from the entry that authorized it.
    #: A caller acting on such a target must use this port; it is never "any
    #: port". ``None`` when the target named its own port or no port applies.
    inherited_port: int | None = None


def authorize_target(
    target: str,
    engagement_id: str | None = None,
    *,
    mode: str = "allowlist",
    allowed_targets: list[str] | None = None,
    blocked_targets: list[str] | None = None,
    base_url: str | None = None,
    allow_origin: str | None = None,
    reject_internal: bool = True,
) -> TargetAuthorization:
    """Parse a target and decide whether it is authorized — the one entry point.

    Every path that authorizes a target calls this: CLI target arguments,
    discovered URLs (crawl links, peer/endpoint discovery) and redirect
    ``Location`` hops. Callers get a decision plus the parsed target, so none of
    them needs its own string comparison.

    Parsing happens first and failure is a denial, not a fallback: an empty,
    scheme-less-with-path, control-character or non-HTTP target is rejected
    before any scope matching, which is what the old prefix/host-suffix tests
    failed to do.

    Args:
        target: CLI target, discovered URL, host or ``host:port``, or a redirect
            ``Location`` value.
        engagement_id: Engagement whose published run scope applies.
        mode / allowed_targets / blocked_targets: Explicit rules; when no rules
            are supplied the engagement's published scope is used.
        base_url: Base to resolve a relative reference against (redirect hops).
        allow_origin: The scan target's own URL. With no engagement there is no
            authoritative scope, so the scan target's origin is the only origin
            a discovered URL or redirect may reach; a sibling origin, another
            scheme or another port is refused. Ignored once an engagement (and
            therefore a real scope) is in play, so this can only narrow.
        reject_internal: Apply the internal/cloud-metadata policy.

    Returns:
        TargetAuthorization with the decision, the parsed target (None when it
        could not be parsed) and a human-readable reason.
    """
    try:
        parsed = parse_target(target, base_url=base_url)
    except TargetParseError as exc:
        logger.warning("Target %r rejected: %s", target, exc)
        return TargetAuthorization(False, None, str(exc))

    authorized = validate_target_scope(
        parsed.request_target,
        engagement_id,
        mode=mode,
        allowed_targets=allowed_targets,
        blocked_targets=blocked_targets,
    )

    if (
        not authorized
        and allow_origin
        and not engagement_id
        and allowed_targets is None
        and blocked_targets is None
    ):
        try:
            origin = parse_target(allow_origin)
        except TargetParseError:
            origin = None
        # Origin equality on parsed parts: same scheme, same host, same port.
        if (
            origin is not None
            and not origin.host_form
            and parsed.scheme == origin.scheme
            and parsed.hostname == origin.hostname
            and parsed.port == origin.port
        ):
            authorized = True

    inherited_port = _inherited_port(parsed, engagement_id, allowed_targets, blocked_targets)

    if reject_internal and ScopeValidator.is_blocked_internal_target(
        parsed.hostname, authorized=authorized
    ):
        return TargetAuthorization(
            False,
            parsed,
            "internal or cloud-metadata target: requires the internal-target "
            "opt-in and an explicit scope entry",
            inherited_port,
        )

    return TargetAuthorization(
        authorized,
        parsed,
        "authorized" if authorized else "not in authorized scope",
        inherited_port,
    )


def _inherited_port(
    parsed: ParsedTarget,
    engagement_id: str | None,
    allowed_targets: list[str] | None,
    blocked_targets: list[str] | None,
) -> int | None:
    """The port a bare-host target inherits from the entry that authorized it.

    This is the explicit form of the one exception in ``permission_authorizes``:
    a port scanner is handed ``host`` rather than ``host:port``, so the decision
    reports which port the run authorized and the scanner is expected to use it.
    """
    if not parsed.host_form or parsed.port is not None:
        return None
    candidates = allowed_targets
    if candidates is None and blocked_targets is None:
        published = process_scope(engagement_id)
        candidates = (published or {}).get("allowed_targets")
    for entry in candidates or []:
        permission = parse_scope_entry(entry)
        if permission is None or permission.kind != "origin" or not permission.port:
            continue
        if _host_matches_permission(permission.hostname, parsed.hostname):
            return permission.port
    return None
