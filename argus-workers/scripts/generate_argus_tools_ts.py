#!/usr/bin/env python3
"""Generate native OpenCode tool wrappers from the canonical tool registry.

Every executable entry in ``tool_definitions.TOOLS`` (YAML definitions plus
inline policy overrides) becomes a first-class native tool the TUI LLM calls
exactly like ``grep`` or ``glob``: a name, a description and a JSON Schema —
instead of a bare ``bash`` invocation the model has to compose itself.

Execution mirrors ``agent/tool_arguments.build_tool_argv`` (static
``default_args`` first, then each declared parameter's flag and value in
declaration order; booleans are switches; flag-less parameters stay
positional) so the TypeScript runner can never disagree with the Python
dispatch about how a tool is invoked.

Usage:
    python scripts/generate_argus_tools_ts.py                # write the generated module
    python scripts/generate_argus_tools_ts.py --check         # CI mode: verify no drift
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKERS_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(WORKERS_DIR))

from tool_definitions import TOOLS, is_pipeline_step  # noqa: E402

REPO_ROOT = WORKERS_DIR.parent
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "Argus-Tui"
    / "packages"
    / "opencode"
    / "src"
    / "tool"
    / "argus-tools.generated.ts"
)


def _ts_string(value: str) -> str:
    """Render a TS string literal (JSON quoting is valid TS)."""
    return json.dumps(value, ensure_ascii=False)


def _var_name(tool_id: str) -> str:
    parts = [p for p in tool_id.replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) + "Tool"


def _schema_type(param) -> str:
    if isinstance(param.default, bool):
        return "Schema.Boolean"
    if isinstance(param.default, int):
        return "Schema.Number"
    return "Schema.String"


def _is_launcher(tool) -> bool:
    return any(str(a).endswith("run_agent_tool.py") for a in (tool.default_args or []))


def executable_tools():
    """Registry entries that run as a subprocess: phased, not a pipeline step."""
    return sorted(
        (
            tool
            for tool in TOOLS.values()
            if tool.phases and not is_pipeline_step(tool.name)
        ),
        key=lambda t: t.name,
    )


def _emit_spec(tool) -> str:
    tool_id = tool.name.replace("_", "-")
    var = _var_name(tool_id)
    command = tool.binary or tool.name
    lines = [f"export const {var}Spec: RegistryToolSpec = {{"]
    lines.append(f"    id: {_ts_string(tool_id)},")
    lines.append(f"    toolName: {_ts_string(tool.name)},")
    lines.append(f"    command: {_ts_string(command)},")
    args = ", ".join(_ts_string(str(a)) for a in (tool.default_args or []))
    lines.append(f"    args: [{args}],")
    param_specs = ", ".join(
        f"{{ name: {_ts_string(p.name)}, flag: "
        f"{_ts_string(p.flag) if p.flag else 'null'} }}"
        for p in tool.parameters
    )
    lines.append(f"    params: [{param_specs}],")
    lines.append(f"    timeoutMs: {int(tool.timeout) * 1000},")
    env = ", ".join(_ts_string(str(v)) for v in (tool.required_env or ()))
    lines.append(f"    requiredEnv: [{env}],")
    phases = ", ".join(_ts_string(str(p)) for p in (tool.phases or []))
    lines.append(f"    phases: [{phases}],")
    lines.append(f"    risk: {_ts_string(str(tool.risk_level or 'low'))},")
    lines.append("  }")
    return "\n".join(lines)


def _emit_tool(tool) -> str:
    tool_id = tool.name.replace("_", "-")
    var = _var_name(tool_id)
    lines = [f"const {var}Parameters = Schema.Struct({{"]

    for param in tool.parameters:
        schema = _schema_type(param)
        desc = _ts_string(param.description or param.name)
        # Quote every key: registry names may contain dashes (attacker-username).
        key = _ts_string(param.name)
        if param.required:
            lines.append(f"    {key}: {schema}.annotate({{ description: {desc} }}),")
        else:
            lines.append(
                f"    {key}: Schema.optional({schema}.annotate({{ description: {desc} }})),"
            )
    lines.append("  })")
    lines.append(f"export const {var} = Tool.define(")
    lines.append(f"  {_ts_string(tool_id)},")
    lines.append("  Effect.gen(function* () {")
    lines.append("    return {")
    lines.append(f"      description: {_ts_string(tool.description)},")
    lines.append(f"      parameters: {var}Parameters,")
    lines.append(
        f"      execute: (params: Schema.Schema.Type<typeof {var}Parameters>, ctx: Tool.Context) =>"
    )
    lines.append("        Effect.gen(function* () {")
    lines.append("          const result = yield* Effect.sync(() =>")
    lines.append(f"            runRegistryInvocation({var}Spec, params as Record<string, unknown>),")
    lines.append("          )")
    lines.append(f"          return formatRegistryResult({var}Spec.id, result)")
    lines.append("        }).pipe(Effect.orDie),")
    lines.append("    }")
    lines.append("  }),")
    lines.append(")")
    return "\n".join(lines)


HEADER = [
    "/**",
    " * {what}",
    " *",
    " * AUTO-GENERATED — DO NOT EDIT BY HAND.",
    " *",
    " * Generated by: argus-workers/scripts/generate_argus_tools_ts.py",
    " * Source:       tool_definitions.TOOLS (tools/definitions/*.yaml + inline policy)",
    " * Tools:          {count} definitions",
]


def _header(what: str, count: int) -> list[str]:
    return [line.format(what=what, count=count) for line in HEADER]


def generate(output_path: str) -> str:
    tools = executable_tools()
    seen_ids: set[str] = set()
    seen_vars: set[str] = set()
    for tool in tools:
        tool_id = tool.name.replace("_", "-")
        var = _var_name(tool_id)
        if tool_id in seen_ids or var in seen_vars:
            raise ValueError(f"generated id/var collision for tool {tool.name!r}")
        seen_ids.add(tool_id)
        seen_vars.add(var)

    # Pure-data specs module: zero runtime imports, so permission rulesets
    # (security-roles.ts) can consume it without joining the tool/agent
    # import cycle.
    specs_path = Path(output_path).parent / "argus-tools.specs.generated.ts"
    spec_chunks = _header(
        "Executable Argus registry tool specs (pure data, no runtime imports).", len(tools)
    ) + [
        " */",
        'import type { RegistryToolSpec } from "./argus-tools"',
        "",
    ]
    for tool in tools:
        spec_chunks += ["", _emit_spec(tool)]
    spec_chunks += [
        "",
        "/** Every executable tool's spec, for permission rulesets. */",
        "export const REGISTRY_TOOL_SPECS: readonly RegistryToolSpec[] = [",
        *[f"  {_var_name(t.name.replace('_', '-'))}Spec," for t in tools],
        "]",
        "",
    ]
    specs_path.write_text("\n".join(spec_chunks), encoding="utf-8")

    chunks = _header("Native OpenCode wrappers for every executable Argus registry tool.", len(tools)) + [
        " *",
        " * The TUI LLM calls these exactly like grep/glob: a name, a description",
        " * and a JSON Schema. Execution mirrors agent/tool_arguments.build_tool_argv",
        " * (see runRegistryInvocation in ./argus-tools), so the native surface can",
        " * never disagree with the worker about how a tool is invoked.",
        " */",
        'import { Effect, Schema } from "effect"',
        'import * as Tool from "./tool"',
        'import { formatRegistryResult, runRegistryInvocation } from "./argus-tools"',
        'import {',
        *[
            f"  {_var_name(t.name.replace('_', '-'))}Spec,"
            for t in tools
        ],
        '} from "./argus-tools.specs.generated"',
        "",
    ]
    for tool in tools:
        chunks.append("")
        chunks.append(_emit_tool(tool))

    tool_refs = [f"  {_var_name(t.name.replace('_', '-'))}," for t in tools]
    chunks += [
        "",
        "/** Every generated wrapper, for registration in ./registry. */",
        "export const REGISTRY_GENERATED_TOOLS = [",
        *tool_refs,
        "] as const",
        "",
    ]
    content = "\n".join(chunks)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


GENERATED_FILES = ("argus-tools.generated.ts", "argus-tools.specs.generated.ts")


def check(output_path: str) -> bool:
    import tempfile

    out = Path(output_path)
    if out.name != GENERATED_FILES[0]:
        print(f"[FAIL] unexpected output name: {out.name}", file=sys.stderr)
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        generate(str(Path(tmpdir) / out.name))
        ok = True
        for name in GENERATED_FILES:
            generated = (Path(tmpdir) / name).read_text(encoding="utf-8")
            existing = (out.parent / name).read_text(encoding="utf-8")
            if generated == existing:
                print(f"[PASS] {name} is consistent with the tool registry.")
            else:
                print(
                    f"[FAIL] {name} has drifted from the tool registry.\n"
                    "       Run: python argus-workers/scripts/generate_argus_tools_ts.py",
                    file=sys.stderr,
                )
                ok = False
        return ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate native TUI tool wrappers from the tool registry"
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="CI mode: verify no drift")
    args = parser.parse_args()
    if args.check:
        sys.exit(0 if check(args.output) else 1)
    generate(args.output)
    print(f"Generated {args.output} from {len(executable_tools())} registry tools.")


if __name__ == "__main__":
    main()
