"""Tests for agent.swarm_memory — SwarmMemory thread-safe shared store."""

import time
from concurrent.futures import ThreadPoolExecutor

from agent.swarm_memory import SwarmMemory


class TestSwarmMemoryPublishConsume:
    """Basic publish/consume cycle for endpoints, tech signals, parameters."""

    def test_publish_and_consume_endpoint(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://example.com/api/users/123")
        endpoints = memory.get_new_endpoints("api")  # api agent consumes
        assert endpoints == ["http://example.com/api/users/123"]

    def test_agent_does_not_see_own_endpoints(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://example.com/api/users/123")
        own = memory.get_new_endpoints("idor")
        assert own == []  # idor shouldn't see its own endpoints

    def test_agent_sees_peer_endpoints(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://example.com/idor/1")
        memory.publish_endpoint("api", "http://example.com/api/v2")
        idor_sees = memory.get_new_endpoints("idor")
        api_sees = memory.get_new_endpoints("api")
        # idor should see api's endpoint, but not its own
        assert "http://example.com/api/v2" in idor_sees
        assert "http://example.com/idor/1" not in idor_sees
        # api should see idor's endpoint, but not its own
        assert "http://example.com/idor/1" in api_sees
        assert "http://example.com/api/v2" not in api_sees

    def test_publish_endpoints_batch(self):
        memory = SwarmMemory()
        memory.publish_endpoints("api", ["http://ex.com/a", "http://ex.com/b"])
        all_eps = memory.get_all_endpoints()
        assert sorted(all_eps) == ["http://ex.com/a", "http://ex.com/b"]

    def test_endpoint_dedup(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://ex.com/dup")
        memory.publish_endpoint("api", "http://ex.com/dup")  # same endpoint
        all_eps = memory.get_all_endpoints()
        assert len(all_eps) == 1  # deduplicated

    def test_endpoint_trailing_slash_normalized(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://ex.com/foo/")
        memory.publish_endpoint("api", "http://ex.com/foo")  # no trailing slash
        all_eps = memory.get_all_endpoints()
        assert len(all_eps) == 1  # both map to http://ex.com/foo

    def test_empty_endpoint_not_published(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "")
        memory.publish_endpoint("api", "  ")
        assert memory.get_endpoint_count() == 0

    def test_tech_signal_publish_and_consume(self):
        memory = SwarmMemory()
        memory.publish_tech_signal("api", "framework", "Express")
        signals = memory.get_tech_signals("idor")
        assert len(signals) == 1
        assert signals[0]["category"] == "framework"
        assert signals[0]["value"] == "Express"

    def test_agent_does_not_see_own_tech_signals(self):
        memory = SwarmMemory()
        memory.publish_tech_signal("api", "framework", "Express")
        own_signals = memory.get_tech_signals("api")
        assert own_signals == []

    def test_tech_signal_dedup(self):
        memory = SwarmMemory()
        memory.publish_tech_signal("api", "framework", "Express")
        memory.publish_tech_signal("idor", "framework", "Express")  # same value
        signals = memory.get_tech_signals("auth")  # third agent sees it
        assert len(signals) == 1  # deduplicated by fingerprint

    def test_tech_summary(self):
        memory = SwarmMemory()
        memory.publish_tech_signal("api", "framework", "Express")
        memory.publish_tech_signal("idor", "server", "nginx")
        summary = memory.get_tech_summary()
        assert "framework" in summary
        assert "Express" in summary
        assert "server" in summary
        assert "nginx" in summary

    def test_tech_summary_empty(self):
        memory = SwarmMemory()
        assert memory.get_tech_summary() == ""

    def test_parameter_publish_and_consume(self):
        memory = SwarmMemory()
        memory.publish_parameter("idor", "user_id")
        params = memory.get_new_parameters("api")
        assert params == ["user_id"]

    def test_parameter_agent_isolation(self):
        memory = SwarmMemory()
        memory.publish_parameter("idor", "user_id")
        own_params = memory.get_new_parameters("idor")
        assert own_params == []

    def test_publish_parameters_batch(self):
        memory = SwarmMemory()
        memory.publish_parameters("api", ["q", "page", "limit"])
        params = memory.get_new_parameters("idor")
        assert sorted(params) == ["limit", "page", "q"]

    def test_auth_context_publish_and_get(self):
        memory = SwarmMemory()
        memory.publish_auth_context("auth", {"auth_type": "jwt"})
        ctx = memory.get_auth_context()
        assert ctx["auth_type"] == "jwt"

    def test_auth_context_merge(self):
        memory = SwarmMemory()
        memory.publish_auth_context("auth", {"auth_type": "jwt"})
        memory.publish_auth_context("idor", {"has_login_page": True})
        ctx = memory.get_auth_context()
        assert ctx["auth_type"] == "jwt"
        assert ctx["has_login_page"] is True

    def test_agent_summary(self):
        memory = SwarmMemory()
        memory.publish_summary("idor", "found 5 findings")
        memory.publish_summary("api", "found 3 findings")
        peer_summaries = memory.get_peer_summaries("idor")
        assert "api" in peer_summaries
        assert "idor" not in peer_summaries
        assert "found 5 findings" not in "|".join(peer_summaries.values())


class TestSwarmMemoryEmptyState:
    """Edge cases with empty/initial state."""

    def test_empty_endpoints(self):
        memory = SwarmMemory()
        assert memory.get_new_endpoints("idor") == []
        assert memory.get_all_endpoints() == []
        assert memory.get_endpoint_count() == 0

    def test_empty_tech_signals(self):
        memory = SwarmMemory()
        assert memory.get_tech_signals("idor") == []

    def test_empty_auth_context(self):
        memory = SwarmMemory()
        assert memory.get_auth_context() == {}

    def test_empty_parameters(self):
        memory = SwarmMemory()
        assert memory.get_new_parameters("idor") == []

    def test_empty_snapshot(self):
        memory = SwarmMemory()
        snap = memory.snapshot()
        assert snap["endpoint_count"] == 0
        assert snap["tech_fingerprints"] == 0

    def test_none_string_not_published(self):
        memory = SwarmMemory()
        memory.publish_tech_signal("idor", "", "value")  # empty category
        memory.publish_tech_signal("idor", "cat", "")   # empty value
        memory.publish_endpoint("idor", "")
        memory.publish_parameter("idor", "")
        assert memory.get_endpoint_count() == 0
        assert len(memory.get_tech_signals("api")) == 0
        assert memory.get_new_parameters("api") == []


class TestSwarmMemoryThreadSafety:
    """Thread safety under concurrent access."""

    def test_concurrent_publish_does_not_deadlock(self):
        """Publish from multiple threads simultaneously."""
        memory = SwarmMemory()
        n_threads = 10
        endpoints_per_thread = 100

        def publish(agent_id: str):
            for i in range(endpoints_per_thread):
                memory.publish_endpoint(
                    agent_id,
                    f"http://example.com/{agent_id}/resource/{i}",
                )

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = []
            for i in range(n_threads):
                futures.append(pool.submit(publish, f"agent{i}"))
            for f in futures:
                f.result(timeout=5)

        # All endpoints should be unique
        assert memory.get_endpoint_count() == n_threads * endpoints_per_thread

    def test_concurrent_read_write_no_crash(self):
        """Read from one thread while another writes."""
        memory = SwarmMemory()

        def writer():
            for i in range(100):
                memory.publish_endpoint("api", f"http://ex.com/{i}")
                memory.publish_tech_signal("api", "framework", f"v{i}")
                time.sleep(0.001)

        def reader():
            for _ in range(50):
                memory.get_new_endpoints("idor")
                memory.get_tech_signals("idor")
                time.sleep(0.002)

        with ThreadPoolExecutor(max_workers=3) as pool:
            w = pool.submit(writer)
            r1 = pool.submit(reader)
            r2 = pool.submit(reader)
            w.result(timeout=10)
            r1.result(timeout=10)
            r2.result(timeout=10)

        # Should not crash, and at least some endpoints should be visible
        assert memory.get_endpoint_count() > 0

    def test_concurrent_tech_dedup(self):
        """Dedup under concurrent publishing of same signal."""
        memory = SwarmMemory()

        def publish_same():
            for _ in range(50):
                memory.publish_tech_signal("api", "framework", "React")

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(publish_same) for _ in range(5)]
            for f in futures:
                f.result(timeout=5)

        # Should only have 1 unique tech signal, not 250
        assert memory.snapshot()["tech_fingerprints"] == 1

    def test_endpoint_dedup_concurrent(self):
        """Same endpoint published by multiple agents concurrently."""
        memory = SwarmMemory()

        def publish_dup(agent: str):
            for _ in range(20):
                memory.publish_endpoint(agent, "http://example.com/shared")

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(publish_dup, "idor"),
                pool.submit(publish_dup, "api"),
                pool.submit(publish_dup, "auth"),
            ]
            for f in futures:
                f.result(timeout=5)

        # Only 1 unique endpoint
        assert memory.get_endpoint_count() == 1

    def test_auth_context_concurrent_merge(self):
        """Multiple agents publishing auth context concurrently."""
        memory = SwarmMemory()

        def publish_auth(agent: str, key: str, value: str):
            for _ in range(10):
                memory.publish_auth_context(agent, {key: value})
                time.sleep(0.001)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(publish_auth, "auth", "auth_type", "jwt"),
                pool.submit(publish_auth, "idor", "has_login_page", "true"),
                pool.submit(publish_auth, "api", "has_api", "true"),
            ]
            for f in futures:
                f.result(timeout=5)

        ctx = memory.get_auth_context()
        # All keys should be present (although values may have been overwritten)
        assert "auth_type" in ctx
        assert "has_login_page" in ctx
        assert "has_api" in ctx


class TestSwarmMemorySnapshot:
    """Snapshot consistency."""

    def test_snapshot_after_publishes(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://ex.com/1")
        memory.publish_endpoint("api", "http://ex.com/2")
        memory.publish_tech_signal("auth", "framework", "Django")
        memory.publish_summary("idor", "done")

        snap = memory.snapshot()
        assert snap["endpoint_count"] == 2
        assert snap["tech_fingerprints"] == 1
        assert "idor" in snap["agents_with_signals"]
        assert "api" in snap["agents_with_signals"]
        assert "auth" in snap["agents_with_signals"]
        assert snap["completed_agents"] == ["idor"]

    def test_get_endpoints_by_agent(self):
        memory = SwarmMemory()
        memory.publish_endpoint("idor", "http://ex.com/idor/1")
        memory.publish_endpoint("api", "http://ex.com/api/1")
        memory.publish_endpoint("api", "http://ex.com/api/2")

        by_agent = memory.get_endpoints_by_agent("auth")
        assert "idor" in by_agent
        assert "api" in by_agent
        assert len(by_agent["api"]) == 2
        assert len(by_agent["idor"]) == 1

        # Consuming agent (auth) should not appear
        assert "auth" not in by_agent
