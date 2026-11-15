"""External tools are bounded by an egress policy decided before they start.

Stage 3.2 item 3. A CLI tool makes its own connections, so there is no
request-level hook at our boundary. The policy therefore works pre-spawn:

* tools whose traffic necessarily leaves the target scope are excluded;
* vendor-update flags are refused (they contact the tool's own service);
* *every* destination in the argv is authorized, not just the first;
* the run's own infrastructure endpoints are logged separately from target
  scope and can never be scanned.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from unittest.mock import patch

import pytest

from cache import CacheMode
from tool_core.result import ToolStatus
from tools.egress_policy import (
    authorize_tool_egress,
    extract_destinations,
    infrastructure_hosts,
)
from tools.scope_validator import clear_process_scope, set_process_scope
from tools.tool_runner import ToolRunner


@pytest.fixture(autouse=True)
def clean_scope():
    clear_process_scope()
    yield
    clear_process_scope()


class TestExcludedTools:
    @pytest.mark.parametrize(
        "tool", ["subfinder", "amass", "theharvester", "shodan", "trufflehog"]
    )
    def test_third_party_tools_are_excluded_with_a_reason(self, tool):
        decision = authorize_tool_egress(tool, ["-d", "example.com"])

        assert decision.allowed is False
        assert decision.tool_class == "third_party"
        assert "egress policy" in decision.reason

    def test_an_unknown_tool_with_no_destinations_is_allowed(self):
        # Local-only commands (echo, ls, a script over a file) make no egress.
        assert authorize_tool_egress("echo", ["hello"]).allowed is True

    @pytest.mark.parametrize(
        ("tool", "flag"),
        [
            ("nuclei", "-update-templates"),
            ("nuclei", "-ut"),
            ("wpscan", "--update"),
        ],
    )
    def test_vendor_update_flags_are_refused(self, tool, flag):
        decision = authorize_tool_egress(tool, ["-u", "https://example.com", flag])

        assert decision.allowed is False
        assert decision.tool_class == "vendor_update"


class TestDestinationExtraction:
    def test_every_url_argument_is_collected(self):
        targets, infrastructure = extract_destinations(
            ["-u", "https://a.test/x", "--url=https://b.test/y", "https://c.test/z"],
            tool="nuclei",
        )

        assert infrastructure == []
        assert targets == [
            "https://a.test/x",
            "https://b.test/y",
            "https://c.test/z",
        ]

    def test_output_paths_and_proxies_are_not_targets(self):
        targets, _ = extract_destinations(
            [
                "-u",
                "https://a.test",
                "-o",
                "https://looks-like-a-url.test",
                "--proxy",
                "http://proxy.test:8080",
            ],
            tool="ffuf",
        )

        assert targets == ["https://a.test"]

    def test_host_positional_tools_contribute_their_host(self):
        targets, _ = extract_destinations(["127.0.0.1", "-p", "80-90"], tool="nmap")

        assert targets == ["127.0.0.1"]

    def test_infrastructure_hosts_are_classified_separately(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        targets, infrastructure = extract_destinations(
            ["-u", "https://api.openai.com/v1/models"], tool="nuclei"
        )

        assert targets == []
        assert infrastructure == ["https://api.openai.com/v1/models"]


class TestPolicyDecision:
    def test_all_destinations_are_authorized_not_only_the_first(self):
        seen: list[str] = []

        def target_check(target: str) -> str | None:
            seen.append(target)
            return None

        decision = authorize_tool_egress(
            "nuclei",
            ["-u", "https://a.test", "-u", "https://b.test"],
            target_check=target_check,
        )

        assert decision.allowed is True
        assert seen == ["https://a.test", "https://b.test"]

    def test_a_later_out_of_scope_destination_refuses_the_whole_invocation(self):
        def target_check(target: str) -> str | None:
            return None if "a.test" in target else "outside authorized scope"

        decision = authorize_tool_egress(
            "nuclei",
            ["-u", "https://a.test", "-u", "https://evil.test"],
            target_check=target_check,
        )

        assert decision.allowed is False
        assert "https://evil.test" in decision.reason
        assert "outside authorized scope" in decision.reason

    def test_infrastructure_destination_is_refused_and_named(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        decision = authorize_tool_egress(
            "nuclei", ["-u", "https://api.openai.com/v1/models"]
        )

        assert decision.allowed is False
        assert decision.tool_class == "infrastructure"
        assert "infrastructure" in decision.reason

    def test_infrastructure_is_logged_on_its_own_channel(self, monkeypatch, caplog):
        monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/0")

        with caplog.at_level(logging.INFO, logger="argus.egress.infrastructure"):
            authorize_tool_egress(
                "nuclei", ["-u", "https://a.test"], target_check=lambda _: None
            )

        records = [
            r for r in caplog.records if r.name == "argus.egress.infrastructure"
        ]
        assert records, "approved infrastructure destinations must be logged"
        assert any("cache.internal" in r.getMessage() for r in records)
        # And never on the target-scope logger.
        assert not [
            r for r in caplog.records if r.name == "tools.scope_validator"
        ]

    def test_infrastructure_hosts_reads_known_endpoints(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://cache.internal:6379/0")

        assert infrastructure_hosts().get("cache.internal") == "redis"

    def test_same_host_different_port_is_a_target_not_infrastructure(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

        targets, infrastructure = extract_destinations(
            ["-u", "http://127.0.0.1:18080"], tool="nuclei"
        )

        assert targets == ["http://127.0.0.1:18080"]
        assert infrastructure == []

    def test_matching_infrastructure_port_is_still_refused(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

        decision = authorize_tool_egress(
            "nuclei", ["-u", "http://127.0.0.1:6379"]
        )

        assert decision.allowed is False
        assert decision.tool_class == "infrastructure"


class TestToolRunnerEnforcement:
    def setup_method(self):
        self.sandbox_dir = tempfile.mkdtemp(prefix="test_egress_sandbox_")
        set_process_scope("eng-1", "allowlist", ["https://allowed.test"])

    def teardown_method(self):
        self.runner.cleanup()
        clear_process_scope()

    def _runner(self) -> ToolRunner:
        self.runner = ToolRunner(sandbox_dir=self.sandbox_dir, engagement_id="eng-1")
        return self.runner

    def test_third_party_tool_never_spawns(self):
        runner = self._runner()

        with patch("tools.tool_runner.subprocess.run") as run_mock:
            result = runner.run("subfinder", ["-d", "example.com"])

        assert result.status == ToolStatus.SKIPPED
        assert "egress policy" in (result.stderr or "")
        run_mock.assert_not_called()

    def test_out_of_scope_destination_never_spawns(self):
        runner = self._runner()

        with (
            patch("tools.tool_runner.subprocess.run") as run_mock,
            patch.object(runner, "_resolve_tool_path", return_value=sys.executable),
        ):
            result = runner.run(
                "nuclei", ["-u", "https://evil.test"], cache_mode=CacheMode.NO_CACHE
            )

        assert result.status == ToolStatus.SCOPE_ERROR
        assert "https://evil.test" in (result.stderr or "")
        run_mock.assert_not_called()

    def test_update_flag_never_spawns(self):
        runner = self._runner()

        with patch("tools.tool_runner.subprocess.run") as run_mock:
            result = runner.run(
                "nuclei",
                ["-u", "https://allowed.test", "-update-templates"],
                cache_mode=CacheMode.NO_CACHE,
            )

        assert result.status == ToolStatus.SCOPE_ERROR
        assert "update" in (result.stderr or "").lower()
        run_mock.assert_not_called()

    def test_an_authorized_tool_still_runs(self):
        runner = self._runner()
        completed = __import__("subprocess").CompletedProcess(
            args=["nuclei"], returncode=0, stdout="[]", stderr=""
        )

        with (
            patch.object(runner, "_run_bounded", return_value=completed),
            patch.object(runner, "_resolve_tool_path", return_value=sys.executable),
        ):
            result = runner.run(
                "nuclei",
                ["-u", "https://allowed.test"],
                cache_mode=CacheMode.NO_CACHE,
            )

        assert result.status in {ToolStatus.SUCCESS, ToolStatus.SUCCESS_EMPTY}
