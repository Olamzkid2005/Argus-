#!/usr/bin/env python3
"""
Generate _generated_tools.py from YAML single source of truth.

Reads all tool definitions from tools/definitions/*.yaml and generates
_generated_tools.py — a module that tool_definitions.py imports so that
the YAML files remain the single source of truth.

Usage:
    python scripts/generate_tool_defs.py               # write _generated_tools.py
    python scripts/generate_tool_defs.py --check        # verify no drift (CI mode)
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Capability → phase mapping
# ---------------------------------------------------------------------------
CAPABILITY_TO_PHASES: dict[str, list[str]] = {
    "web_recon": ["recon"],
    "port_scanning": ["recon"],
    "technology_detection": ["recon"],
    "content_discovery": ["recon", "scan"],
    "api_probing": ["scan"],
    "auth_detection": ["scan"],
    "credential_analysis": ["scan"],
    "vulnerability_scanning": ["scan", "deep_scan"],
    "template_scanning": ["scan", "deep_scan"],
    "browser_verification": ["scan", "deep_scan"],
    "sqli_detection": ["scan", "deep_scan"],
    "database_exfiltration": ["deep_scan"],
    "http_probe": ["recon"],
    "graphql_assessment": ["scan"],
    "api_docs_analysis": ["scan"],
    "jwt_analysis": ["scan"],
    "ssrf_check": ["scan", "deep_scan"],
    "command_injection": ["scan", "deep_scan"],
    "security_analysis": ["analyze"],
    "secret_detection": ["repo_scan"],
    "sast": ["repo_scan"],
    "sca": ["repo_scan"],

    "cloud_enum": ["recon", "scan"],
    "s3_scanning": ["scan"],
    "report_generation": ["report"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _indent(text: str, level: int = 1) -> str:
    return "    " * level + text


def _build_parameters(params: list[dict]) -> str:
    if not params:
        return "[]"
    lines = ["["]
    for p in params:
        name = p.get("name", "unknown")
        desc = p.get("description", "").replace('"', '\\"')
        required = p.get("required", False)
        flag = p.get("flag")
        default = p.get("default")
        enum_vals = p.get("enum")

        args = f'name="{name}", description="{desc}"'
        if required:
            args += ", required=True"
        if flag:
            args += f', flag="{flag}"'
        if default is not None:
            import json

            args += f", default={json.dumps(default)}"
        if enum_vals:
            vals = ", ".join(f'"{v}"' for v in enum_vals)
            args += f", enum=[{vals}]"

        lines.append(_indent(f"ToolParameter({args}),"))
    lines.append(_indent("]", level=0))
    return "\n".join(lines)


def _build_requires(yaml_data: dict) -> str:
    requires = yaml_data.get("requires", {}) or {}
    if not requires:
        return ""

    tech = requires.get("tech_contains", [])
    signals = requires.get("recon_signals", [])
    scheme = requires.get("target_scheme")

    args = []
    if tech:
        tech_str = ", ".join(f'"{t}"' for t in tech)
        args.append(f"tech_contains=[{tech_str}]")
    if signals:
        sig_str = ", ".join(f'"{s}"' for s in signals)
        args.append(f"recon_signals=[{sig_str}]")
    if scheme:
        args.append(f'target_scheme="{scheme}"')

    if not args:
        return ""
    return f"ToolRequires({', '.join(args)})"


def _build_tool_registration(data: dict) -> str:
    name = data["name"]
    description = data.get("description", "").replace('"', '\\"')
    command = data.get("command", "")
    args = data.get("args", [])
    params = data.get("parameters", [])
    capabilities = data.get("capabilities", [])
    signal_quality_str = (data.get("signal_quality") or "").upper()
    priority = data.get("priority")
    cost = data.get("cost")
    timeout = data.get("timeout", 300)
    requires_obj = _build_requires(data)

    # Phases: use explicit YAML phases if provided, otherwise derive from capabilities
    phases: list[str] = data.get("phases", [])
    if not phases:
        for cap in capabilities:
            mapped = CAPABILITY_TO_PHASES.get(cap)
            if mapped:
                for p in mapped:
                    if p not in phases:
                        phases.append(p)
    if not phases:
        phases = ["scan"]

    lines = ["_register(ToolDefinition("]
    lines.append(_indent(f'name="{name}",'))
    lines.append(_indent(f'description="{description}",'))
    if command and command != name:
        lines.append(_indent(f'binary="{command}",'))
    phases_str = ", ".join(f'"{p}"' for p in phases)
    lines.append(_indent(f"phases=[{phases_str}],"))
    if args:
        args_str = ", ".join(f'"{a}"' for a in args)
        lines.append(_indent(f"default_args=[{args_str}],"))
    params_str = _build_parameters(params)
    lines.append(_indent(f"parameters={params_str},"))
    lines.append(_indent(f"timeout={timeout},"))
    if signal_quality_str in ("CONFIRMED", "PROBABLE", "CANDIDATE"):
        lines.append(_indent(f"signal_quality=SignalQuality.{signal_quality_str},"))
    if requires_obj:
        lines.append(_indent(f"requires={requires_obj},"))
    if priority is not None:
        lines.append(_indent(f"priority={priority},"))
    if cost:
        lines.append(_indent(f'cost="{cost}",'))
    risk_level = data.get("risk_level") or ("medium" if cost == "high" else "low")
    lines.append(_indent(f'risk_level="{risk_level}",'))
    lines.append(_indent("))", level=0))
    return "\n".join(lines)


def generate(output_path: str, tools_dir: str) -> str:
    """Generate _generated_tools.py content and write it."""
    import yaml

    tools_path = Path(tools_dir)
    yaml_files = sorted(tools_path.glob("*.yaml"))

    lines = [
        '"""',
        "Auto-generated tool registrations — DO NOT EDIT BY HAND.",
        "",
        "Generated by: scripts/generate_tool_defs.py",
        "Source:      tools/definitions/*.yaml",
        f"Tools:       {len(yaml_files)} definitions",
        '"""',
        "",
        "from tool_definitions import ToolDefinition, ToolParameter, ToolRequires, SignalQuality, _register",
        "",
    ]

    for yaml_file in yaml_files:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or "name" not in data:
            continue
        lines.append("")
        lines.append(f"# ── {data['name']} (from {yaml_file.name}) ──")
        lines.append(_build_tool_registration(data))

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def check(tools_dir: str, generated_path: str) -> bool:
    """Compare generated output with existing file. Returns True if consistent."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        generate(tmp.name, tools_dir)
        tmp_path = tmp.name

    try:
        with open(tmp_path) as f:
            generated = f.read()
        with open(generated_path) as f:
            existing = f.read()

        gen_hash = hashlib.sha256(generated.encode()).hexdigest()
        existing_hash = hashlib.sha256(existing.encode()).hexdigest()

        if gen_hash == existing_hash:
            print(f"[PASS] {generated_path} is consistent with YAML definitions.")
            return True
        else:
            print(
                f"[FAIL] {generated_path} has drifted from YAML definitions.",
                file=sys.stderr,
            )
            print("       Run: python scripts/generate_tool_defs.py", file=sys.stderr)
            return False
    finally:
        os.unlink(tmp_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate _generated_tools.py from YAML single source of truth"
    )
    parser.add_argument("--tools-dir", default=None, help="Path to tools/definitions/")
    parser.add_argument(
        "--output", default=None, help="Output path for _generated_tools.py"
    )
    parser.add_argument("--check", action="store_true", help="CI mode: verify no drift")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent

    tools_dir = args.tools_dir or str(project_dir / "tools" / "definitions")
    output_path = args.output or str(project_dir / "_generated_tools.py")

    if args.check:
        sys.exit(0 if check(tools_dir, output_path) else 1)
    else:
        generate(output_path, tools_dir)
        yaml_count = len(list(Path(tools_dir).glob("*.yaml")))
        print(f"Generated {output_path} from {yaml_count} YAML definitions.")


if __name__ == "__main__":
    main()
