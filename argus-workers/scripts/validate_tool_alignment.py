"""
Tool Alignment Validation Script

Validates that overlapping fields between the Python execution YAMLs
(tools/definitions/*.yaml) and the TUI workflow YAML (tool-definitions.yaml)
remain consistent.

Architecture (ADR-006):
    The two YAML schemas model different domains:
    - Python YAML = Execution domain (command, args, parameters, timeout, risk_level)
    - TUI YAML   = Workflow domain (consumes, provides, scoring.confidence_score)

    They share only a few overlapping fields (name, capabilities, risk_level).
    Neither is "generated" from the other. This script validates only the
    fields that SHOULD agree across both schemas.

Usage:
    python scripts/validate_tool_alignment.py          # print warnings + errors
    python scripts/validate_tool_alignment.py --check  # exit 1 on errors (for CI)
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


_SCRIPT_DIR = Path(__file__).resolve().parent.parent

PYTHON_DEFS_DIR = _SCRIPT_DIR / "tools" / "definitions"
TUI_DEFS_PATH = (
    _SCRIPT_DIR
    / ".."
    / "Argus-Tui"
    / "packages"
    / "opencode"
    / "src"
    / "argus"
    / "workflows"
    / "tool-definitions.yaml"
)


def load_python_definitions() -> dict:
    """Load all Python execution YAML definitions from tools/definitions/.

    Returns:
        Dict mapping tool name -> parsed YAML data.
    """
    if yaml is None:
        print("ERROR: PyYAML is required. Run: pip install pyyaml")
        sys.exit(1)

    tools = {}
    defs_dir = PYTHON_DEFS_DIR
    if not defs_dir.exists():
        print(f"WARNING: Definitions directory not found: {defs_dir}")
        return tools

    for yaml_file in sorted(defs_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            if data and "name" in data:
                tools[data["name"]] = data
        except Exception as e:
            print(f"ERROR: Failed to parse {yaml_file}: {e}")

    return tools


def load_tui_definitions() -> dict:
    """Load the TUI workflow YAML definition.

    Returns:
        Dict mapping tool name -> parsed YAML data.
    """
    if yaml is None:
        print("ERROR: PyYAML is required. Run: pip install pyyaml")
        sys.exit(1)

    path = TUI_DEFS_PATH
    if not path.exists():
        print(f"WARNING: TUI definitions file not found: {path}")
        return {}

    with open(path) as f:
        data = yaml.safe_load(f)

    tools = {}
    for tool in data.get("tools", []):
        if "name" in tool:
            tools[tool["name"]] = tool
    return tools


def validate() -> list[str]:
    """Check consistency between Python execution YAMLs and TUI workflow YAML.

    Validates only fields that SHOULD agree:
    - Tool existence (tools present in both where expected)
    - Capability names match
    - Risk level classification is consistent

    Returns:
        List of error messages. Empty list means no issues found.
    """
    errors: list[str] = []
    python_tools = load_python_definitions()
    tui_tools = load_tui_definitions()

    if not python_tools:
        errors.append("No Python tool definitions found — cannot validate")
        return errors

    if not tui_tools:
        errors.append("No TUI tool definitions found — cannot validate")
        return errors

    python_names = set(python_tools.keys())
    tui_names = set(tui_tools.keys())
    common_names = python_names & tui_names

    if not common_names:
        errors.append("No overlapping tool names between Python and TUI definitions")
        return errors

    for name in sorted(common_names):
        py = python_tools[name]
        ts = tui_tools[name]

        # Validate capability names match
        py_caps = set(_normalize_capabilities(py.get("capabilities", [])))
        ts_caps = set(ts.get("capabilities", []))

        if py_caps != ts_caps:
            only_py = py_caps - ts_caps
            only_ts = ts_caps - py_caps
            if only_py:
                errors.append(
                    f"CAPABILITY_MISMATCH [{name}]: in Python YAML only: {sorted(only_py)}"
                )
            if only_ts:
                errors.append(
                    f"CAPABILITY_MISMATCH [{name}]: in TUI YAML only: {sorted(only_ts)}"
                )

        # Validate risk level classification consistency
        py_risky = _is_destructive(py)
        ts_risky = ts.get("destructive", False)
        if py_risky != ts_risky:
            errors.append(
                f"RISK_MISMATCH [{name}]: Python risk_level={py.get('risk_level', 'unknown')}, "
                f"TUI destructive={ts_risky}"
            )

    return errors


def _normalize_capabilities(caps: list) -> list[str]:
    """Normalize capability names from Python YAML (may use '-' or '_' variants)."""
    normalized = []
    for c in caps:
        if isinstance(c, str):
            normalized.append(c.lower().replace("-", "_"))
    return normalized


def _is_destructive(py_def: dict) -> bool:
    """Determine if a Python tool definition is considered destructive/risky."""
    risk = py_def.get("risk_level", "").lower()
    return risk in ("high", "critical")


def main():
    parser = argparse.ArgumentParser(description="Validate tool definition alignment")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 1 if any errors found (for CI)",
    )
    args = parser.parse_args()

    errors = validate()

    if errors:
        print("Tool alignment validation FAILED:")
        for err in errors:
            print(f"  ❌ {err}")
        if args.check:
            sys.exit(1)
    else:
        print(
            "Tool alignment validation PASSED — all overlapping fields are consistent"
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
