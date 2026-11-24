"""The claim protocol is defined once and shared by todos and intents (A-11/A-12)."""

import pytest

from database.graph_claims import (
    DEFAULT_INTENT_LEASE_SECONDS,
    DEFAULT_TODO_LEASE_SECONDS,
    LEASE_CLEAR_SQL,
    LEASE_GRANT_SQL,
    claim_token_matches,
    claimable_sql,
    live_claim_sql,
    validate_lease_seconds,
)
from database.graph_errors import GraphMutationError


class TestLeaseSeconds:
    @pytest.mark.parametrize("value", [0, -1, -300])
    def test_a_non_positive_lease_is_rejected(self, value):
        with pytest.raises(GraphMutationError):
            validate_lease_seconds(value)

    @pytest.mark.parametrize("value", ["not-a-number", None, object()])
    def test_a_non_numeric_lease_is_rejected(self, value):
        with pytest.raises(GraphMutationError):
            validate_lease_seconds(value)

    def test_a_positive_lease_is_returned_as_an_int(self):
        assert validate_lease_seconds(90) == 90
        assert validate_lease_seconds("120") == 120


class TestClaimTokenFencing:
    def test_an_unclaimed_row_accepts_an_unclaimed_write(self):
        assert claim_token_matches(None, None) is True

    def test_the_current_token_matches_across_str_and_uuid_objects(self):
        import uuid

        token = "0f8fad5b-d9cb-469f-a165-70867728950e"
        assert claim_token_matches(token, token) is True
        assert claim_token_matches(uuid.UUID(token), token) is True
        assert claim_token_matches(token, uuid.UUID(token)) is True

    def test_a_stale_or_absent_token_never_matches_a_live_claim(self):
        current = "0f8fad5b-d9cb-469f-a165-70867728950e"
        stale = "11111111-2222-4333-8444-555555555555"
        assert claim_token_matches(current, stale) is False
        assert claim_token_matches(current, None) is False
        assert claim_token_matches(current, "") is False


class TestSharedPredicates:
    def test_claimable_work_is_open_or_lease_expired(self):
        predicate = claimable_sql()
        assert "state = 'open'" in predicate
        assert "lease_expires_at IS NULL" in predicate
        assert "lease_expires_at < NOW()" in predicate

    def test_claimable_predicate_can_target_a_joined_alias(self):
        predicate = claimable_sql(
            state_column="status",
            open_states=("open",),
            running_state="in_progress",
            prefix="candidate.",
        )
        assert "candidate.status = 'open'" in predicate
        assert "candidate.status = 'in_progress'" in predicate
        assert "candidate.lease_expires_at" in predicate

    def test_live_claim_requires_running_current_token_and_live_lease(self):
        predicate = live_claim_sql(state_column="status", running_state="in_progress")
        assert "status = 'in_progress'" in predicate
        assert "claim_token::text = %s" in predicate
        assert "lease_expires_at IS NOT NULL" in predicate
        assert "lease_expires_at > NOW()" in predicate
        assert predicate.count("%s") == 1

    def test_grant_and_clear_assignments_are_symmetric(self):
        assert "lease_expires_at = NOW() + (%s * INTERVAL '1 second')" in (
            LEASE_GRANT_SQL
        )
        assert "last_heartbeat_at = NOW()" in LEASE_GRANT_SQL
        for column in ("claim_token", "lease_expires_at", "last_heartbeat_at"):
            assert f"{column} = NULL" in LEASE_CLEAR_SQL

    def test_both_paths_share_the_same_lease_defaults(self):
        assert DEFAULT_TODO_LEASE_SECONDS > 0
        assert DEFAULT_INTENT_LEASE_SECONDS > 0
