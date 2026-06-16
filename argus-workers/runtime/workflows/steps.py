"""
Workflow Steps — Concrete step implementations for the BOLA/BOPLA workflow.

Each step inherits from WorkflowStep and implements run(ctx) -> StepResult.
Steps communicate via WorkflowContext (mutated in place). Obstacles are
emitted via ctx.state.add_obstacle(). Findings via scanner._emit_finding().
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from runtime.workflows.base import StepResult, WorkflowContext, WorkflowStep

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)


class AuthenticateStep(WorkflowStep):
    """Authenticate as User A and User B using operator-supplied configs."""

    name = "authenticate"

    def run(self, ctx: WorkflowContext) -> StepResult:
        ctx.session_a = self._authenticate(ctx.auth_config_a, "user_a", ctx)
        ctx.session_b = self._authenticate(ctx.auth_config_b, "user_b", ctx)
        return StepResult(success=True)  # obstacles (if any) already recorded

    def _authenticate(
        self, auth_config: dict, role: str, ctx: WorkflowContext
    ) -> requests.Session | None:
        from tools.auth_manager import AuthError, AuthManager

        try:
            mgr = AuthManager(auth_config)
            session = mgr.authenticate(ctx.target)
            ctx.slog.info(f"User {role} authenticated")
            return session
        except AuthError:
            obstacle_type = f"auth_failed_{role[-1]}"
            ctx.slog.warning(
                f"Obstacle: {obstacle_type}",
                extra={"step": self.name, "role": role},
            )
            ctx.state.add_obstacle({
                "type": obstacle_type,
                "detected_at": time.time(),
                "step": self.name,
                "recoverable": False,
                "recovery_paths": (
                    ["skip"] if role == "user_a" else ["skip_bola_only_bopla"]
                ),
                "metadata": {"role": role, "error_class": "AuthError"},
            })
            return None


class DiscoverOwnedResourcesStep(WorkflowStep):
    """Discover resources owned by User A via GET-based crawl."""

    name = "discover_resources"

    def run(self, ctx: WorkflowContext) -> StepResult:
        if not ctx.session_a:
            return StepResult(success=True, skipped=True)

        from tools.dual_auth_scanner import DualAuthScanner

        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )
        owned = scanner._discover_owned_resources(ctx.session_a)
        ctx.owned_resources = owned

        total = sum(len(v) for v in owned.values())
        if total == 0:
            # Distinguish "target is down" from "auth worked but no resources".
            # _discover_owned_resources probes 5 endpoints; if all fail at the
            # transport level, the target is unreachable.
            if not scanner._last_response_received:
                ctx.slog.warning(
                    "Obstacle: target_unreachable",
                    extra={"step": self.name, "target": ctx.target},
                )
                ctx.state.add_obstacle({
                    "type": "target_unreachable",
                    "detected_at": time.time(),
                    "step": self.name,
                    "recoverable": False,
                    "recovery_paths": ["skip"],
                    "metadata": {"target": ctx.target, "probed_endpoints": 5},
                })
            else:
                ctx.slog.warning(
                    "Obstacle: no_owned_resources",
                    extra={"step": self.name, "target": ctx.target},
                )
                ctx.state.add_obstacle({
                    "type": "no_owned_resources",
                    "detected_at": time.time(),
                    "step": self.name,
                    "recoverable": False,
                    "recovery_paths": ["skip_bola_run_bopla"],
                    "metadata": {"target": ctx.target, "probed_endpoints": 5},
                })
            ctx.skip_bola = True

        return StepResult(success=True)


class TestBolaStep(WorkflowStep):
    """Test cross-account access: User B accessing User A's resources."""

    name = "test_bola"

    def run(self, ctx: WorkflowContext) -> StepResult:
        if not ctx.session_b or ctx.skip_bola or not ctx.owned_resources:
            return StepResult(success=True, skipped=True)

        from tools.dual_auth_scanner import DualAuthScanner

        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )

        # _test_cross_account_access RETURNS findings but does NOT emit them.
        # The caller is responsible for emitting via scanner._emit_finding().
        raw_findings = scanner._test_cross_account_access(ctx.session_b, ctx.owned_resources)
        for f in raw_findings:
            scanner._emit_finding(f)  # routes through FindingBuilder.add() → emit_finding_callback
        ctx.bola_findings = len(raw_findings)

        # If the step ran but no requests succeeded at the transport level,
        # surface the failure as an obstacle.
        if not scanner._last_response_received and len(raw_findings) == 0:
            ctx.slog.warning(
                "Obstacle: target_unreachable",
                extra={"step": self.name, "phase": "bola_test", "target": ctx.target},
            )
            ctx.state.add_obstacle({
                "type": "target_unreachable",
                "detected_at": time.time(),
                "step": self.name,
                "recoverable": False,
                "recovery_paths": ["skip"],
                "metadata": {"target": ctx.target, "phase": "bola_test"},
            })

        return StepResult(success=True, findings_emitted=len(raw_findings))


class TestBoplaStep(WorkflowStep):
    """Check BOPLA on both sessions — sensitive field exposure."""

    name = "test_bopla"

    def run(self, ctx: WorkflowContext) -> StepResult:
        from tools.dual_auth_scanner import DualAuthScanner

        scanner = DualAuthScanner.for_phase_execution(
            target=ctx.target,
            engagement_id=ctx.engagement_id,
            emit_finding=ctx.emit_finding_callback,
            source_tool="bola_workflow",
            timeout=60,
            rate_limit=0.3,
            verify=True,
        )

        emitted = 0
        if ctx.session_a:
            for f in scanner._check_bopla(ctx.session_a, "user_a"):
                scanner._emit_finding(f)
                emitted += 1
        if ctx.session_b:
            for f in scanner._check_bopla(ctx.session_b, "user_b"):
                scanner._emit_finding(f)
                emitted += 1

        ctx.bopla_findings = emitted
        return StepResult(success=True, findings_emitted=emitted)
