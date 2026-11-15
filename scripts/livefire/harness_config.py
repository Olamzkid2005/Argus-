#!/usr/bin/env python3
"""Validate the live-fire harness' swarm opt-in before anything is dispatched.

The runner used to hardcode ``aggressiveness: moderate`` and ``scan_mode:
standard``; exporting AGGRESSIVENESS or SCAN_MODE changed nothing, and a run that
never activated a specialist still produced a green verdict. This module is the
single, tested place that turns the environment into the effective payload:

    AGGRESSIVENESS=high        moderate by default; elevated is explicit
    SCAN_MODE=swarm            standard by default
    REQUIRE_SWARM=1            fail the run unless the required specialists
                               activate, execute a tool and complete cleanly
    REQUIRED_SPECIALISTS=idor,auth,api

Malformed values fail here, before dispatch. ``--json`` prints the effective
configuration that the runner saves next to the run's artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Mapping

AGGRESSIVENESS_LEVELS = ("low", "moderate", "high", "extreme")
SCAN_MODES = ("standard", "agent", "swarm", "deterministic")
SPECIALISTS = ("idor", "auth", "api")
TRUE_VALUES = ("1", "true", "yes", "on")
FALSE_VALUES = ("0", "false", "no", "off")


class ConfigError(ValueError):
    """A harness option that must stop the run before dispatch."""


@dataclass(frozen=True)
class HarnessOptions:
    aggressiveness: str
    scan_mode: str
    require_swarm: bool
    required_specialists: tuple[str, ...]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["required_specialists"] = list(self.required_specialists)
        return data


def _parse_bool(name: str, raw: str) -> bool:
    value = (raw or "").strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES or value == "":
        return False
    raise ConfigError(f"{name} must be 1/0, got {raw!r}")


def resolve_options(env: Mapping[str, str] | None = None) -> HarnessOptions:
    """Validate the environment and return the effective harness options."""
    env = os.environ if env is None else env

    aggressiveness = (env.get("AGGRESSIVENESS") or "moderate").strip().lower()
    if aggressiveness not in AGGRESSIVENESS_LEVELS:
        raise ConfigError(
            f"AGGRESSIVENESS must be one of {', '.join(AGGRESSIVENESS_LEVELS)}, "
            f"got {aggressiveness!r}"
        )

    scan_mode = (env.get("SCAN_MODE") or "standard").strip().lower()
    if scan_mode not in SCAN_MODES:
        raise ConfigError(
            f"SCAN_MODE must be one of {', '.join(SCAN_MODES)}, got {scan_mode!r}"
        )

    require_swarm = _parse_bool("REQUIRE_SWARM", env.get("REQUIRE_SWARM", ""))

    raw_specialists = (env.get("REQUIRED_SPECIALISTS") or "").strip()
    if raw_specialists:
        requested = tuple(
            item.strip().lower() for item in raw_specialists.split(",") if item.strip()
        )
        unknown = [item for item in requested if item not in SPECIALISTS]
        if unknown:
            raise ConfigError(
                f"REQUIRED_SPECIALISTS contains unknown specialist(s): {', '.join(unknown)}"
            )
        duplicates = {item for item in requested if requested.count(item) > 1}
        if duplicates:
            raise ConfigError(
                f"REQUIRED_SPECIALISTS repeats: {', '.join(sorted(duplicates))}"
            )
        required_specialists = requested
    else:
        required_specialists = SPECIALISTS if require_swarm else ()

    if required_specialists and not require_swarm:
        raise ConfigError("REQUIRED_SPECIALISTS requires REQUIRE_SWARM=1")

    if require_swarm:
        if aggressiveness not in ("high", "extreme"):
            raise ConfigError(
                "REQUIRE_SWARM=1 needs AGGRESSIVENESS=high (or extreme); "
                "moderate never reaches the specialist gate"
            )
        if scan_mode == "deterministic":
            raise ConfigError(
                "REQUIRE_SWARM=1 needs an agent route; SCAN_MODE=deterministic "
                "skips the specialists"
            )

    return HarnessOptions(
        aggressiveness=aggressiveness,
        scan_mode=scan_mode,
        require_swarm=require_swarm,
        required_specialists=tuple(required_specialists),
    )


def effective_config(
    options: HarnessOptions,
    *,
    target_url: str,
    engagement_id: str,
    scope: dict,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Everything needed to reproduce this run's effective job."""
    env = os.environ if env is None else env
    return {
        "options": options.to_dict(),
        "target_url": target_url,
        "engagement_id": engagement_id,
        "scope": scope,
        "feature_flags": {
            key: value for key, value in sorted(env.items()) if key.startswith("ARGUS_FF_")
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate live-fire harness opt-ins")
    parser.add_argument("--json", action="store_true", help="print the effective options")
    parser.add_argument("--target-url", default="")
    parser.add_argument("--engagement-id", default="")
    parser.add_argument("--scope", default="{}", help="JSON scope object")
    args = parser.parse_args(argv)

    try:
        options = resolve_options()
    except ConfigError as exc:
        print(f"harness_config: {exc}", file=sys.stderr)
        return 2

    if not args.json:
        print(
            f"aggressiveness={options.aggressiveness} "
            f"scan_mode={options.scan_mode} "
            f"require_swarm={int(options.require_swarm)} "
            f"required_specialists={','.join(options.required_specialists)}"
        )
        return 0

    try:
        scope = json.loads(args.scope)
    except json.JSONDecodeError as exc:
        print(f"harness_config: --scope is not JSON: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            effective_config(
                options,
                target_url=args.target_url,
                engagement_id=args.engagement_id,
                scope=scope,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
