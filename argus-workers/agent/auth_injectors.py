"""
Tool-specific auth injection functions.

Each injector takes the agent's args list and AuthContext, and returns
a modified args list with auth parameters injected.

Keeps tool-specific auth knowledge out of the agent and the tool wrappers.
"""

from __future__ import annotations

from collections.abc import Callable

from agent.auth_context import AuthContext

# ── Type alias ──

InjectorFn = Callable[[list[str], AuthContext], list[str]]


# ── Individual injectors ──


def inject_sqlmap_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies for sqlmap via ``--cookie`` flag."""
    args = list(args)  # don't mutate original
    if ctx.cookie_string and not _has_cookie_flag(args):
        args.extend(["--cookie", ctx.cookie_string])
    return args


def inject_dalfox_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies and auth headers for dalfox."""
    args = list(args)
    if ctx.cookie_string and not _has_cookie_flag(args):
        args.extend(["--cookie", ctx.cookie_string])
    if ctx.authorization:
        args.extend(["--header", ctx.authorization])
    return args


def inject_nuclei_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies as ``-H "Cookie: ..."`` header for nuclei."""
    args = list(args)
    if ctx.cookie_string and not _has_header_flag(args, "Cookie"):
        args.extend(["-H", f"Cookie: {ctx.cookie_string}"])
    if ctx.authorization and not _has_header_flag(args, "Authorization"):
        auth_value = ctx.authorization
        if not auth_value.startswith("Authorization:"):
            auth_value = f"Authorization: {auth_value}"
        args.extend(["-H", auth_value])
    return args


def inject_ffuf_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies for ffuf via ``-b`` flag."""
    args = list(args)
    if ctx.cookie_string and not _has_cookie_flag(args):
        args.extend(["-b", ctx.cookie_string])
    return args


def inject_nikto_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies for nikto via ``-Cookie`` flag."""
    args = list(args)
    if ctx.cookie_string:
        args.extend(["-Cookie", ctx.cookie_string])
    return args


def inject_gospider_auth(args: list[str], ctx: AuthContext) -> list[str]:
    """Inject cookies for gospider via ``--cookie`` flag."""
    args = list(args)
    if ctx.cookie_string and not _has_cookie_flag(args):
        args.extend(["--cookie", ctx.cookie_string])
    return args


# ── Registry ──

TOOL_AUTH_INJECTORS: dict[str, InjectorFn] = {
    "sqlmap": inject_sqlmap_auth,
    "dalfox": inject_dalfox_auth,
    "nuclei": inject_nuclei_auth,
    "ffuf": inject_ffuf_auth,
    "nikto": inject_nikto_auth,
    "gospider": inject_gospider_auth,
}


def inject_auth(
    tool_name: str,
    args: list[str],
    ctx: AuthContext | None,
) -> list[str]:
    """Apply auth injection for a tool if an injector exists and auth is available.

    Args:
        tool_name: Name of the tool to inject auth for.
        args: Current CLI argument list.
        ctx: AuthContext or None.

    Returns:
        Modified args list with auth parameters injected (or unchanged).
    """
    if ctx is None or not ctx.is_authenticated():
        return args
    injector = TOOL_AUTH_INJECTORS.get(tool_name)
    if injector:
        return injector(args, ctx)
    return args


# ── Helpers ──


def _has_cookie_flag(args: list[str]) -> bool:
    """Check if args already contain a cookie flag (``--cookie``, ``-b``, ``-Cookie``).

    Prevents double-injection when the LLM or user already specified cookies.
    """
    for i, arg in enumerate(args):
        if arg in ("--cookie", "-b", "-Cookie") and i + 1 < len(args):
            return True
    return False


def _has_header_flag(args: list[str], header_name: str) -> bool:
    """Check if args already contain a ``-H`` header with the given name.

    Prevents double-injection of the same header type.
    """
    prefix = header_name.lower() + ":"
    for i, arg in enumerate(args):
        if arg == "-H" and i + 1 < len(args) and args[i + 1].lower().startswith(prefix):
            return True
    return False
