"""Shared fixtures for test_adaptive_planner tests."""

from types import SimpleNamespace

from orchestrator_pkg.planning.adaptive_planner import (
    AdaptiveWorkflowPlanner,
    TestingPhase,
    ToolTask,
    WorkflowPlan,
)


def _make_mock_recon(**overrides):
    """Create a minimal ReconContext-like SimpleNamespace with specified attributes.

    Using SimpleNamespace instead of MagicMock ensures ``hasattr()`` returns
    ``False`` for unset attributes, which matches how the activation functions
    use ``hasattr`` guards in the planner.
    """
    defaults = {
        "target_url": "https://example.com",
        "live_endpoints": ["https://example.com"],
        "subdomains": [],
        "open_ports": [],
        "tech_stack": [],
        "crawled_paths": [],
        "parameter_bearing_urls": [],
        "auth_endpoints": [],
        "api_endpoints": [],
        "findings_count": 0,
        "has_login_page": False,
        "has_api": False,
        "has_file_upload": False,
    }
    merged = {**defaults, **overrides}
    return SimpleNamespace(**merged)
