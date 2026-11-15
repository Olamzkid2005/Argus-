"""Tests for engagement-owned subprocess cancellation (Stage 6.1 item 3)."""

import os
import subprocess
import sys

import pytest

from tools.process_ownership import (
    EngagementProcessRegistry,
    get_process_registry,
)


def spawn_group(seconds: int = 30) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        start_new_session=True,
    )


def is_running(proc: subprocess.Popen) -> bool:
    return proc.poll() is None


@pytest.fixture
def registry():
    return EngagementProcessRegistry()


class TestOwnership:
    def test_only_the_named_engagement_is_cancelled(self, registry):
        mine = spawn_group()
        other = spawn_group()
        try:
            registry.register("eng-a", mine)
            registry.register("eng-b", other)
            assert registry.active_for("eng-a") == [mine.pid]

            report = registry.terminate_engagement("eng-a", grace_seconds=0.2)

            assert report.ok is True
            assert mine.pid in report.terminated
            assert not is_running(mine)
            # The other engagement's scanner is untouched.
            assert is_running(other)
            assert registry.active_for("eng-b") == [other.pid]
        finally:
            for proc in (mine, other):
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass

    def test_unknown_engagement_reports_nothing(self, registry):
        report = registry.terminate_engagement("eng-missing")
        assert report.ok is True
        assert report.terminated == []
        assert report.escalated == []

    def test_process_without_engagement_is_refused(self, registry):
        proc = spawn_group()
        try:
            with pytest.raises(ValueError, match="owned by an engagement"):
                registry.register("", proc)
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_a_process_ignoring_sigterm_is_escalated_and_reported(self, registry):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(30)",
            ],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        try:
            registry.register("eng-a", proc)
            report = registry.terminate_engagement("eng-a", grace_seconds=0.2)
            assert report.escalated == [proc.pid]
            assert report.terminated == [proc.pid]
            assert not is_running(proc)
        finally:
            if is_running(proc):
                proc.kill()
            proc.wait(timeout=5)

    def test_cleanup_errors_are_reported_not_hidden(self, registry):
        class BrokenProcess:
            pid = 424242

            def poll(self):
                return None

            def wait(self, timeout=None):
                raise OSError("cannot reap")

        registry.register("eng-a", BrokenProcess())
        report = registry.terminate_engagement("eng-a", grace_seconds=0.0)
        assert report.ok is False
        assert any("cannot reap" in error for error in report.errors)

    def test_registry_is_process_wide_and_unregisters(self):
        proc = spawn_group()
        registry = get_process_registry()
        try:
            registry.register("eng-shared", proc)
            assert proc.pid in registry.active_for("eng-shared")
            registry.unregister("eng-shared", proc)
            assert proc.pid not in registry.active_for("eng-shared")
        finally:
            proc.kill()
            proc.wait(timeout=5)


class TestToolRunnerCancellation:
    def test_tool_runner_cancels_only_its_engagement(self, tmp_path):
        from tools.tool_runner import ToolRunner

        first = ToolRunner(sandbox_dir=str(tmp_path), engagement_id="eng-one")
        second = ToolRunner(sandbox_dir=str(tmp_path), engagement_id="eng-two")
        mine = spawn_group()
        other = spawn_group()
        registry = get_process_registry()
        try:
            registry.register("eng-one", mine)
            registry.register("eng-two", other)
            report = first.cancel_engagement("eng-one", grace_seconds=0.2)
            assert not is_running(mine)
            assert is_running(other)
            assert report.engagement_id == "eng-one"
            # A second runner's cancel does not reach the first's processes.
            assert second.cancel_engagement("eng-two", grace_seconds=0.2).ok
        finally:
            for proc in (mine, other):
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass

    def test_bounded_run_returns_output_and_reaps(self, tmp_path):
        from tools.tool_runner import ToolRunner

        runner = ToolRunner(sandbox_dir=str(tmp_path), engagement_id="eng-run")
        result = runner._run_bounded(
            [sys.executable, "-c", "print('hello bounded')"],
            timeout=30,
            cwd=str(tmp_path),
            env=dict(os.environ),
            max_output_bytes=1024,
        )
        assert result.returncode == 0
        assert "hello bounded" in result.stdout
        assert get_process_registry().active_for("eng-run") == []

    def test_bounded_run_truncates_and_kills_a_chatty_process(self, tmp_path):
        from tools.tool_runner import ToolRunner

        runner = ToolRunner(sandbox_dir=str(tmp_path), engagement_id="eng-chatty")
        script = "import sys\nwhile True:\n    sys.stdout.write('x' * 4096)\n"
        result = runner._run_bounded(
            [sys.executable, "-c", script],
            timeout=30,
            cwd=str(tmp_path),
            env=dict(os.environ),
            max_output_bytes=8192,
        )
        # Bounded: never the whole unbounded stream, and the process was stopped
        # rather than being allowed to produce output indefinitely.
        assert len(result.stdout) <= 8192
        assert result.returncode != 0
        assert get_process_registry().active_for("eng-chatty") == []
