"""
Scope Validator - Ensures scan targets are within authorized scope
"""
from typing import List, Dict
from urllib.parse import urlparse
import ipaddress
import fnmatch


class ScopeViolationError(Exception):
    """Raised when target is outside authorized scope"""
    pass


class ScopeValidator:
    """
    Validates scan targets against authorized scope
    Supports exact domain matching, wildcard subdomains, and IP ranges
    """
    
    def __init__(self, engagement_id: str, authorized_scope: Dict):
        """
        Initialize Scope Validator
        
        Args:
            engagement_id: Engagement ID for logging
            authorized_scope: Dictionary with 'domains' and 'ipRanges' lists
        """
        self.engagement_id = engagement_id
        self.authorized_domains = authorized_scope.get("domains", [])
        self.authorized_ip_ranges = authorized_scope.get("ipRanges", [])
        
        # Parse IP ranges into network objects
        self.ip_networks = []
        for ip_range in self.authorized_ip_ranges:
            try:
                self.ip_networks.append(ipaddress.ip_network(ip_range, strict=False))
            except ValueError as e:
                print(f"Invalid IP range {ip_range}: {e}")
    
    def validate_target(self, target_url: str) -> bool:
        """
        Validate target is within authorized scope
        
        Args:
            target_url: Target URL to validate
            
        Returns:
            True if within scope
            
        Raises:
            ScopeViolationError: If target is outside scope
        """
        # Parse URL
        parsed = urlparse(target_url)
        hostname = parsed.hostname or parsed.netloc
        
        if not hostname:
            raise ScopeViolationError(f"Invalid URL: {target_url}")
        
        # Check if it's an IP address
        try:
            ip_addr = ipaddress.ip_address(hostname)
            if self._is_ip_in_ranges(ip_addr):
                return True
        except ValueError:
            # Not an IP address, treat as domain
            if self._domain_matches(hostname):
                return True
        
        # Not in scope
        self._log_violation(target_url, hostname)
        raise ScopeViolationError(
            f"Target {target_url} is outside authorized scope for engagement {self.engagement_id}"
        )
    
    def _domain_matches(self, target: str) -> bool:
        """
        Check if target domain matches allowed patterns
        
        Supports:
        - Exact matching: "staging.app.com"
        - Wildcard subdomains: "*.dev.app.com"
        
        Args:
            target: Target domain
            
        Returns:
            True if matches any allowed pattern
        """
        target_lower = target.lower()
        
        for allowed in self.authorized_domains:
            allowed_lower = allowed.lower()
            
            # Exact match
            if target_lower == allowed_lower:
                return True
            
            # Wildcard match
            if "*" in allowed_lower:
                # Convert wildcard pattern to fnmatch pattern
                if fnmatch.fnmatch(target_lower, allowed_lower):
                    return True
                
                # Also check if target is subdomain of wildcard
                # e.g., "*.dev.app.com" should match "test.dev.app.com"
                wildcard_base = allowed_lower.replace("*.", "")
                if target_lower.endswith("." + wildcard_base) or target_lower == wildcard_base:
                    return True
        
        return False
    
    def _is_ip_in_ranges(self, target_ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        """
        Check if IP is in authorized ranges
        
        Args:
            target_ip: Target IP address
            
        Returns:
            True if IP is in any authorized range
        """
        for network in self.ip_networks:
            if target_ip in network:
                return True
        
        return False
    
    def _log_violation(self, target_url: str, hostname: str):
        """
        Log scope violation for security audit
        
        Args:
            target_url: Full target URL
            hostname: Extracted hostname
        """
        # In production, this would write to scope_violations table
        print(f"SCOPE VIOLATION: Engagement {self.engagement_id} attempted to access {target_url}")
        print(f"  Hostname: {hostname}")
        print(f"  Authorized domains: {self.authorized_domains}")
        print(f"  Authorized IP ranges: {self.authorized_ip_ranges}")
    
    def is_in_scope(self, target_url: str) -> bool:
        """
        Check if target is in scope without raising exception
        
        Args:
            target_url: Target URL to check
            
        Returns:
            True if in scope, False otherwise
        """
        try:
            return self.validate_target(target_url)
        except ScopeViolationError:
            return False
