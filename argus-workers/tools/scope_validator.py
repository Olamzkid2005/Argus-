"""
Scope Validator - Ensures LLM-selected tools stay within authorized scope.
Prevents prompt injection from tricking the agent into scanning unauthorized targets.
"""
import json
import logging
from urllib.parse import urlparse

from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


class ScopeViolationError(Exception):
    """Raised when a tool is requested for an out-of-scope target."""
    pass


class ScopeValidator:
    """
    Validates that tool execution targets are within the engagement's authorized scope.

    Supports:
    - Domain matching (including wildcard: *.example.com)
    - IP range matching (CIDR notation)
    - Exact URL prefix matching
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
            slog.info(f"Scope loaded: {len(self._scope['domains'])} domains, {len(self._scope['ipRanges'])} IP ranges")

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
            slog.info(f"Target {target} in scope (domain match)")
            return True

        if self._matches_ip_range(hostname):
            slog.info(f"Target {target} in scope (IP range match)")
            return True

        slog.warn(f"Target {target} OUT of scope (hostname: {hostname})")
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


def validate_target_scope(target: str, engagement_id: str, authorized_scope: dict | None = None) -> bool:
    """Standalone convenience wrapper around ScopeValidator.

    Fail-Closed: If scope validation encounters an error (DB unavailable,
    malformed scope JSON, network timeout), the target is considered
    OUT of scope. Only when no scope is configured do we allow-all.

    R-03: DB lookup is wrapped in a thread with a configurable timeout
    (SCOPE_VALIDATION_TIMEOUT) to prevent scope validation from blocking
    the scan pipeline if the DB is slow or unreachable.

    Args:
        target: Target URL or hostname
        engagement_id: Engagement UUID
        authorized_scope: Optional scope dict (loaded from DB if None)

    Returns:
        True if target is in scope, False if not or on validation error
    """
    from config.constants import SCOPE_VALIDATION_TIMEOUT
    from database.connection import db_cursor

    # Load scope from DB if not provided (with timeout)
    if authorized_scope is None:
        try:
            import concurrent.futures as _futures

            def _load_scope():
                with db_cursor() as cursor:
                    cursor.execute(
                        "SELECT authorized_scope FROM engagements WHERE id = %s",
                        (engagement_id,),
                    )
                    row = cursor.fetchone()
                    return row[0] if row else None

            with _futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_load_scope)
                authorized_scope = future.result(timeout=SCOPE_VALIDATION_TIMEOUT)
        except _futures.TimeoutError:
            logger.warning(
                "Scope validation: DB lookup timed out after %ss for %s — "
                "defaulting to deny (L-20 fail-closed)",
                SCOPE_VALIDATION_TIMEOUT, engagement_id,
            )
            return False
        except Exception as e:
            logger.warning(
                "Scope validation: DB unavailable for %s — defaulting to deny: %s",
                target, e,
            )
            return False

    # No scope configured — allow all (no restrictions set by operator)
    if not authorized_scope:
        return True

    try:
        validator = ScopeValidator(engagement_id, authorized_scope)
        return validator.is_in_scope(target)
    except Exception as e:
        logger.warning(
            "Scope validation failed for %s — failing closed (deny): %s",
            target, e,
        )
        return False
