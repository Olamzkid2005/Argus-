"""Build a tool's CLI argv from the canonical tool definitions.

The agent used to forward a bare target to every binary: ``args =
[target] + kwargs.pop("args", [])``. Two things went wrong with that:

* a named parameter the model chose and the registry validated (for example
  arjun ``threads``) was accepted and then silently dropped, so the tool ran
  with defaults while the audit log said otherwise;
* tools whose target is a flag (``arjun -u``, ``nuclei -u``) received the URL
  as a positional argument, which they do not accept.

``build_tool_argv`` mirrors the MCP server's command builder: the definition's
static ``default_args`` first, then every declared parameter's flag and value
in declaration order. A parameter without a flag (``nmap target``) stays
positional. Parameters absent from the call are not invented — their declared
``default`` is documentation for the planner, exactly as in the MCP server.
"""

from __future__ import annotations

_MISSING = object()


def build_tool_argv(
    tool_name: str,
    target: str = "",
    parameters: dict | None = None,
) -> list[str]:
    """Return the argv for ``tool_name`` built from its definition.

    Args:
        tool_name: Name as registered in ``tool_definitions.TOOLS``.
        target: The engagement target, used for the definition's ``target``
            parameter (or appended for a definition that declares none).
        parameters: Named parameters chosen by the caller. Values are stringified;
            booleans become switches.

    Unknown names are ignored: the registry rejects them before dispatch, and a
    definition that does not exist must not gain arguments from the model.
    """
    from tool_definitions import TOOLS

    named = dict(parameters or {})
    tool = TOOLS.get(tool_name)
    if tool is None:
        return [str(target)] if target else []

    argv = [str(arg) for arg in tool.default_args]
    declared = {param.name for param in tool.parameters}

    for param in tool.parameters:
        if param.name == "target":
            value = named.pop("target", target if target else _MISSING)
        else:
            value = named.pop(param.name, _MISSING)

        if value is _MISSING or value is None:
            continue

        # Booleans are switches: ``--deep-domxss True`` is not a CLI argument.
        if isinstance(value, bool):
            if value and param.flag:
                argv.append(param.flag)
            continue

        if param.flag:
            argv.append(param.flag)
        argv.append(str(value))

    # A definition without a target parameter still needs the target — several
    # tools take it positionally without declaring it in the YAML schema.
    if target and "target" not in declared:
        argv.append(str(target))

    return argv
