"""
Scope Validator - Ensures LLM-selected tools stay within authorized scope.
Prevents prompt injection from tricking the agent into scanning unauthorized targets.
"""
import json
import logging
import fnmatch
from typing import Dict, List, Optional
from urllib.parse import urlparse

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

    def __init__(self, engagement_id: str, authorized_scope: Optional[Dict] = None):
        """
        Args:
            engagement_id: Engagement UUID
            authorized_scope: Dict with 'domains' and 'ipRanges' lists, or JSON string
        """
        self.engagement_id = engagement_id
        self._scope = self._parse_scope(authorized_scope)

    def _parse_scope(self, scope) -> Dict:
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
        if not target:
            return True

        hostname = self._extract_hostname(target)

        if self._matches_domain(hostname):
            return True

        if self._matches_ip_range(hostname):
            return True

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
        target = target.strip().lower()

        if target.startswith(("http://", "https://")):
            return urlparse(target).hostname or target

        return target.split("/")[0].split(":")[0]

    def _matches_domain(self, hostname: str) -> bool:
        """Check if hostname matches any authorized domain (with wildcard support)."""
        for domain in self._scope.get("domains", []):
            if fnmatch.fnmatch(hostname, domain):
                return True
            if hostname == domain:
                return True
            if hostname.endswith("." + domain.lstrip("*.")):
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
