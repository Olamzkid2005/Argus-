# Tool Registry Architecture

> **Status:** ✅ Confirmed (WS3 Investigation — Outcome 3.3b)
> **Last updated:** 2026-07-25
> **Purpose:** Document the layered tool registry architecture so developers understand which registry to use for which purpose, and avoid creating a fifth layer.

---

## Overview

Argus has **4 intentional layers** for tool definitions. Each serves a distinct purpose — they are **not** redundant. Attempting to merge them would lose information or create tight coupling between compile-time and runtime concerns.

```
  YAML Source              Generated Python         Declarative Registry          MCP Runtime
 (tools/definitions/)      (_generated_tools.py)    (tool_definitions.py)     (mcp_server.py)
      Layer 1 ──────────▶    Layer 2 ────────────▶   Layer 3 ───────────────▶   Layer 4
        |                      |                        |                         |
  67+ YAML files          Auto-generated          60+ inline _register()    ToolDefinition class
  (nuclei.yaml,            Python code              calls that can override   with execution fields
   httpx.yaml, ...)        (DO NOT EDIT BY HAND)    generated defs            (command, args, timeout)
```

---

## Layer 1: YAML Source of Truth

**Location:** `argus-workers/tools/definitions/*.yaml`

The canonical source for tool **execution metadata**. Each YAML file describes one tool:

```yaml
name: nuclei
command: nuclei
args: ["-json", "-silent"]
phases: ["scan", "deep_scan"]
timeout: 600
signal_quality: confirmed
```

**Generator:** `scripts/generate_tool_defs.py` reads these YAML files and produces Layer 2.

---

## Layer 2: Auto-Generated Python

**Location:** `argus-workers/_generated_tools.py` (1,155 lines, ~60 tools)

Auto-generated Python module with `_register()` calls for every tool defined in YAML. Header explicitly says:

```python
# Auto-generated tool registrations — DO NOT EDIT BY HAND
```

**Generator:** `python scripts/generate_tool_defs.py`

**CI check:** `argus-workers/scripts/check_tool_registry_drift.py` — detects if Layer 1 and Layer 2 have diverged. Run manually with:
```
python argus-workers/scripts/check_tool_registry_drift.py
```

---

## Layer 3: Declarative Registry (tool_definitions.py)

**Location:** `argus-workers/tool_definitions.py`

The **primary Python-side consumer-facing registry**. Combines YAML-generated registrations with manually curated overrides:

```python
# Import generated defs FIRST (Layer 2)
from _generated_tools import *

# Then override specific tools with richer metadata
_register(ToolDefinition(
    name="pip-audit",         # overrides _generated_tools.py
    phases=["repo_scan"],
    requires=ToolRequires(tech_contains=["python"]),
    signal_quality=SignalQuality.CANDIDATE,
    ...
))
```

**Key types:**
- `ToolDefinition` — declarative (phases, parameters, signal_quality, requires, priority, cost)
- `ToolParameter` — schema for one parameter
- `ToolRequires` — activation conditions (tech_contains, recon_signals, target_scheme)
- `SignalQuality` — CONFIRMED / PROBABLE / CANDIDATE

**Exported helpers:**
- `get_tools_for_phase(phase)` — get tools for a phase, filtered by PATH availability
- `build_phase_tools_dict()` — PHASE_TOOLS dict for ReActAgent
- `evaluate_gate(tool, recon_context)` — check activation gates
- `build_mcp_tool_definitions()` — convert to Layer 4 format

**Agent-internal tools** (no external binary — always available):
`register`, `login`, `post_exploitation`, `ai_surface_detected`, `finding_correlation_engine`, `attack_path_generator`, `verification_agent`, etc.

**What makes a tool "agent-internal"?**
These tools have no external binary on PATH — they are Python functions within the agent itself. They are listed in `_AGENT_INTERNAL_TOOLS` (a `frozenset` in `tool_definitions.py`) and `is_tool_available()` always returns `True` for them without checking PATH. To add a new agent-internal tool:
1. Add its `ToolDefinition` via `_register()` in `tool_definitions.py`
2. Add its name to the `_AGENT_INTERNAL_TOOLS` frozenset
3. Implement the tool logic in a Python handler

**15+ consumers** — imported by agents, orchestrator, health checker, MCP bridge, smoke tests, and unit tests.

---

## Layer 4: MCP Runtime (mcp_server.py)

**Location:** `argus-workers/mcp_server.py` — `ToolDefinition` class (lines 70-120)

The **runtime representation** used by the MCP protocol server. Same name, different fields:

| Field | Purpose |
|-------|---------|
| `name`, `description` | Identity |
| `command`, `args` | Subprocess invocation |
| `parameters` | JSON schema for parameter validation |
| `timeout` | Execution timeout |
| `env` | Environment variables |
| `enabled` | Runtime enable/disable flag |
| `capabilities` | Planner capability mapping |
| `signal_quality` | Findings reliability tier |
| `requires` | Activation gates |

**Why separate from Layer 3?**
- Layer 3 is declarative (what, when, under what conditions)
- Layer 4 is runtime (how to execute, with what command, with what timeout)
- A tool might be registered in Layer 3 but fail to load in Layer 4 (binary not found on PATH)
- Layer 3 has `parallel_safe`, `risk_level`, `estimated_cost` — metadata that Layer 4 doesn't need

**Loading path:** Layer 4 loads **directly from YAML** (`_load_yaml_tools()`), not from Layer 2 or 3. This is intentional — it reads the same YAML source so both registries stay in sync without a Python-level import dependency.

**Bridge:** `tool_definitions.py:build_mcp_tool_definitions()` converts Layer 3 `ToolDefinition` objects into Layer 4 `ToolDefinition` objects so the orchestrator's MCP tool registration sees the same enriched metadata.

---

## TypeScript Side (Independent Registry)

**Location:** `Argus-Tui/packages/opencode/src/argus/workflows/`

The TypeScript CLI has its **own separate** tool registry for **planning** purposes:

| File | Purpose |
|------|---------|
| `tool-registry.ts` | `ToolRegistry` class — capability-driven tool selection |
| `tool-definitions.yaml` | Tool capability metadata (capabilities, scoring, auth gating) |

**Key differences from Python side:**

| Concern | Python (Layer 3-4) | TypeScript |
|---------|-------------------|------------|
| **Purpose** | Execution (phase assignment, CLI args, timeouts) | Planning (capability matching, scoring) |
| **Auth** | `credential_roles` | Auth gating per capability |
| **Scoring** | `priority`, `cost` | `confidence_score`, `speed_score`, `stability_score` |
| **Granularity** | Tool-level | Capability-level |

**Why separate?** The TypeScript planner needs to reason about *capabilities* (e.g., "which tool provides `sqli_detection`?"), not *execution paths*. The Python side handles execution. This separation prevents the planner from being coupled to tool-specific implementation details.

**Important distinction: Python YAML ≠ TypeScript YAML**
- Python `tools/definitions/*.yaml` defines **how tools execute** (command, args, timeout, phases)
- TypeScript `tool-definitions.yaml` defines **what capabilities tools provide** 
- TypeScript `workflows/*.yaml` defines **assessment plan phases** (recon → scan → verify → report)
These are three separate YAML formats serving different purposes — don't conflate them.

---

## Summary: Which Registry Should I Use?

| If you want to... | Use... |
|-------------------|--------|
| Add/modify a tool definition | **Layer 1** — YAML in `tools/definitions/` |
| Add richer metadata (requirements, overrides) | **Layer 3** — add `_register()` in `tool_definitions.py` |
| Regenerate Python code from YAML | `python scripts/generate_tool_defs.py` |
| Check if a tool is on PATH | `is_tool_available(name)` from `tool_definitions.py` |
| Get tools for a phase in Python | `get_tools_for_phase(phase)` from `tool_definitions.py` |
| Register MCP tools with orchestrator | `build_mcp_tool_definitions()` from `tool_definitions.py` |
| Add a tool to the TypeScript planner | Edit `tool-definitions.yaml` in `src/argus/workflows/` |
| Run the MCP server directly | `python -m mcp_server` (uses `main()` entry point) |
| Check if YAML and Python are in sync | `python scripts/check_tool_registry_drift.py` |

## Adding a New Tool — Full Workflow

1. **Create YAML** in `tools/definitions/<name>.yaml` (Layer 1)
2. **Regenerate** `_generated_tools.py` (Layer 2):
   ```
   python scripts/generate_tool_defs.py
   ```
3. **Add override** in `tool_definitions.py` (Layer 3) if you need:
   - `requires` gates (`tech_contains`, `recon_signals`, `target_scheme`)
   - Custom `signal_quality` (different from YAML default)
   - Phase overrides or additional metadata
   
   *YAML-generated entries suffice for basic registration. Override only when the YAML metadata isn't enough.*
4. **Add TS metadata** in `Argus-Tui/.../workflows/tool-definitions.yaml` if the planner needs capability info
5. **Verify** the tool is available: `is_tool_available(name)` in Python, `ToolRegistry` in TypeScript

---

## Layer Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TOOL REGISTRY ARCHITECTURE                       │
└─────────────────────────────────────────────────────────────────────┘

  PYTHON SIDE                           TYPESCRIPT SIDE
┌─────────────────────────────┐    ┌─────────────────────────────┐
│  Layer 1: YAML              │    │  TS tool-definitions.yaml   │
│  tools/definitions/*.yaml   │    │  (capabilities, scoring)    │
│  (67+ files)                │    │                             │
└──────────┬──────────────────┘    └──────────────┬──────────────┘
           │ generate_tool_defs.py                │ ToolRegistry.load()
           ▼                                      ▼
┌─────────────────────────────┐    ┌─────────────────────────────┐
│  Layer 2: _generated_tools  │    │  TS tool-registry.ts        │
│  (60 tools, auto-gen'd)     │    │  (capability matching,      │
└──────────┬──────────────────┘    │   scoring, auth gating)     │
           │ imported by            └─────────────────────────────┘
           ▼
┌─────────────────────────────┐
│  Layer 3: tool_definitions  │  ← Declarative registry
│  (inline overrides +        │    (phases, params, signal_quality)
│   helper functions)         │
└──────┬──────────────┬───────┘
       │              │
       │ build_mcp_   │ get_tools_for_phase()
       │ definitions  │ evaluate_gate()
       ▼              ▼
┌──────────────────────┐    ┌──────────────────────┐
│  Layer 4: mcp_server │    │  agent/react_agent   │
│  (runtime execution, │    │  intelligence_engine │
│   subprocess calling)│    │  orchestrator, etc.  │
└──────────────────────┘    └──────────────────────┘
```

---

## Historical Context

This architecture was investigated systematically in **WS3 (Tool-Registry Resolution)** of the 5 workstreams plan. The investigation:

1. Exported both registries as JSON and diffed programmatically
2. Mapped all 15+ consumer sites of `tool_definitions.py`
3. Checked consumer overlap (does any code path import both layers?)
4. Produced the decision tree outcome: **3.3b — Legitimately separate paths**

The key finding was that `tool_definitions.py` (declarative) and `mcp_server.py:ToolDefinition` (runtime) serve different schemas for different consumers. Merging them would require either:
- Adding runtime fields (command, args, timeout) to the declarative type, or
- Adding declarative fields (phases, parallel_safe, risk_level) to the runtime type

Both would create tighter coupling. The current separation is intentional and should be preserved.
