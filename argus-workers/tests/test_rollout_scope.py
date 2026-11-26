"""Stage 5 engagement allowlist tests (stage5-rollout-plan.md §2).

Pure unit tests — no database. Unconfigured means unscoped (existing behaviour
is preserved); a configured allowlist gates strictly and fails closed.
"""

from __future__ import annotations

from control_plane.rollout_scope import (
    ENV_VAR,
    parse_allowlist,
    v2_enabled_for_engagement,
)


def test_unset_allowlist_is_unscoped(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert v2_enabled_for_engagement("any-engagement") is True


def test_blank_allowlist_is_unscoped(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "   ")
    assert v2_enabled_for_engagement("any-engagement") is True


def test_listed_engagement_is_enabled(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "Eng-A, eng-b ")
    assert v2_enabled_for_engagement("eng-a") is True
    assert v2_enabled_for_engagement(" ENG-B ") is True


def test_unlisted_engagement_is_denied(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "eng-a")
    assert v2_enabled_for_engagement("eng-other") is False


def test_configured_but_empty_allowlist_denies_everything(monkeypatch):
    # Fail closed: a set-but-useless allowlist runs V2 nowhere.
    monkeypatch.setenv(ENV_VAR, " , ,")
    assert v2_enabled_for_engagement("eng-a") is False


def test_parse_none_and_blank_are_unscoped():
    assert parse_allowlist(None) is None
    assert parse_allowlist("") is None
    assert parse_allowlist("  ") is None


def test_parse_normalises_entries():
    assert parse_allowlist(" Eng-A ,,eng-b ") == frozenset({"eng-a", "eng-b"})
