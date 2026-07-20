# Tool-Registry Reconciliation Report

**Investigating the alleged "duplicate tool registries" in the Argus codebase**

**Date:** 2026-07-20
**Investigator:** Automated cross-reference of Python and TypeScript sides

---

## Executive Summary

The senior review (2026-07-19) flagged a "real, new, and moderately serious finding" that the codebase has two tool-definition systems that both claim to be the single source of truth:

1. `tool_definitions.py` — declarative registry (Python)
2. `tools/definitions/*.yaml` + `_generated_tools.py` — YAML-derived registry (Python)

**Verdict: The Python "duplication" is NOT real.** It's a single registry (`TOOLS` dict) populated from two complementary sources. No drift risk exists on the Python side.

**However, a REAL but INTENTIONAL duplication exists between the Python-side `TOOLS` dict and the TypeScript-side `workflows/tool-definitions.yaml`.** These are genuinely independent systems serving different purposes (execution vs. planning), with no synchronization mechanism and different schema/metadata coverage.

---

## 1. Python-Side Architecture (ONE Registry, Two Sources)

### The Registry: `TOOLS` dict in `tool_definitions.py`

```python
TOOLS: dict[str, ToolDefinition] = {}

def _register(tool: ToolDefinition) -> None:
    TOOLS[tool.name] = tool
```

Every tool definition, regardless of origin, ends up in this single dict. It is the **unambiguous single source of truth** on the Python side.

### Source A: YAML Files → `_generated_tools.py`

| Component | Location |
|---|---|
| YAML source files | `argus-workers/tools/definitions/*.yaml` (67 files, 1 per tool) |
| Generator script | `argus-workers/scripts/generate_tool_defs.py` |
| Generated output | `argus-workers/_generated_tools.py` |
| Registrations | 65 tool definitions via `_register()` calls |

Each YAML file defines one tool with its schema (parameters, args, timeout, capabilities, etc.).

Example (`nuclei.yaml`):
```yaml
name: nuclei
command: nuclei
description: "Nuclei vulnerability scanner..."
args: ["-json", "-silent", ...]
parameters:
  - name: target
    type: string
    required: true
    flag: "-u"
  - name: severity
    type: string
    flag: "-severity"
capabilities:
  - vulnerability_scanning
  - template_scanning
signal_quality: CONFIRMED
priority: 95
cost: medium
timeout: 600
```

### Source B: Inline Definitions in `tool_definitions.py`

The same file also contains 40+ inline `_register(ToolDefinition(...))` calls. These are hand-crafted definitions for tools that either:

- Are **agent-internal tools** with no external binary (e.g., `register`, `login`, `finding_correlation_engine`, `post_exploitation`)
- Are **specialized tools** that need hand-tuned metadata (e.g., `nuclei` has a `ToolMetadata` with vendor/homepage/license info)
- **Override** YAML-generated definitions when the inline version should take priority

### The Import Chain

```
tool_definitions.py:
  1. TOOLS = {}                # Initialize empty registry
  2. from _generated_tools import *  # Import YAML-generated registrations
     → _generated_tools.py:
        from tool_definitions import ToolDefinition, ..., _register  # Import types
        _register(ToolDefinition(name="nuclei", ...))  # Register 65 YAML tools
        _register(ToolDefinition(name="pip-audit", ...))
        ...
  3. _register(ToolDefinition(name="pip-audit", ...))  # Override: inline wins for name collisions
     _register(ToolDefinition(name="nuclei", ...))      # Override: richer inline metadata wins
     ...
```

**Key insight:** This is NOT circular — Python resolves `from _generated_tools import *` during `tool_definitions`' partial initialization. The YAML-generated tools register first, then inline tools can intentionally override them.

The comments in `tool_definitions.py` confirm this is by design:
```python
# pip-audit comment: "(overrides _generated_tools.py)"
# dependency_check comment: "(overrides _generated_tools.py)"
```

### Consumers of the Python `TOOLS` Dict

| Consumer | What it imports |
|---|---|
| `react_agent.py` | `build_phase_tools_dict()`, `get_tools_for_phase()`, `TOOLS` |
| `intelligence_engine.py` | `TOOLS`, `SignalQuality` |
| `orchestrator_pkg/orchestrator.py` | `build_mcp_tool_definitions()` |
| `orchestrator_pkg/scan.py` | `TOOLS`, `evaluate_gate()` |
| `tool_core/registry.py` | `TOOLS` (cross-reference discovered binaries) |
| `tools/mcp_bridge.py` | `build_mcp_tool_definitions()` |
| 7+ test files | Various imports |

**`tool_core/registry.py`** — The third item the review flagged — is NOT a competing registry. It's a PATH-scanning tool **discovery** mechanism that imports `TOOLS` from `tool_definitions.py` to cross-reference. It's purely a consumer.

---

## 2. TypeScript-Side: TRULY Independent System

### The Registry: `tool-registry.ts`

| Component | Location |
|---|---|
| Registry class | `Argus-Tui/packages/opencode/src/argus/workflows/tool-registry.ts` |
| YAML data file | `Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml` |
| Workflow YAMLs | Same directory: `full_assessment.yaml`, `quick_scan.yaml`, `xss.yaml`, etc. |

### Schema Difference: TS vs Python

The TS `tool-definitions.yaml` has a **completely different schema** from the Python YAMLs:

| Field | Python YAML | TS YAML |
|---|---|---|
| Structure | One file per tool, `name:` at top | Single combined file, `tools:` array |
| `capabilities` | Array of strings | Array of strings (same semantics) |
| `command`/`args` | Yes (execution detail) | No (not needed for planning) |
| `parameters` | Yes (parameter schema) | No (not needed for planning) |
| `phases` | Yes (recon, scan, analyze...) | No (uses `capabilities` + workflow YAMLs instead) |
| `signal_quality` | Yes | Yes (via `scoring` sub-object) |
| `priority`, `cost` | Yes | Yes |
| `scoring` | No | Yes (confidence_score + coverage_score) |
| `consumes`/`provides` | No | Yes (for workflow dependency resolution) |
| `requires_auth` | No | Yes (for planner filtering) |
| `supports_api`/`supports_web` | No | Yes (for target-type routing) |
| `destructive` | No | Yes (for safety gating) |
| `version_cmd`/`version_regex` | No | Yes (for version checking) |

The two schemas have diverged because they serve **different roles**:

- **Python side** (execution): needs to know how to invoke the tool (command, args, parameters) and how to interpret results (signal_quality, phases)
- **TS side** (planning): needs to know which tools to select (capabilities, scoring, consumes/provides) and how to route them (supports_api/web, destructive)

### Consumers of the TS ToolRegistry

| Consumer | Role |
|---|---|
| `workflow-runner.ts` | Creates registry, loads YAML, runs assessment |
| `planner/planner.ts` | Uses `selectBest()` to pick tools for each work phase |
| `planner/executor.ts` | Uses `getTool()`, `getToolsByCapability()` to dispatch tools |
| `commands/resume.ts` | Loads registry when resuming an engagement |
| `commands/doctor.ts` | Checks tool availability |

### Coverage Comparison

| Metric | Python Side | TS Side |
|---|---|---|
| Total tool definitions | ~107 (67 YAML + 40 inline) | ~37 (in single YAML) |
| Agent-internal tools | Yes (20+) | Yes (same set, replicated) |
| Post-exploitation tools | Yes (post_exploitation, credential_replay, internal_probe) | Yes (same set, replicated) |
| Infrastructure tools | Yes (trivy, semgrep, etc.) | Yes (subset) |
| Cloud tools | Yes (cloud_enum, s3scanner, bucket_upload) | Yes (same set) |
| Some minor tools | Yes (sn1per, github-endpoints, uncover, shuffledns) | No |

The TS side covers a **subset** of the Python tools — enough for the planner to make good decisions, but not every tool the executor can run.

---

## 3. Findings and Recommendations

### Finding A: Python "duplication" is NOT a real problem

The circular import between `tool_definitions.py` and `_generated_tools.py` is intentional and well-designed. The YAML-generated tools register first, then inline definitions can intentionally override. The `TOOLS` dict is the single source of truth.

**Status:** ✅ By design. No action required.

### Finding B: TS/Python independence IS intentional but undocumented

The two registries are genuinely independent, serve different roles (planning vs execution), and have different schemas. **This is correct architecture** — coupling the TS planner's tool metadata to the Python executor's would create unnecessary dependencies.

However, the relationship is **completely undocumented**. A developer adding a tool needs to:
1. Create a Python YAML in `tools/definitions/` and re-run `generate_tool_defs.py`
2. Optionally add an inline override in `tool_definitions.py`
3. **Separately** update the TS `tool-definitions.yaml` if the planner needs to know about the tool

There is no indication in either file that the other exists.

**Status:** ⚠️ Documented gap. Low risk but contributor-friction.

### Finding C: Drift between the two registries exists but may be harmless

The TS side is missing ~70 Python tools. Most of these are tools the planner doesn't need to select independently (e.g., `cloud_enum`, `uncover`, `chaos`, `dnsx` — these are called as sub-steps by higher-level tools like `attack_surface_mapper`). But this drift is invisible — there's no way to tell if a missing tool is intentionally excluded or accidentally omitted.

**Status:** ⚠️ Undocumented drift. Low-medium risk. Could cause confusing behavior if a tool exists on Python side but the TS planner doesn't know about it and therefore doesn't select it.

### Finding D: tool_core/registry.py is NOT a competing registry

It's a PATH-scanning discovery mechanism, not a tool definition registry. It imports `TOOLS` from `tool_definitions.py` as a cross-reference.

**Status:** ✅ Not a problem. No action required.

---

## 4. Actionable Recommendations

### Tier 0: Document the Architecture (0.5 day)

Add a comment header to both files explaining the relationship:

**`tool_definitions.py`** — Add at top:
```python
"""
This is the Python-side single source of truth for tool execution metadata.
- YAML-generated registrations in _generated_tools.py populate the TOOLS dict first
- Inline registrations below can intentionally override YAML-generated definitions

The TypeScript-side planner has its own tool definitions in:
  Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml
This is intentionally separate — different schema, different purpose (planning vs execution).

When adding a new tool:
  1. Create a .yaml file in tools/definitions/
  2. Run: python scripts/generate_tool_defs.py
  3. Optionally add an inline override here with richer metadata
  4. If the TS planner needs to know about this tool, also update tool-definitions.yaml
"""
```

**`tool-registry.ts` / `tool-definitions.yaml`** — Add at top:
```typescript
/**
 * TypeScript-side tool registry for the Argus planner.
 * 
 * This is intentionally separate from the Python-side TOOLS dict in
 * tool_definitions.py. Different schema, different purpose (planning vs execution).
 * 
 * Python source of truth: argus-workers/tool_definitions.py (+ tools/definitions/*.yaml)
 * 
 * When adding a tool here, also add its execution metadata to the Python side.
 */
```

### Tier 1: Add Drift-Detection CI Check (1 day)

Add a script that cross-references the TS `tool-definitions.yaml` against the Python `TOOLS` dict and reports missing or mismatched tools. This doesn't need to fail CI (drift may be intentional) but should log warnings for the developer.

Suggested approach:
```bash
# scripts/check-tool-registry-drift.sh
# 1. Parse Python TOOLS dict (import tool_definitions and extract keys)
# 2. Parse TS tool-definitions.yaml 
# 3. Report any tools in Python that are missing from TS (and vice versa)
# 4. Exit 0 (informational only — drift may be intentional)
```

### Tier 2: Evaluate Schema Unification (Future)

If the planner and executor ever need tighter integration (e.g., the planner needs to understand parameter schemas for dynamic tool configuration), consider unifiying the schemas. For now, the separation is appropriate.

---

## 5. Files Referenced

| File | Role |
|---|---|
| `argus-workers/tool_definitions.py` | Python-side single source of truth (TOOLS dict, inline registrations) |
| `argus-workers/_generated_tools.py` | Auto-generated YAML-derived registrations |
| `argus-workers/scripts/generate_tool_defs.py` | Generator from Python YAMLs |
| `argus-workers/tools/definitions/*.yaml` | 67 per-tool YAML source files |
| `argus-workers/tool_core/registry.py` | PATH-scanning discovery (consumer, not registry) |
| `Argus-Tui/.../workflows/tool-registry.ts` | TS-side planning registry |
| `Argus-Tui/.../workflows/tool-definitions.yaml` | TS-side combined tool definitions |
| `Argus-Tui/.../workflows/*.yaml` | TS-side workflow definitions |
