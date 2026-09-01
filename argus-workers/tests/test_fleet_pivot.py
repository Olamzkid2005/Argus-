"""Tests for fleet-pivot target collection in tasks.post_exploit.

Covers _collect_pivot_targets: INTERNAL_SERVICE_DISCOVERY findings,
subdomain expansion, dedup, max-target cap, and scope validation.
"""

import sys
from unittest.mock import MagicMock, patch

# Mock celery_app BEFORE importing tasks.post_exploit. This test file may be
# collected before test_post_exploit_dispatch.py (which also mocks celery via
# its own _heavy_deps), so without this the module would be cached with REAL
# Celery Task wrappers and the task-bound functions would bind arguments
# differently when called directly (same pattern as test_post_exploit_dispatch).
# The patch is stopped after import so the REAL celery_app is restored in
# sys.modules — otherwise the mock leaks for the whole session and breaks
# test_full_scan_pipeline_e2e.py's routing checks (they read app.conf.task_routes
# at test time).
_mock_app = MagicMock()
_mock_app.task = lambda **_kwargs: lambda f: f
_mock_celery = type(sys)("celery_app")
_mock_celery.app = _mock_app
_heavy_deps = patch.dict(sys.modules, {"celery_app": _mock_celery})
_heavy_deps.start()

import tasks.post_exploit as _pe_mod  # noqa: E402
from tasks.post_exploit import _collect_pivot_targets  # noqa: E402

_heavy_deps.stop()
# Do not leave the mock-bound task module cached for later integration tests.
sys.modules.pop("tasks.post_exploit", None)
_tasks_pkg = sys.modules.get("tasks")
if _tasks_pkg is not None:
    _tasks_pkg.__dict__.pop("post_exploit", None)

# NOTE: string-form patches like patch("tasks.post_exploit._target_in_scope")
# are NOT used here — the dual sys.path layout (argus-workers/ and
# argus-workers/tasks/ both importable as `tasks`) can make the string target
# resolve to a different module object than the one _pe_mod binds. Patch the
# module OBJECT directly (same convention as test_post_exploit_dispatch.py).


class TestCollectPivotTargets:
    def test_internal_service_discovery_hosts(self):
        result = {
            "new_findings": [
                {
                    "type": "INTERNAL_SERVICE_DISCOVERY",
                    "evidence": {"host": "10.0.0.5"},
                },
                {"type": "SQLI", "evidence": {"host": "10.0.0.6"}},
            ]
        }
        with patch.object(_pe_mod, "_target_in_scope", return_value=True):
            targets = _collect_pivot_targets(result, [], "eng-1")
        assert "http://10.0.0.5" in targets
        assert "http://10.0.0.6" not in targets  # only discovery findings

    def test_subdomain_expansion_suggestions(self):
        engine = type("IE", (), {})()
        engine.suggest_new_targets = lambda _findings: ["http://sub.example.com"]
        with patch.object(_pe_mod, "_target_in_scope", return_value=True), patch(
            "intelligence_engine.IntelligenceEngine", return_value=engine
        ):
            targets = _collect_pivot_targets({}, [], "eng-1")
        assert "http://sub.example.com" in targets

    def test_dedupes_targets(self):
        result = {
            "new_findings": [
                {"type": "INTERNAL_SERVICE_DISCOVERY", "evidence": {"host": "10.0.0.9"}},
                {"type": "INTERNAL_SERVICE_DISCOVERY", "evidence": {"host": "10.0.0.9"}},
            ]
        }
        with patch.object(_pe_mod, "_target_in_scope", return_value=True):
            targets = _collect_pivot_targets(result, [], "eng-1")
        assert targets.count("http://10.0.0.9") == 1

    def test_respects_max_targets(self):
        result = {
            "new_findings": [
                {
                    "type": "INTERNAL_SERVICE_DISCOVERY",
                    "evidence": {"host": f"10.0.0.{i}"},
                }
                for i in range(1, 8)
            ]
        }
        with patch.object(_pe_mod, "_target_in_scope", return_value=True):
            targets = _collect_pivot_targets(result, [], "eng-1", max_targets=3)
        assert len(targets) == 3

    def test_skips_already_scanned_targets(self):
        """Hosts present in existing findings must not be re-targeted."""
        result = {
            "new_findings": [
                {"type": "INTERNAL_SERVICE_DISCOVERY", "evidence": {"host": "10.0.0.5"}},
            ]
        }
        findings = [
            {"endpoint": "http://10.0.0.5/admin"},  # already scanned
            {"endpoint": "https://api.example.com"},  # already scanned
        ]
        engine = type("IE", (), {})()
        engine.suggest_new_targets = lambda _f: [
            "http://10.0.0.5",  # known → filtered out after the cap fill
            "http://new-host.internal",  # novel → kept
        ]
        with patch.object(_pe_mod, "_target_in_scope", return_value=True), patch(
            "intelligence_engine.IntelligenceEngine", return_value=engine
        ):
            targets = _collect_pivot_targets(result, findings, "eng-1")
        assert "http://10.0.0.5" not in targets
        assert "http://new-host.internal" in targets

    def test_filters_out_of_scope_targets(self):
        result = {
            "new_findings": [
                {"type": "INTERNAL_SERVICE_DISCOVERY", "evidence": {"host": "10.0.0.5"}},
                {"type": "INTERNAL_SERVICE_DISCOVERY", "evidence": {"host": "10.0.0.6"}},
            ]
        }
        with patch.object(
            _pe_mod,
            "_target_in_scope",
            side_effect=lambda t, _e: t == "http://10.0.0.5",
        ):
            targets = _collect_pivot_targets(result, [], "eng-1")
        assert targets == ["http://10.0.0.5"]

    def test_engine_failure_is_non_fatal(self):
        with patch.object(_pe_mod, "_target_in_scope", return_value=True), patch(
            "intelligence_engine.IntelligenceEngine",
            side_effect=Exception("engine down"),
        ):
            assert _collect_pivot_targets({}, [], "eng-1") == []
