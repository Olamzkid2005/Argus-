"""Egress policy for external tools.

An external CLI tool makes its own connections: nuclei resolves templates and
targets, ffuf dials the fuzz host, sqlmap follows redirects. There is no
request-level hook at our boundary, so the only honest control is a decision
made *before* the process starts:

* a tool whose traffic necessarily leaves the target scope (passive-DNS
  providers, OSINT APIs, vendor update services) cannot meet the demo policy and
  is excluded rather than silently run;
* a tool that is handed several destinations (a URL argument, a fuzz URL, a
  ``--target`` value) has *every* one authorized against the run's scope, not
  just the first one the runner happens to find;
* destinations that belong to the run's own infrastructure (model API, Redis,
  worker) are logged on a separate channel and are never treated as target
  scope — a tool argument that names one is refused, because scanning the
  model endpoint is not "in scope", it is a misdirected request.

Authorization itself stays in ``tools.scope_validator``: this module parses and
classifies destinations and delegates the scope decision to a caller-supplied
``target_check`` (``ToolRunner._scope_block_reason``), so there is still exactly
one place that decides whether a target is authorized.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass

from tools.scope_validator import TargetParseError, parse_target

logger = logging.getLogger(__name__)

#: Destinations of the run's own infrastructure are logged here, never mixed
#: into the target-scope log: an operator must be able to tell "the scan
#: contacted the target" from "the worker talked to its model provider".
infrastructure_logger = logging.getLogger("argus.egress.infrastructure")

#: Tools whose ordinary operation contacts a third party. They cannot meet a
#: target-only egress policy, so they are excluded with a reason instead of
#: being run and silently leaking the engagement.
EXCLUDED_TOOLS: dict[str, str] = {
    "subfinder": "queries third-party passive-DNS providers",
    "amass": "passive enumeration contacts third-party data sources",
    "theharvester": "OSINT providers (search engines, certificate transparency)",
    "shodan": "Shodan API is a third-party service",
    "censys": "Censys API is a third-party service",
    "assetfinder": "queries third-party sources",
    "findomain": "queries third-party certificate-transparency sources",
    "github-subdomains": "queries GitHub's API",
}

#: Flags that make a target-directed tool contact its vendor (templates, update
#: feeds, telemetry). They turn an in-scope run into an out-of-scope one.
UPDATING_FLAGS: dict[str, frozenset[str]] = {
    "nuclei": frozenset({"-update-templates", "-ut", "-update", "-duc"}),
    "wpscan": frozenset({"--update"}),
    "sqlmap": frozenset({"--update"}),
}

#: Flags whose value is a destination but not a scan target (a proxy, resolver
#: or output path). Their values are neither authorized nor refused as targets.
NON_TARGET_DESTINATION_FLAGS: frozenset[str] = frozenset(
    {
        "-o",
        "--output",
        "-output",
        "--proxy",
        "-proxy",
        "--resolver",
        "-resolver",
        "--api-url",
        "--config",
        "-c",
        "-t",
        "--templates",
        "-w",
        "--wordlist",
        "--header",
        "-H",
        # Port specifications are not destinations (and `80-90` parses as a
        # hostname, so they must be skipped explicitly).
        "-p",
        "--ports",
        "--top-ports",
    }
)

#: Flags that name a scan target, where the value may be a bare host.
TARGET_FLAGS: frozenset[str] = frozenset({"-u", "--url", "-host", "--target", "-target"})

#: Tools that accept a bare host as a positional argument (port scanners).
HOST_POSITIONAL_TOOLS: frozenset[str] = frozenset(
    {"nmap", "masscan", "naabu", "rustscan", "nc", "ncat", "telnet"}
)

#: Environment variables naming the run's own infrastructure endpoints.
INFRASTRUCTURE_ENV: dict[str, str] = {
    "OPENAI_BASE_URL": "model API",
    "ARGUS_LLM_ENDPOINT": "model API",
    "ARGUS_LLM_BASE_URL": "model API",
    "REDIS_URL": "redis",
    "CELERY_BROKER_URL": "worker broker",
    "ARGUS_WORKER_URL": "worker",
    "MCP_SERVER_URL": "worker",
    "ARGUS_MCP_URL": "worker",
    "LLM_API_URL": "model API",
}


@dataclass(frozen=True)
class EgressDecision:
    """The egress verdict for one external-tool invocation."""

    allowed: bool
    reason: str
    tool_class: str
    targets: tuple[str, ...] = ()
    infrastructure: tuple[str, ...] = ()


def _normalize_tool(tool: str) -> str:
    return os.path.basename(str(tool or "").strip()).lower()


def infrastructure_hosts() -> dict[str, str]:
    """Approved infrastructure hosts, mapped to what they are.

    Read from the environment because that is where the run's endpoints are
    configured. Used to *classify* a destination, never to authorize a target.
    """
    hosts: dict[str, str] = {}
    for variable, purpose in INFRASTRUCTURE_ENV.items():
        raw = os.environ.get(variable, "").strip()
        if not raw:
            continue
        try:
            parsed = parse_target(raw, require_http_scheme=False)
        except TargetParseError:
            continue
        hosts[parsed.hostname] = purpose
    return hosts


def infrastructure_endpoints() -> dict[tuple[str, int | None], str]:
    """Approved infrastructure endpoints keyed by (host, port).

    Host alone is not enough on a host that runs the lab, Postgres, Redis and a
    model stub on 127.0.0.1: comparing only the hostname classified every
    loopback target as the run's own infrastructure and blocked all scanning.
    """
    endpoints: dict[tuple[str, int | None], str] = {}
    for variable, purpose in INFRASTRUCTURE_ENV.items():
        raw = os.environ.get(variable, "").strip()
        if not raw:
            continue
        try:
            parsed = parse_target(raw, require_http_scheme=False)
        except TargetParseError:
            continue
        endpoints[(parsed.hostname, parsed.port)] = purpose
    return endpoints


def log_infrastructure_destinations() -> list[str]:
    """Log the approved infrastructure endpoints on their own channel.

    Called once per tool invocation: it states what this run is allowed to talk
    to outside the target, separately from what it may scan.
    """
    logged: list[str] = []
    for host, purpose in sorted(infrastructure_hosts().items()):
        infrastructure_logger.info(
            "approved infrastructure destination: %s (%s)", host, purpose
        )
        logged.append(host)
    return logged


def _consider_destination(
    value: str,
    targets: list[str],
    infrastructure: list[str],
    infra_endpoints: dict[tuple[str, int | None], str],
) -> None:
    if not value or value.startswith("-"):
        return
    try:
        parsed = parse_target(value, require_http_scheme=False)
    except TargetParseError:
        return
    if (parsed.hostname, parsed.port) in infra_endpoints:
        if value not in infrastructure:
            infrastructure.append(value)
        return
    if not parsed.host_form or parsed.port is not None:
        if value not in targets:
            targets.append(value)
        return
    # A bare host is a destination only for host-taking tools; callers decide by
    # whether they pass it here at all.
    if value not in targets:
        targets.append(value)


def extract_destinations(args: list[str], tool: str = "") -> tuple[list[str], list[str]]:
    """Every destination named by a tool's arguments, split target vs infra.

    Covers the forms a crafted argument can take: absolute URLs anywhere in the
    argv, ``--url=<value>``, the value after a known target flag, and — for
    host-taking tools — a bare positional host. Values of known non-target flags
    (output paths, proxies, wordlists) are skipped so they are not mistaken for
    scan targets.
    """
    name = _normalize_tool(tool)
    infra_endpoints = infrastructure_endpoints()
    targets: list[str] = []
    infrastructure: list[str] = []
    skip_next = False

    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        lowered = arg.lower()

        if lowered in NON_TARGET_DESTINATION_FLAGS:
            skip_next = True
            continue

        if "=" in arg and lowered.split("=", 1)[0] in TARGET_FLAGS:
            _consider_destination(
                arg.split("=", 1)[1], targets, infrastructure, infra_endpoints
            )
            continue

        if lowered in TARGET_FLAGS:
            if index + 1 < len(args):
                _consider_destination(
                    args[index + 1], targets, infrastructure, infra_endpoints
                )
            skip_next = True
            continue

        if "://" in arg:
            _consider_destination(arg, targets, infrastructure, infra_endpoints)
            continue

        if name in HOST_POSITIONAL_TOOLS and not arg.startswith("-"):
            # A port scanner's positional host is its destination.
            candidate = arg.split("/", 1)[0]
            if _looks_like_host(candidate):
                _consider_destination(
                    candidate, targets, infrastructure, infra_endpoints
                )

    return targets, infrastructure


def _looks_like_host(value: str) -> bool:
    if not value or value.startswith("-"):
        return False
    if "/" in value and "://" not in value:
        return False
    try:
        parse_target(value, require_http_scheme=False)
    except TargetParseError:
        return False
    return True


def authorize_tool_egress(
    tool: str,
    args: list[str],
    target_check: Callable[[str], str | None] | None = None,
) -> EgressDecision:
    """Decide whether this invocation's egress can meet the run's policy.

    Args:
        tool: Tool name or path as handed to the runner.
        args: The exact argv the process would receive.
        target_check: Callable returning a block reason for a target, or None
            when it is authorized. This keeps the scope decision in
            ``tools.scope_validator`` (via ``ToolRunner._scope_block_reason``)
            instead of duplicating it here.

    Returns:
        EgressDecision; ``allowed`` is False with a reason when the process must
        not start.
    """
    name = _normalize_tool(tool)

    exclusion = EXCLUDED_TOOLS.get(name)
    if exclusion:
        return EgressDecision(
            allowed=False,
            reason=(
                f"Tool '{name}' is excluded by the egress policy: {exclusion}. "
                f"Its traffic necessarily leaves the engagement's scope, so it "
                f"cannot be run under the demo's target-only policy."
            ),
            tool_class="third_party",
        )

    updates = sorted(
        {arg for arg in args if arg.lower() in UPDATING_FLAGS.get(name, frozenset())}
    )
    if updates:
        return EgressDecision(
            allowed=False,
            reason=(
                f"Tool '{name}' was given {', '.join(updates)}, which contacts the "
                f"vendor's update service. Update feeds are not part of the "
                f"engagement's scope; install/update templates outside the run."
            ),
            tool_class="vendor_update",
        )

    logged = log_infrastructure_destinations()
    targets, infrastructure = extract_destinations(args, tool)

    if infrastructure:
        return EgressDecision(
            allowed=False,
            reason=(
                "Tool arguments name the run's own infrastructure "
                f"({', '.join(infrastructure)}), which is not a scan target. "
                "Infrastructure destinations are approved separately from target "
                "scope and must never be scanned."
            ),
            tool_class="infrastructure",
            targets=tuple(targets),
            infrastructure=tuple(infrastructure),
        )

    for destination in targets:
        if target_check is None:
            break
        reason = target_check(destination)
        if reason:
            return EgressDecision(
                allowed=False,
                reason=(
                    f"Tool '{name}' would send traffic to {destination}, which the "
                    f"run's scope does not authorize: {reason}"
                ),
                tool_class="target",
                targets=tuple(targets),
            )

    if not targets and logged:
        infrastructure_logger.debug(
            "tool '%s' makes no target-directed request this invocation", name
        )

    return EgressDecision(
        allowed=True,
        reason="target-directed invocation within the run's scope",
        tool_class="target",
        targets=tuple(targets),
    )
