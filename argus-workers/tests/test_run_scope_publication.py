"""A run's scope must reach the tool layer, not just the phase layer.

Found by running step 1 of docs/DEMO-READINESS-PLAN.md: the local CLI sends the
run's authorization in the job payload (``{"mode": "allowlist",
"allowed_targets": [target]}``), the orchestrator threaded it onto itself for
phase-level target filtering — and then every tool was rejected by
``ToolRunner``'s scope guard, which only knew about the legacy engagement-record
scope (``domains``/``ipRanges``). On the SQLite/local path that record never
carries a scope, so the whole scan phase was blocked by the guard meant to make
scanning *safe*.

The fix keeps the guard fail-closed and gives it a second, explicit source: the
orchestrator publishes the job's scope with ``set_process_scope``, and the
tool-level guards consult it when the engagement record has none.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from database.sqlite_backend import SQLiteEngagementRepo
from orchestrator_pkg.engagement.engagement_service import EngagementService
from tools.scope_validator import (
    clear_process_scope,
    process_scope,
    set_process_scope,
    validate_target_scope,
)
from tools.tool_runner import ToolRunner

TARGET = "http://127.0.0.1:8877"
ALLOWED = {"mode": "allowlist", "allowed_targets": [TARGET], "blocked_targets": []}


@pytest.fixture(autouse=True)
def no_published_scope():
    """Every test starts with no run scope, so leakage cannot mask a failure."""
    clear_process_scope()
    yield
    clear_process_scope()


class TestPublishedScope:
    def test_round_trip_and_clear(self):
        assert process_scope() is None
        assert process_scope("eng-1") is None

        set_process_scope("eng-1", "allowlist", [TARGET], ["http://blocked.test"])
        assert process_scope("eng-1") == {
            "mode": "allowlist",
            "allowed_targets": [TARGET],
            "blocked_targets": ["http://blocked.test"],
        }
        # There is no unkeyed view of a published authorization.
        assert process_scope() is None

        clear_process_scope()
        assert process_scope("eng-1") is None

    def test_tool_level_check_uses_the_published_scope(self):
        # The tool guards pass no rules of their own: "use this run's scope".
        before = validate_target_scope(TARGET, "eng-1")
        set_process_scope("eng-1", "allowlist", [TARGET])
        after = validate_target_scope(TARGET, "eng-1")

        assert before is False, "no scope anywhere must stay fail-closed"
        assert after is True

    def test_published_scope_does_not_widen_an_explicit_allowlist(self):
        set_process_scope("eng-1", "allowlist", [TARGET])

        assert validate_target_scope(TARGET, allowed_targets=["http://other.test"]) is False

    def test_published_blocked_targets_win(self):
        set_process_scope("eng-1", "allowlist", [TARGET], [TARGET])

        assert validate_target_scope(TARGET, "eng-1") is False

    def test_published_open_mode_allows(self):
        # The published mode is honored, so an operator's explicit "open" run is
        # not silently downgraded to allowlist-with-no-rules (= deny).
        set_process_scope("eng-1", "open", [], [])

        assert validate_target_scope("http://anywhere.test", "eng-1") is True

    def test_a_published_allowlist_with_no_rules_denies(self):
        set_process_scope("eng-1", "allowlist", [], [])

        assert validate_target_scope(TARGET, "eng-1") is False


class TestEngagementIsolation:
    """Concurrent engagements must not borrow each other's authorization.

    The published scope used to be a single unkeyed slot: whichever run read its
    job payload last owned the authorization every later caller inherited. It is
    now keyed by engagement, and a caller that cannot name its engagement has no
    published scope at all.
    """

    def test_concurrent_engagements_keep_their_own_scopes(self):
        set_process_scope("eng-a", "allowlist", ["http://a.test"])
        set_process_scope("eng-b", "allowlist", ["http://b.test"])

        assert validate_target_scope("http://a.test", "eng-a") is True
        assert validate_target_scope("http://b.test", "eng-b") is True
        assert validate_target_scope("http://b.test", "eng-a") is False
        assert validate_target_scope("http://a.test", "eng-b") is False

    def test_an_unknown_engagement_has_no_published_scope(self):
        set_process_scope("eng-a", "allowlist", ["http://a.test"])

        assert validate_target_scope("http://a.test", "eng-z") is False

    def test_a_caller_without_an_engagement_cannot_use_a_published_scope(self):
        set_process_scope("eng-a", "open", [], [])

        assert validate_target_scope("http://a.test") is False

    def test_publication_without_an_owner_is_refused(self):
        with pytest.raises(ValueError):
            set_process_scope("", "open", [], [])

    def test_clearing_one_engagement_keeps_the_others(self):
        set_process_scope("eng-a", "allowlist", ["http://a.test"])
        set_process_scope("eng-b", "allowlist", ["http://b.test"])

        clear_process_scope("eng-a")

        assert validate_target_scope("http://a.test", "eng-a") is False
        assert validate_target_scope("http://b.test", "eng-b") is True


class TestDerivedTargetForms:
    """Tools are handed resources, not the base URL an operator typed.

    Denying every derived form silently removed sqlmap-style parameter URLs,
    ffuf's fuzz URL and every port scanner from an authorized run — measured on
    a local fixture where the rest of the pipeline ran.
    """

    @pytest.fixture(autouse=True)
    def scoped_run(self):
        set_process_scope("eng-1", "allowlist", [TARGET])

    @pytest.mark.parametrize(
        "derived",
        [
            TARGET,
            f"{TARGET}/FUZZ",
            f"{TARGET}/user?id=1",
            "127.0.0.1",  # what a port scanner is given
        ],
    )
    def test_derived_forms_of_the_authorized_target_are_allowed(self, derived):
        assert validate_target_scope(derived, "eng-1") is True

    @pytest.mark.parametrize(
        "other",
        [
            "http://127.0.0.1:9999",  # a different service on the host
            "http://127.0.0.1:8877.evil.test",  # lookalike host, not a path
            "http://127.0.0.1:8877x",  # prefix without a path boundary
            "http://elsewhere.test",
        ],
    )
    def test_nothing_else_is_widened_into_scope(self, other):
        assert validate_target_scope(other, "eng-1") is False


class TestToolRunnerGuard:
    def test_published_scope_authorizes_tool_execution(self):
        set_process_scope("eng-1", **{"mode": "allowlist", "allowed_targets": [TARGET]})
        runner = ToolRunner(engagement_id="eng-1")

        assert runner._scope_block_reason(TARGET) is None

    def test_no_scope_anywhere_still_blocks_with_a_diagnosable_message(self):
        runner = ToolRunner(engagement_id="eng-1")

        reason = runner._scope_block_reason(TARGET)

        assert reason is not None
        assert "no authorized_scope" in reason
        assert "ARGUS_ALLOW_UNSCOPED" in reason

    def test_out_of_scope_target_is_blocked(self):
        set_process_scope("eng-1", "allowlist", ["http://allowed.test"])
        runner = ToolRunner(engagement_id="eng-1")

        assert runner._scope_block_reason(TARGET) is not None

    def test_engagement_record_scope_is_consulted_first(self):
        # Postgres-backed deployments keep using the record; the published run
        # scope is only the fallback.
        set_process_scope("eng-1", "open", [], [])
        runner = ToolRunner(engagement_id="eng-1")

        with patch.object(
            ToolRunner,
            "_load_authorized_scope",
            return_value={"domains": ["example.com"], "ipRanges": []},
        ):
            assert runner._scope_block_reason("https://example.com/x") is None
            assert runner._scope_block_reason("https://elsewhere.test/x") is not None


    def test_tool_runner_does_not_inherit_another_engagements_scope(self):
        # A concurrent run published an open scope; this engagement has none.
        set_process_scope("eng-other", "open", [], [])
        runner = ToolRunner(engagement_id="eng-1")

        assert runner._scope_block_reason(TARGET) is not None


class TestLocalScopePersistence:
    """The local backend must be able to persist the scope it was handed."""

    def test_scope_config_round_trips_through_the_repo(self):
        repo = SQLiteEngagementRepo(":memory:")
        engagement = repo.create({"target": TARGET})

        EngagementService.store_scope_config(engagement["id"], ALLOWED, repo=repo)

        assert EngagementService.load_scope_config(engagement["id"], repo=repo) == ALLOWED

    def test_storing_preserves_other_metadata_keys(self):
        repo = SQLiteEngagementRepo(":memory:")
        engagement = repo.create(
            {"target": TARGET, "metadata": {"authorized_scope": {"domains": ["example.com"]}}}
        )

        EngagementService.store_scope_config(engagement["id"], ALLOWED, repo=repo)

        metadata = repo.find_by_id(engagement["id"])["metadata"]
        assert metadata["scope_config"] == ALLOWED
        assert metadata["authorized_scope"] == {"domains": ["example.com"]}

    def test_loading_from_an_engagement_without_scope_returns_none(self):
        repo = SQLiteEngagementRepo(":memory:")
        engagement = repo.create({"target": TARGET})

        assert EngagementService.load_scope_config(engagement["id"], repo=repo) is None

    def test_an_empty_scope_is_not_persisted(self):
        repo = SQLiteEngagementRepo(":memory:")
        engagement = repo.create({"target": TARGET})

        EngagementService.store_scope_config(engagement["id"], {}, repo=repo)

        assert EngagementService.load_scope_config(engagement["id"], repo=repo) is None
