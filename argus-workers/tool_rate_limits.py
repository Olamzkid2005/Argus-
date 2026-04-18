"""
Tool-specific rate limits for Argus Pentest Platform.

Defines rate limits for different security tools to prevent
overwhelming targets with intensive scans.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class ToolRateLimitConfig:
    """Rate limit configuration for a specific tool."""
    requests_per_second: float
    concurrent_requests: int
    burst_limit: int = 10


# Tool-specific rate limits
# These are more conservative than domain limits to prevent
# intensive tools from overwhelming targets
TOOL_RATE_LIMITS: Dict[str, ToolRateLimitConfig] = {
    "nuclei": ToolRateLimitConfig(
        requests_per_second=10.0,
        concurrent_requests=3,
        burst_limit=15
    ),
    "sqlmap": ToolRateLimitConfig(
        requests_per_second=2.0,
        concurrent_requests=1,
        burst_limit=3
    ),
    "ffuf": ToolRateLimitConfig(
        requests_per_second=5.0,
        concurrent_requests=2,
        burst_limit=10
    ),
    "httpx": ToolRateLimitConfig(
        requests_per_second=20.0,
        concurrent_requests=5,
        burst_limit=30
    ),
}


def get_tool_rate_limit(tool_name: str) -> ToolRateLimitConfig:
    """
    Get rate limit configuration for a tool.
    
    Args:
        tool_name: Name of the security tool
    
    Returns:
        ToolRateLimitConfig for the tool, or default if not found
    """
    return TOOL_RATE_LIMITS.get(
        tool_name,
        ToolRateLimitConfig(
            requests_per_second=5.0,
            concurrent_requests=2,
            burst_limit=10
        )
    )


def get_effective_rate_limit(
    domain_rps: float,
    domain_concurrent: int,
    tool_name: str
) -> tuple[float, int]:
    """
    Get effective rate limit by taking minimum of domain and tool limits.
    
    Args:
        domain_rps: Domain requests per second limit
        domain_concurrent: Domain concurrent requests limit
        tool_name: Name of the security tool
    
    Returns:
        Tuple of (effective_rps, effective_concurrent)
    """
    tool_config = get_tool_rate_limit(tool_name)
    
    effective_rps = min(domain_rps, tool_config.requests_per_second)
    effective_concurrent = min(
        domain_concurrent,
        tool_config.concurrent_requests
    )
    
    return effective_rps, effective_concurrent
