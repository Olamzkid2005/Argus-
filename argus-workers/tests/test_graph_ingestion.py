"""
Tests for the recon -> ARTEX asset graph ingestion bridge (A2).

The bridge turns a recon context (live endpoints, subdomains, open ports) into
canonical assets and observations. Unit tests use a stub repository so the
mapping logic is covered without a database; one integration test proves the
same path persists through the dispatcher-owned repository.
"""

from __future__ import annotations

import os
import uuid

import pytest

from tasks.graph_ingestion import ingest_recon_outcomes, ingest_recon_result


def _db_available() -> bool:
    url = os.getenv("DATABASE_URL", os.getenv("TEST_DATABASE_URL"))
    if not url:
        return False
    try:
        import psycopg2

        psycopg2.connect(url, connect_timeout=3)
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


class _StubRepository:
    """Minimal stand-in for ExplorationGraphRepository (no database)."""

    def __init__(self) -> None:
        self.assets: dict[tuple, dict] = {}
        self.observations: list[dict] = []

    def upsert_asset(self, canonical_key, asset_type, **kwargs):
        key = (kwargs.get("scope_id"), canonical_key, asset_type)
        row = self.assets.get(key)
        if row is None:
            row = {
                "id": uuid.uuid4().hex,
                "canonical_key": canonical_key,
                "asset_type": asset_type,
                "scope_id": kwargs.get("scope_id"),
                "parent_asset_id": None,
            }
            self.assets[key] = row
        if kwargs.get("parent_asset_id"):
            row["parent_asset_id"] = kwargs["parent_asset_id"]
        return dict(row)

    def record_asset_observation(self, **kwargs):
        row = {"id": uuid.uuid4().hex, "observation_count": 1, **kwargs}
        self.observations.append(row)
        return row


def _context(**overrides):
    context = {
        "target_url": "https://api.example.com",
        "live_endpoints": ["https://api.example.com/v1", "https://api.example.com"],
        "subdomains": ["api.example.com", "dev.example.com"],
        "open_ports": [
            {"port": 443, "protocol": "tcp", "service": "https", "source": "naabu"}
        ],
        "crawled_paths": ["https://api.example.com/admin", "/relative/path"],
        "api_endpoints": [],
    }
    context.update(overrides)
    return context


class TestReconGraphIngestion:
    def test_endpoint_subdomain_and_service_observations_are_created(self):
        repo = _StubRepository()

        summary = ingest_recon_outcomes(
            "eng-1", _context(), authorized_scope=None, repository=repo
        )

        assert summary["status"] == "completed"
        assert summary["failed"] == 0
        assert summary["accepted"] == len(repo.observations)

        asset_types = {observation["asset_type"] for observation in repo.observations}
        assert {"endpoint", "subdomain", "service"} <= asset_types

        endpoint_values = [
            observation["observed_value"]
            for observation in repo.observations
            if observation["asset_type"] == "endpoint"
        ]
        # The target URL and the same live endpoint are ingested once, and a
        # relative crawled path is not a canonical URL.
        assert endpoint_values.count("https://api.example.com") == 1
        assert endpoint_values.count("https://api.example.com/v1") == 1
        assert "/relative/path" not in endpoint_values

        service = next(
            observation
            for observation in repo.observations
            if observation["asset_type"] == "service"
        )
        assert service["observed_value"] == "api.example.com:443/tcp"
        assert service["source"] == "recon"

    def test_out_of_scope_recon_assets_are_rejected_not_raised(self):
        repo = _StubRepository()

        summary = ingest_recon_outcomes(
            "eng-1",
            _context(subdomains=["api.example.com", "evil.test"]),
            authorized_scope={"domains": ["*.example.com"], "ipRanges": []},
            repository=repo,
        )

        assert summary["failed"] == 0
        assert summary["rejected"] == 1
        rejected = [
            observation for observation in repo.observations if not observation["accepted"]
        ]
        assert [observation["observed_value"] for observation in rejected] == [
            "evil.test"
        ]
        assert rejected[0]["rejection_reason"] == "out_of_scope"

    def test_invalid_values_are_counted_as_failures(self):
        repo = _StubRepository()

        summary = ingest_recon_outcomes(
            "eng-1",
            _context(subdomains=["not a host"]),
            authorized_scope=None,
            repository=repo,
        )

        assert summary["status"] == "completed"
        assert summary["failed"] == 1

    def test_ingest_recon_result_skips_missing_context(self):
        assert ingest_recon_result("eng-1", {})["status"] == "skipped"
        assert (
            ingest_recon_result("eng-1", {"recon_context": None})["status"] == "skipped"
        )
        assert ingest_recon_result("eng-1", None)["status"] == "skipped"

    def test_ingest_recon_result_uses_the_context(self):
        repo = _StubRepository()

        summary = ingest_recon_result(
            "eng-1",
            {"recon_context": _context()},
            authorized_scope=None,
            repository=repo,
        )

        assert summary["status"] == "completed"
        assert summary["accepted"] > 0

    def test_dataclass_recon_context_is_supported(self):
        from models.recon_context import ReconContext

        repo = _StubRepository()
        context = ReconContext(
            target_url="https://api.example.com",
            subdomains=["api.example.com"],
            open_ports=[{"port": 8443, "protocol": "tcp"}],
        )

        summary = ingest_recon_outcomes(
            "eng-1", context, authorized_scope=None, repository=repo
        )

        assert summary["accepted"] >= 3
        assert any(
            observation["asset_type"] == "service"
            and observation["observed_value"] == "api.example.com:8443/tcp"
            for observation in repo.observations
        )

    def test_ipv6_target_service_is_bracketed(self):
        repo = _StubRepository()

        summary = ingest_recon_outcomes(
            "eng-1",
            {
                "target_url": "https://[2001:db8::1]",
                "open_ports": [{"port": 443, "protocol": "tcp"}],
            },
            authorized_scope={"domains": [], "ipRanges": ["2001:db8::/32"]},
            repository=repo,
        )

        assert summary["accepted"] == 2
        assert summary["rejected"] == 0
        service = next(
            observation
            for observation in repo.observations
            if observation["asset_type"] == "service"
        )
        assert service["observed_value"] == "[2001:db8::1]:443/tcp"

    def test_max_assets_bounds_a_single_run(self):
        repo = _StubRepository()

        summary = ingest_recon_outcomes(
            "eng-1",
            _context(live_endpoints=[f"https://api.example.com/{i}" for i in range(20)]),
            authorized_scope=None,
            repository=repo,
            max_assets=5,
        )

        assert summary["accepted"] == 5
        assert len(repo.observations) == 5


@pytest.mark.skipif(not DB_AVAILABLE, reason="DATABASE_URL not reachable in this environment")
class TestReconIngestionPersistence:
    def test_recon_outcomes_persist_to_the_canonical_graph(self):
        from database.graph_repository import ExplorationGraphRepository

        scope_id = uuid.uuid4().hex
        repo = ExplorationGraphRepository()

        summary = ingest_recon_outcomes(
            scope_id, _context(), authorized_scope=None, repository=repo
        )

        assert summary["status"] == "completed"
        assert summary["accepted"] > 0

        assets = repo.find_assets_for_scope(scope_id)
        identities = {(asset["asset_type"], asset["canonical_key"]) for asset in assets}
        assert ("endpoint", "https://api.example.com") in identities
        assert ("endpoint", "https://api.example.com/v1") in identities
        assert ("subdomain", "api.example.com") in identities
        assert ("service", "tcp://api.example.com:443") in identities

        endpoint = next(
            asset
            for asset in assets
            if asset["canonical_key"] == "https://api.example.com"
        )
        observations = repo.find_observations_for_asset(endpoint["id"])
        assert any(row["source"] == "recon" for row in observations)
