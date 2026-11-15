"""A resumed run is authorized by the same record as its initial run.

Resume replans and executes phases; it reaches tools through the same
``call_tool`` entry point with the engagement id (the executor sends it on every
call), so the validator built in ``scope_validator_for_engagement`` is the single
authorization decision for both runs. An absent or stale scope fails closed
instead of silently skipping validation.
"""

from __future__ import annotations

import pytest

from mcp_server import scope_validator_for_engagement
from orchestrator_pkg.engagement import EngagementService
from tools.scope_validator import ScopeViolationError


@pytest.fixture(autouse=True)
def no_unscoped_override(monkeypatch):
    monkeypatch.delenv("ARGUS_ALLOW_UNSCOPED", raising=False)


def _with_scope(monkeypatch, scope):
    monkeypatch.setattr(
        EngagementService,
        "load_authorized_scope",
        staticmethod(lambda _engagement_id: scope),
    )


def test_resumed_run_refuses_a_target_its_scope_forbids(monkeypatch):
    _with_scope(monkeypatch, {"domains": ["allowed.test"], "ipRanges": []})

    validator = scope_validator_for_engagement("eng-resumed")
    validator.validate_target("https://allowed.test/login")

    with pytest.raises(ScopeViolationError):
        validator.validate_target("https://forbidden.test/")


def test_resumed_run_with_a_missing_scope_fails_closed(monkeypatch):
    _with_scope(monkeypatch, None)

    validator = scope_validator_for_engagement("eng-resumed")
    with pytest.raises(ScopeViolationError):
        validator.validate_target("https://anything.test/")


def test_resumed_run_with_a_stale_scope_fails_closed(monkeypatch):
    _with_scope(monkeypatch, {})

    validator = scope_validator_for_engagement("eng-resumed")
    with pytest.raises(ScopeViolationError):
        validator.validate_target("https://anything.test/")


def test_a_valid_scope_still_authorizes_the_resumed_target(monkeypatch):
    _with_scope(monkeypatch, {"domains": ["allowed.test"], "ipRanges": []})

    validator = scope_validator_for_engagement("eng-resumed")
    assert validator.is_in_scope("https://allowed.test/login") is True
