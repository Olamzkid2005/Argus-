"""
Verification for the first Argus graph write path (A-04 slice).

This test is intentionally small: create a canonical asset, create an
intent/fact/finding node, anchor it, and read the relationship back.

It uses repository-level verification, not a full dispatcher + worker + lease
end-to-end run. The dispatcher-owned boundary (C-18) is exercised through the
dispatcher surface in a companion check below.
"""

from __future__ import annotations

import uuid

import pytest

from database.graph_repository import (
    ExplorationGraphRepository,
    GraphNodeKind,
    GraphNodeState,
)
from database.dispatcher_graph import DispatcherGraph, GraphMutationError


@pytest.fixture
def repo():
    # First-pass verification is repository/unit-scoped. A real dispatcher run
    # would flow through dispatcher_graph and use a real Postgres connection.
    return ExplorationGraphRepository()


class TestCanonicalAssetUpsert:
    def test_same_identity_returns_same_asset(self, repo):
        key = f"domain-{uuid.uuid4().hex[:12]}.example.com"
        a1 = repo.upsert_asset(key, "root_domain", display_value=key)
        a2 = repo.upsert_asset(key, "root_domain", display_value=key.upper())

        assert a1["canonical_key"] == key
        assert a2["canonical_key"] == key
        assert a1["id"] == a2["id"]

    def test_different_types_are_different_assets(self, repo):
        key = f"host-{uuid.uuid4().hex[:12]}"
        a1 = repo.upsert_asset(key, "ip")
        a2 = repo.upsert_asset(key, "endpoint")

        assert a1["id"] != a2["id"]
        assert a1["asset_type"] == "ip"
        assert a2["asset_type"] == "endpoint"


class TestExplorationNodeCreate:
    def test_intent_node_is_created(self, repo):
        engagement_id = uuid.uuid4().hex
        node = repo.create_node(
            engagement_id,
            GraphNodeKind.INTENT,
            payload={"objective": "find authenticated API surface"},
        )

        assert node["engagement_id"] == engagement_id
        assert node["kind"] == GraphNodeKind.INTENT
        assert node["state"] == GraphNodeState.OPEN
        assert node["payload"]["objective"] == "find authenticated API surface"

    def test_node_can_be_reposited_and_read_back(self, repo):
        engagement_id = uuid.uuid4().hex
        fact = repo.create_node(
            engagement_id,
            GraphNodeKind.FACT,
            payload={"description": "one HTTPS endpoint was observed"},
        )
        found = repo.find_node_by_id(fact["id"])

        assert found is not None
        assert found["kind"] == GraphNodeKind.FACT
        assert found["payload"]["description"] == "one HTTPS endpoint was observed"


class TestAnchors:
    def test_node_can_be_anchored_to_an_asset(self, repo):
        asset = repo.upsert_asset(
            "target.example.com",
            "root_domain",
            display_value="target.example.com",
        )
        node = repo.create_node(
            uuid.uuid4().hex,
            GraphNodeKind.INTENT,
            payload={"objective": "enumerate subdomains"},
        )
        anchor = repo.attach_anchor(node["id"], asset["id"], role="investigated")

        assert anchor["node_id"] == node["id"]
        assert anchor["asset_id"] == asset["id"]
        assert anchor["role"] == "investigated"

    def test_anchors_for_node_return_assets(self, repo):
        asset = repo.upsert_asset(
            "backend.example.com",
            "endpoint",
            display_value="https://backend.example.com/api",
        )
        node = repo.create_node(
            uuid.uuid4().hex,
            GraphNodeKind.FACT,
            payload={"description": "backend endpoint discovered"},
        )
        repo.attach_anchor(node["id"], asset["id"], role="describes")

        anchors = repo.find_anchors_for_node(node["id"])
        assert len(anchors) == 1
        assert anchors[0]["id"] == asset["id"]
        assert anchors[0]["asset_type"] == "endpoint"

    def test_nodes_for_asset_return_anchored_nodes(self, repo):
        asset = repo.upsert_asset(
            "app.example.com",
            "app",
            display_value="customer app",
        )
        n1 = repo.create_node(
            uuid.uuid4().hex,
            GraphNodeKind.INTENT,
            payload={"objective": "check login flow"},
        )
        n2 = repo.create_node(
            uuid.uuid4().hex,
            GraphNodeKind.FACT,
            payload={"description": "login flow observed"},
        )
        repo.attach_anchor(n1["id"], asset["id"], role="investigated")
        repo.attach_anchor(n2["id"], asset["id"], role="describes")

        nodes = repo.find_nodes_for_asset(asset["id"])
        node_ids = {n["id"] for n in nodes}
        assert n1["id"] in node_ids
        assert n2["id"] in node_ids


class TestDispatcherOwnedSurface:
    """
    Smallest C-18 slice: mutations go through the dispatcher surface, not through
    ad-hoc repository calls scattered in worker/agent code.
    """

    def test_dispatcher_owns_ensure_asset(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        asset = dispatcher.ensure_asset(
            "shop.example.com",
            "root_domain",
            display_value="shop.example.com",
        )

        assert asset["canonical_key"] == "shop.example.com"
        assert asset["asset_type"] == "root_domain"

    def test_dispatcher_rejects_empty_asset_identity(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.ensure_asset("", "root_domain")

        with pytest.raises(GraphMutationError):
            dispatcher.ensure_asset("x", "")

    def test_dispatcher_rejects_empty_intent(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.create_intent("", "do something")

        with pytest.raises(GraphMutationError):
            dispatcher.create_intent("eng-1", "")

    def test_dispatcher_rejects_empty_anchor(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        with pytest.raises(GraphMutationError):
            dispatcher.anchor_node_to_asset("", "asset-1")

        with pytest.raises(GraphMutationError):
            dispatcher.anchor_node_to_asset("node-1", "")

    def test_dispatcher_flow_creates_asset_then_intent_then_anchor(self):
        repo = ExplorationGraphRepository()
        dispatcher = DispatcherGraph(repo)

        engagement_id = uuid.uuid4().hex
        asset = dispatcher.ensure_asset(
            "api.example.com",
            "endpoint",
            display_value="https://api.example.com/graphql",
        )
        intent = dispatcher.create_intent(
            engagement_id,
            "discover authenticated GraphQL surface",
        )
        anchor = dispatcher.anchor_node_to_asset(
            intent["id"],
            asset["id"],
            role="investigated",
        )

        read_back = repo.find_anchors_for_node(intent["id"])
        assert len(read_back) == 1
        assert read_back[0]["id"] == asset["id"]
        assert read_back[0]["asset_type"] == "endpoint"
