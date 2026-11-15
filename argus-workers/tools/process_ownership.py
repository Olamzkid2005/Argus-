"""Engagement-owned subprocess cancellation (Stage 6.1 item 3).

A cancelled run used to have no way to stop the scanners it had started: the
only handle was the Popen object inside a single call, so an operator cancel
stopped the loop and left the tool running, and a "cancel everything" sweep
could only have targeted processes by command name — which would also kill
another engagement's scanner.

This registry records every child the run starts under its engagement, with the
child in its own process group (``start_new_session=True``). Cancelling an
engagement signals exactly those groups (SIGTERM, then SIGKILL after a grace
period), reports what happened including cleanup errors, and never touches a
process owned by another engagement. ``ProcessCleanupError`` records a failure
to reap a process so the caller can report it instead of claiming a clean stop.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    engagement_id: str
    terminated: list[int] = field(default_factory=list)
    escalated: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class EngagementProcessRegistry:
    """Thread-safe registry of engagement-owned process groups."""

    def __init__(self) -> None:
        self._owned: dict[str, dict[int, object]] = {}
        self._lock = threading.Lock()

    def register(self, engagement_id: str, process) -> None:
        if not engagement_id:
            raise ValueError("a spawned process must be owned by an engagement")
        with self._lock:
            self._owned.setdefault(engagement_id, {})[process.pid] = process

    def unregister(self, engagement_id: str, process) -> None:
        with self._lock:
            owned = self._owned.get(engagement_id)
            if owned is None:
                return
            owned.pop(process.pid, None)

    def active_for(self, engagement_id: str) -> list[int]:
        with self._lock:
            return sorted(self._owned.get(engagement_id, {}))

    def terminate_engagement(
        self, engagement_id: str, *, grace_seconds: float = 2.0
    ) -> CleanupReport:
        """Stop only this engagement's process groups.

        A process that did not exit within ``grace_seconds`` is escalated to
        SIGKILL. A process that cannot be signalled or reaped is reported in
        ``errors``; the registry entry is kept so a later retry can try again.
        """
        report = CleanupReport(engagement_id=engagement_id)
        with self._lock:
            owned = dict(self._owned.get(engagement_id, {}))

        for pid, process in owned.items():
            self._signal_group(pid, signal.SIGTERM, report)
            deadline = time.monotonic() + max(0.0, grace_seconds)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if process.poll() is None:
                self._signal_group(pid, signal.SIGKILL, report)
                report.escalated.append(pid)
            try:
                process.wait(timeout=5)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                report.errors.append(f"pid {pid}: could not reap process: {exc}")
                continue
            report.terminated.append(pid)
            self.unregister(engagement_id, process)

        for error in report.errors:
            logger.warning(
                "Engagement %s process cleanup: %s", engagement_id, error
            )
        return report

    @staticmethod
    def _signal_group(pid: int, sig: int, report: CleanupReport) -> None:
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            # Already gone: not an error, and the caller still reaps it.
            return
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            report.errors.append(f"pid {pid}: signal {sig} failed: {exc}")


#: Process-wide registry used by ``ToolRunner``.
_default_registry = EngagementProcessRegistry()


def get_process_registry() -> EngagementProcessRegistry:
    return _default_registry
