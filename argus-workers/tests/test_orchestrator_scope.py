"""Tests for orchestrator scope threading — Category: class

These tests require the full argus-workers environment (opentelemetry, etc.).
If imports fail, tests are gracefully skipped rather than failing collection.
"""

import os
from unittest.mock import patch

import pytest

# Attempt module-level import — if it fails, all tests in this file skip
try:
    from orchestrator_pkg.orchestrator import Orchestrator
    _HAVE_ORCHESTRATOR = True
except ImportError:
    _HAVE_ORCHESTRATOR = False


# The Orchestrator.__init__ requires a DATABASE_URL and several heavy
# dependencies (tool_runner, llm_client, mcp). We mock them out to keep
# the test fast and focused on the scope extraction logic.
_BASE_PATCHES = [
    "orchestrator_pkg.orchestrator.ToolRunner",
    "orchestrator_pkg.orchestrator.LLMClient",
    "orchestrator_pkg.orchestrator.get_mcp_server",
    "orchestrator_pkg.orchestrator.get_stream_manager",
    "orchestrator_pkg.orchestrator.TracingManager",
    "orchestrator_pkg.orchestrator.StructuredLogger",
    "orchestrator_pkg.orchestrator.ExecutionSpan",
    "orchestrator_pkg.orchestrator.Parser",
    "orchestrator_pkg.orchestrator.FindingNormalizer",
    "orchestrator_pkg.orchestrator.EngagementRepository",
    "orchestrator_pkg.orchestrator.FindingRepository",
    "orchestrator_pkg.orchestrator.RateLimitRepository",
    "orchestrator_pkg.orchestrator.ScanLogger",
    "orchestrator_pkg.orchestrator.emit_thinking",
    "orchestrator_pkg.custom_rules.CustomRulesService",
    "orchestrator_pkg.orchestrator.load_recon_context",
]

# Base job dicts shared across tests (scope key is overridden per test)
_SCOPE_JOB = {
    "targets": ["http://127.0.0.1:3001"],
    "budget": {},
    "trace_id": "trace-1",
    "agent_mode": True,
    "scan_mode": "standard",
    "aggressiveness": "moderate",
    "bug_bounty_mode": False,
    "auth_config": {},
    "dual_auth_config": None,
}

# Recon base — note 'target' (str) vs 'targets' (list)
_RECON_JOB = {
    "target": "http://127.0.0.1:3001",
    "budget": {},
    "trace_id": "trace-1",
    "agent_mode": True,
    "scan_mode": "standard",
    "aggressiveness": "moderate",
    "bug_bounty_mode": False,
    "auth_config": {},
    "dual_auth_config": None,
}


@pytest.mark.skipif(not _HAVE_ORCHESTRATOR, reason="Orchestrator import requires opentelemetry and full environment")
class TestOrchestratorScope:
    """Tests that Orchestrator.run_scan() and run_recon() thread scope from job to self."""

    @pytest.fixture(autouse=True)
    def _patch_orchestrator_deps(self):
        """Patch Orchestrator constructor dependencies so we can instantiate it."""
        def _getenv_side_effect(key, default=None):
            if key == "DATABASE_URL":
                return "postgresql://test:test@localhost:5432/test"
            return os.environ.get(key, default)

        patchers = []
        for target in _BASE_PATCHES:
            p = patch(target)
            p.start()
            patchers.append(p)
        # Patch os.getenv with side_effect so it returns real values for known keys
        # instead of MagicMock (which causes TCP connection timeouts elsewhere).
        p_env = patch("os.getenv", side_effect=_getenv_side_effect)
        p_env.start()
        patchers.append(p_env)
        yield
        for p in reversed(patchers):
            p.stop()

    @pytest.fixture
    def orchestrator(self):
        """Create a minimal Orchestrator instance with patched dependencies."""
        return Orchestrator(engagement_id="eng-test-scope-1", trace_id="trace-scope-1")

    def test_run_scan_sets_scope_mode_from_job(self, orchestrator):
        """run_scan() sets self.scope_mode from job['scope']['mode']."""
        job = {**_SCOPE_JOB, "scope": {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001", "localhost:3001"],
            "blocked_targets": ["*"],
        }}
        try:
            orchestrator.run_scan(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets == ["127.0.0.1:3001", "localhost:3001"]
        assert orchestrator.blocked_targets == ["*"]

    def test_run_scan_sets_scope_mode_allowlist_default(self, orchestrator):
        """run_scan() defaults to 'allowlist' when mode is missing in scope."""
        job = {**_SCOPE_JOB, "scope": {
            "allowed_targets": ["127.0.0.1:3001"],
        }}
        try:
            orchestrator.run_scan(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets == ["127.0.0.1:3001"]
        assert orchestrator.blocked_targets is None

    def test_run_scan_no_scope_leaves_attrs_unset(self, orchestrator):
        """run_scan() does not set scope attributes when job has no scope."""
        job = {**_SCOPE_JOB}
        try:
            orchestrator.run_scan(job)
        except Exception:
            pass

        assert not hasattr(orchestrator, "scope_mode")
        assert not hasattr(orchestrator, "allowed_targets")
        assert not hasattr(orchestrator, "blocked_targets")

    def test_run_scan_scope_empty_dict_skips(self, orchestrator):
        """run_scan() skips scope when scope is an empty dict."""
        job = {**_SCOPE_JOB, "scope": {}}
        try:
            orchestrator.run_scan(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets is None
        assert orchestrator.blocked_targets is None

    def test_run_scan_scope_none_skips(self, orchestrator):
        """run_scan() skips scope when scope is None."""
        job = {**_SCOPE_JOB, "scope": None}
        try:
            orchestrator.run_scan(job)
        except Exception:
            pass

        assert not hasattr(orchestrator, "scope_mode")

    # ── run_recon() tests ────────────────────────────────────────────────
    # The scope extraction logic is identical to run_scan(), but run_recon()
    # reads 'target' (str) instead of 'targets' (list).

    def test_run_recon_sets_scope_mode_from_job(self, orchestrator):
        """run_recon() sets self.scope_mode from job['scope']['mode']."""
        job = {**_RECON_JOB, "scope": {
            "mode": "allowlist",
            "allowed_targets": ["127.0.0.1:3001"],
            "blocked_targets": ["*"],
        }}
        try:
            orchestrator.run_recon(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets == ["127.0.0.1:3001"]
        assert orchestrator.blocked_targets == ["*"]

    def test_run_recon_sets_scope_mode_allowlist_default(self, orchestrator):
        """run_recon() defaults to 'allowlist' when mode is missing."""
        job = {**_RECON_JOB, "scope": {
            "allowed_targets": ["127.0.0.1:3001"],
        }}
        try:
            orchestrator.run_recon(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets == ["127.0.0.1:3001"]
        assert orchestrator.blocked_targets is None

    def test_run_recon_no_scope_leaves_attrs_unset(self, orchestrator):
        """run_recon() does not set scope attributes when job has no scope."""
        job = {**_RECON_JOB}
        try:
            orchestrator.run_recon(job)
        except Exception:
            pass

        assert not hasattr(orchestrator, "scope_mode")
        assert not hasattr(orchestrator, "allowed_targets")
        assert not hasattr(orchestrator, "blocked_targets")

    def test_run_recon_scope_empty_dict_skips(self, orchestrator):
        """run_recon() skips scope when scope is an empty dict."""
        job = {**_RECON_JOB, "scope": {}}
        try:
            orchestrator.run_recon(job)
        except Exception:
            pass

        assert orchestrator.scope_mode == "allowlist"
        assert orchestrator.allowed_targets is None
        assert orchestrator.blocked_targets is None

    def test_run_recon_scope_none_skips(self, orchestrator):
        """run_recon() skips scope when scope is None."""
        job = {**_RECON_JOB, "scope": None}
        try:
            orchestrator.run_recon(job)
        except Exception:
            pass

        assert not hasattr(orchestrator, "scope_mode")
