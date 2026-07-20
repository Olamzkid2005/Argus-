#!/usr/bin/env python3
"""
Tool Registry Drift Detection — cross-reference TS and Python tool definitions.

Usage:
    # From repo root (default paths)
    python argus-workers/scripts/check_tool_registry_drift.py

    # With explicit paths
    python argus-workers/scripts/check_tool_registry_drift.py \
        --python-tools argus-workers/tool_definitions.py \
        --ts-yaml Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml

    # Quiet mode (exit codes only)
    python argus-workers/scripts/check_tool_registry_drift.py --quiet

Exit codes:
    0 always — drift may be intentional (different schema, different purpose).
    This script is informational, not a CI gate.

Architecture:
    The TS and Python registries are INTENTIONALLY SEPARATE (different schema,
    different purpose: planning vs execution). Drift is expected and normal.
    This script reports drift so developers can decide whether to sync.

See: docs/tool-registry-reconciliation-report.md
"""

import argparse
import ast
import os
import re
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    """Find the repo root by walking up from script location."""
    script_dir = Path(__file__).resolve().parent
    if script_dir.name == "scripts":
        return script_dir.parent.parent
    return script_dir.parent  # fallback


def _extract_tool_names_from_ast(filepath: str | Path) -> set[str]:
    """Extract tool names from a Python file by parsing AST for _register() calls.

    Looks for calls matching: _register(ToolDefinition(name="xxx", ...))

    This avoids importing the module entirely — no side effects, no circular
    import issues, no dependency on importlib.

    Args:
        filepath: Path to a Python file containing _register() calls.

    Returns:
        Set of registered tool names.
    """
    path = Path(filepath)
    if not path.exists():
        return set()

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    names: set[str] = set()

    for node in ast.walk(tree):
        # Match: _register(ToolDefinition(name="xxx", ...))
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        if not isinstance(func, ast.Name) or func.id != "_register":
            continue
        if not call.args:
            continue
        first_arg = call.args[0]
        if not isinstance(first_arg, ast.Call):
            continue
        # Check if it's a ToolDefinition(...) call
        td_func = first_arg.func
        if not isinstance(td_func, ast.Name) or td_func.id != "ToolDefinition":
            continue
        # Find the 'name' keyword argument
        for kw in first_arg.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                names.add(kw.value.value)
                break

    return names


def _extract_tool_names_from_star_import(filepath: str | Path) -> set[str]:
    """Extract tool names from a file that does 'from _generated_tools import *'.

    Follows the star import to the generated file and parses its _register() calls.
    Also handles the _register() calls inline in the file itself.

    Args:
        filepath: Path to a Python file (typically tool_definitions.py).

    Returns:
        Combined set of registered tool names from all sources.
    """
    path = Path(filepath)
    if not path.exists():
        return set()

    names: set[str] = set()

    # First, extract from the file itself
    names.update(_extract_tool_names_from_ast(path))

    # Then, check for 'from _generated_tools import *' and follow it
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return names

    # Look for star import of _generated_tools
    for match in re.finditer(
        r"from\s+_generated_tools\s+import\s+\*", text
    ):
        generated_path = path.parent / "_generated_tools.py"
        if generated_path.exists():
            names.update(_extract_tool_names_from_ast(generated_path))

    return names


def parse_python_tools(tool_definitions_path: str) -> set[str]:
    """Parse Python tool_definitions.py and extract all registered tool names.

    Uses AST parsing — no module import, no side effects, no circular import issues.
    Follows 'from _generated_tools import *' to capture all registrations.

    Args:
        tool_definitions_path: Path to tool_definitions.py.

    Returns:
        Set of registered tool names.
    """
    abs_path = Path(tool_definitions_path).resolve()
    if not abs_path.exists():
        print(f"  WARNING: Python tools file not found at {abs_path}")
        return set()

    return _extract_tool_names_from_star_import(abs_path)


def parse_ts_yaml(ts_yaml_path: str) -> set[str]:
    """Parse TS tool-definitions.yaml and extract all tool names.

    Prefers YAML parsing (PyYAML) but falls back to regex if the package
    is not available.

    Args:
        ts_yaml_path: Path to tool-definitions.yaml.

    Returns:
        Set of tool names defined in the YAML.
    """
    abs_path = Path(ts_yaml_path).resolve()
    if not abs_path.exists():
        print(f"  WARNING: TS YAML not found at {abs_path}")
        return set()

    text = abs_path.read_text(encoding="utf-8")

    # Try YAML parser first
    try:
        import yaml

        data = yaml.safe_load(text)
        if data and "tools" in data:
            return {tool.get("name", "") for tool in data["tools"] if tool.get("name")}
    except ImportError:
        pass  # PyYAML not installed, fall through to regex
    except Exception:
        pass  # Malformed YAML, fall through to regex

    # Regex fallback: match lines like "  - name: nuclei"
    names = re.findall(r"^\s+-\s+name:\s+(\S+)", text, re.MULTILINE)
    return set(names)


def check_drift(
    python_tools: set[str],
    ts_tools: set[str],
    quiet: bool = False,
) -> int:
    """Compare two tool registries and report differences.

    Args:
        python_tools: Set of tool names from the Python registry.
        ts_tools: Set of tool names from the TS registry.
        quiet: If True, only print summary counts.

    Returns:
        0 always — drift may be intentional.
    """
    only_python = python_tools - ts_tools
    only_ts = ts_tools - python_tools
    both = python_tools & ts_tools

    sep = "=" * 60
    print(f"\n{sep}")
    print("  Tool Registry Drift Report")
    print(f"{sep}")
    print(f"  Python tools:   {len(python_tools)}")
    print(f"  TS tools:       {len(ts_tools)}")
    print(f"  In both:        {len(both)}")
    print(f"  Python-only:    {len(only_python)}")
    print(f"  TS-only:        {len(only_ts)}")
    print(f"{sep}\n")

    drift_found = bool(only_python or only_ts)

    if only_python and not quiet:
        print("Tools in Python but NOT in TS YAML:")
        print("-" * 40)
        for name in sorted(only_python):
            print(f"  * {name}")
        print()

    if only_ts and not quiet:
        print("Tools in TS YAML but NOT in Python:")
        print("-" * 40)
        for name in sorted(only_ts):
            print(f"  * {name}")
        print()

    if not drift_found:
        print("  No drift detected -- registrations are in sync.")
    else:
        print(
            "  NOTE: Drift may be INTENTIONAL -- the two registries serve\n"
            "  different purposes (planning vs execution). Review the lists\n"
            "  above to decide whether to sync.\n"
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Check for drift between Python and TS tool registries",
        epilog="Exit 0 regardless -- drift may be intentional.",
    )

    parser.add_argument(
        "--python-tools",
        default=None,
        help="Path to Python tool_definitions.py (default: auto-detect from repo root)",
    )
    parser.add_argument(
        "--ts-yaml",
        default=None,
        help="Path to TS tool-definitions.yaml (default: auto-detect from repo root)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only print summary counts (no detailed diffs)",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = _resolve_project_root()

    # Auto-detect paths relative to repo root
    if args.python_tools:
        py_path = args.python_tools
    else:
        py_path = str(repo_root / "argus-workers" / "tool_definitions.py")

    if args.ts_yaml:
        ts_path = args.ts_yaml
    else:
        ts_path = str(
            repo_root
            / "Argus-Tui"
            / "packages"
            / "opencode"
            / "src"
            / "argus"
            / "workflows"
            / "tool-definitions.yaml"
        )

    # Validate paths
    if not os.path.exists(py_path):
        print(f"ERROR: Python tools file not found: {py_path}")
        print("Use --python-tools to specify the correct path.")
        return 1

    if not os.path.exists(ts_path):
        print(f"WARNING: TS YAML file not found: {ts_path}")
        print("Use --ts-yaml to specify the correct path.")
        print("Continuing with empty TS set...\n")

    print(f"Python source: {py_path}")
    print(f"TS source:     {ts_path}")
    print()

    python_tools = parse_python_tools(py_path)
    ts_tools = parse_ts_yaml(ts_path)

    return check_drift(python_tools, ts_tools, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
