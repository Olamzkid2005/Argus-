# Task Plan: Port All Tools to Extended YAML Schema

## Goal
Port all ~40 tools from Python `tool_definitions.py` into YAML definitions with an extended schema (`capabilities`, `signal_quality`, `requires`, `priority`, `cost`), update both registries (Python YAML + TypeScript tool-definitions.yaml) to stay in sync, and plumb the new fields through the MCP server, ToolRegistry, ConfidenceEngine, and planner so the system becomes a capability-driven orchestration engine.

## Current Phase
Phase 1 (complete — analysis done)

---

## Phases

### Phase 1: Analysis & Schema Design (DONE)
- [x] Inventory all tools in Python `tool_definitions.py`
- [x] Map which are on PATH vs. not yet installed
- [x] Understand current YAML schema vs. Python dataclass fields
- [x] Understand TypeScript `ToolRegistry` ingestion
- [x] Understand `ConfidenceEngine` promotion pipeline
- [x] Design extended YAML schema
- **Status:** complete

### Phase 2: Extend Python MCP Server — Accept New YAML Fields
- [ ] Update `ToolDefinition` class in `mcp_server.py` to accept `capabilities`, `signal_quality`, `requires`, `priority`, `cost`
- [ ] Update `to_dict()` to serialize new fields
- [ ] Update `_load_yaml_tools()` to pass new fields through safely (backward compat with old YAMLs)
- [ ] Update `ToolSchema` if needed
- **Status:** pending

### Phase 3: Extend TypeScript ToolRegistry — Ingest New Fields
- [ ] Add `signal_quality`, `requires`, `priority`, `cost` to `ToolDef` interface
- [ ] Add `SignalQuality` enum (CANDIDATE, PROBABLE, CONFIRMED)
- [ ] Add `RequiresGate` interface (tech_contains, recon_signals, target_scheme)
- [ ] Make `load()` tolerant of missing new fields (backward compat)
- [ ] Expose new fields via `getTool()`, `selectBest()` filtering
- [ ] **Status:** pending

### Phase 4: Port Recon Tools (Batch 1 — 7 tools)
- [ ] Create YAML: `ffuf` (on PATH, TS-side already has metadata)
- [ ] Create YAML: `katana`
- [ ] Create YAML: `gau`
- [ ] Create YAML: `waybackurls`
- [ ] Create YAML: `amass`
- [ ] Create YAML: `naabu`
- [ ] Create YAML: `gospider`
- [ ] Add corresponding metadata in `tool-definitions.yaml` (TypeScript side)
- **Status:** pending

### Phase 5: Port Scan Tools (Batch 2 — 7 tools)
- [ ] Create YAML: `dalfox`
- [ ] Create YAML: `sqlmap`
- [ ] Create YAML: `arjun`
- [ ] Create YAML: `jwt_tool`
- [ ] Create YAML: `commix`
- [ ] Create YAML: `testssl`
- [ ] Create YAML: `wafw00f`
- [ ] Add TypeScript metadata
- **Status:** pending

### Phase 6: Port Repo Scan Tools (Batch 3 — 5 tools)
- [ ] Create YAML: `semgrep`
- [ ] Create YAML: `gitleaks`
- [ ] Create YAML: `trivy`
- [ ] Create YAML: `bandit`
- [ ] Create YAML: `pip-audit`
- [ ] Add TypeScript metadata
- **Status:** pending

### Phase 7: Port Off-PATH / Future Tools (Batch 4 — 15 tools)
- [ ] Create YAML for recon off-path: `alterx`, `shuffledns`, `dnsx`, `chaos`, `uncover`, `s3scanner`, `trufflehog`, `github-endpoints`
- [ ] Create YAML for scan off-path: `masscan`, `wpscan`
- [ ] Create YAML for deep_scan off-path: `sn1per`, `cloud_enum`, `bucket_upload`
- [ ] Create YAML for repo_scan off-path: `dependency_check`, `govulncheck`, `brakeman`, `gosec`, `eslint`, `phpcs`, `spotbugs`, `npm-audit`
- [ ] Add TypeScript metadata for all
- **Status:** pending

### Phase 8: Refine Existing YAMLs (Add Missing Params)
- [ ] `nuclei.yaml` — add `severity`, `templates`, `tags` parameters (Python has them, YAML doesn't)
- [ ] `nmap.yaml` — add `ports` parameter
- [ ] `nikto.yaml`, `httpx.yaml`, `subfinder.yaml`, `whatweb.yaml` — review against Python definition for missing params
- [ ] Add TypeScript capability metadata where missing
- **Status:** pending

### Phase 9: Plumb signal_quality Into ConfidenceEngine
- [ ] Load `signal_quality` from tool definition at finding creation time
- [ ] Map CANDIDATE → LOW, PROBABLE → MEDIUM, CONFIRMED → HIGH as initial baseline
- [ ] Update `ConfidenceEngine.promote()` to respect initial baseline
- [ ] Verify with doctor output: findings should show correct confidence
- **Status:** pending

### Phase 10: Plumb requires Gates Into Planner
- [ ] Make `ToolRegistry.selectBest()` filter tools by `requires` gates when `PlannerContext` is available
- [ ] Gate on `tech_contains`: only suggest tool if target tech stack matches
- [ ] Gate on `recon_signals`: only suggest tool if recon has published matching signals
- [ ] Gate on `target_scheme`: only suggest tool if target URL scheme matches
- [ ] Wire `priority` and `cost` into `selectBest()` scoring
- **Status:** pending

### Phase 11: Test & Verify
- [ ] Run `bun test test/argus/unit/commands/doctor.test.ts`
- [ ] Run doctor live: verify all installed tools appear
- [ ] Run deterministic assess against example.com: verify tool selection and execution
- [ ] Verify doctor output shows proper signal_quality information
- **Status:** pending

---

## Extended YAML Schema (Final Design)

```yaml
# ── Core (required, same as today) ──
name: <tool_name>                       # e.g., sqlmap
command: <binary_name>                  # e.g., sqlmap
description: "<human-readable desc>"

# ── Static args (always appended) ──
args:
  - "-json"
  - "-silent"

# ── Parameters (mapped from user input to CLI flags) ──
parameters:
  - name: target
    type: string
    description: "Target URL"
    required: true
    flag: "-u"
  - name: level
    type: integer
    description: "Test level (1-5)"
    required: false
    flag: "--level"
    default: 1

# ── Planner intelligence (NEW) ──
capabilities:
  - sqli_detection
  - database_exfiltration

signal_quality: CONFIRMED               # CANDIDATE | PROBABLE | CONFIRMED

priority: 80                            # 0-100, higher = preferred
cost: high                              # low | medium | high

requires:                               # All conditions must be met (AND)
  tech_contains:                        # Tool only runs if tech stack contains one of these
    - python
  recon_signals:                        # Tool only runs if recon has these signals
    - parameterized_forms
    - injectable_parameter
  target_scheme:                        # Tool only runs if target URL matches
    - http
    - https

# ── Runtime ──
enabled: true
timeout: 600
```

## Mapping: Python fields → YAML fields

| Python field | YAML field | Required |
|---|---|---|
| `tool.name` | `name` | yes |
| `tool.binary or tool.name` | `command` | yes |
| `tool.description` | `description` | yes |
| `tool.default_args` | `args` | no |
| `tool.parameters` | `parameters` | no |
| `tool.enabled` | `enabled` | no |
| `tool.timeout` | `timeout` | no |
| *(new)* | `capabilities` | **yes** (planner needs it) |
| `tool.signal_quality` | `signal_quality` | no |
| `tool.requires.tech_contains` | `requires.tech_contains` | no |
| `tool.requires.recon_signals` | `requires.recon_signals` | no |
| `tool.requires.target_scheme` | `requires.target_scheme` | no |
| *(new)* | `priority` | no |
| *(new)* | `cost` | no |

## Two Registries Must Stay in Sync

| Registry | File(s) | Purpose | Needs Update |
|---|---|---|---|
| **Python MCP YAML** | `argus-workers/tools/definitions/*.yaml` | Tool execution (MCP server runs tools from these) | New files + new fields |
| **TypeScript metadata** | `Argus-Tui/.../workflows/tool-definitions.yaml` | Planner capability matching + scoring | New entries + capabilities |

The TypeScript side already has a separate schema (`capabilities`, `scoring`, `supports_api`, etc.). The plan is to:
1. Add new entries here for every tool (in sync with Python YAMLs)
2. Not duplicate `signal_quality`/`requires` here — those live in the Python YAMLs (the MCP server is the execution source of truth)
3. The TypeScript side keeps its own `scoring.confidence_score` and `scoring.coverage_score` for planner ranking

## Tool Inventory (Complete)

Legend: ✅ exists, ❌ missing, 🔧 needs refinement

### Already in Python YAML (6)
| Tool | Status | Notes |
|---|---|---|
| httpx | ✅ exists | Check params vs Python |
| nikto | ✅ exists | Check params vs Python |
| nmap | ✅ exists | 🔧 Missing `ports` param |
| nuclei | ✅ exists | 🔧 Missing `severity`, `templates`, `tags` |
| subfinder | ✅ exists | 🔧 Missing `all` param |
| whatweb | ✅ exists | Check params vs Python |

### On PATH, needs YAML (19)
| # | Tool | Phase | Capability | Signal Quality | Requires |
|---|---|---|---|---|---|
| 1 | ffuf | recon | content_discovery | CANDIDATE | — |
| 2 | katana | recon | content_discovery, web_recon | CANDIDATE | — |
| 3 | gau | recon | web_recon | CANDIDATE | — |
| 4 | waybackurls | recon | web_recon | CANDIDATE | — |
| 5 | amass | recon | web_recon | CANDIDATE | — |
| 6 | naabu | recon | port_scanning | CANDIDATE | — |
| 7 | gospider | recon | content_discovery | CANDIDATE | — |
| 8 | dalfox | scan | sqli_detection | PROBABLE | — |
| 9 | sqlmap | scan | sqli_detection, database_exfiltration | CONFIRMED | recon_signals: [parameterized_forms] |
| 10 | arjun | scan | api_probing | CANDIDATE | — |
| 11 | jwt_tool | scan | jwt_analysis | PROBABLE | recon_signals: [has_api, has_login_page] |
| 12 | commix | scan | ssrf_check | PROBABLE | recon_signals: [has_file_upload] |
| 13 | testssl | scan | vulnerability_scanning | CANDIDATE | target_scheme: [https] |
| 14 | wafw00f | recon, scan | web_recon | CONFIRMED | — |
| 15 | semgrep | repo_scan | — | CONFIRMED | — |
| 16 | gitleaks | repo_scan | — | CONFIRMED | — |
| 17 | trivy | repo_scan | — | PROBABLE | — |
| 18 | bandit | repo_scan | — | PROBABLE | tech_contains: [python] |
| 19 | pip-audit | repo_scan, scan | — | CANDIDATE | tech_contains: [python] |

### Not on PATH, needs YAML (15)
| # | Tool | Phase | Capability | Signal Quality | Requires |
|---|---|---|---|---|---|
| 20 | alterx | recon | web_recon | CANDIDATE | — |
| 21 | shuffledns | recon | web_recon | CANDIDATE | — |
| 22 | dnsx | recon | web_recon | CANDIDATE | — |
| 23 | chaos | recon | web_recon | CANDIDATE | — |
| 24 | uncover | recon | web_recon | CANDIDATE | — |
| 25 | s3scanner | recon | web_recon | CANDIDATE | — |
| 26 | trufflehog | repo_scan | — | PROBABLE | — |
| 27 | masscan | scan | port_scanning | CANDIDATE | — |
| 28 | sn1per | deep_scan | vulnerability_scanning | CANDIDATE | — |
| 29 | cloud_enum | deep_scan | — | CANDIDATE | — |
| 30 | bucket_upload | deep_scan | — | CANDIDATE | — |
| 31 | dependency_check | repo_scan | — | CONFIRMED | — |
| 32 | govulncheck | repo_scan | — | PROBABLE | tech_contains: [go] |
| 33 | brakeman | repo_scan | — | PROBABLE | tech_contains: [ruby] |
| 34 | gosec | repo_scan | — | PROBABLE | tech_contains: [go] |
| 35 | eslint | repo_scan | — | PROBABLE | tech_contains: [javascript, typescript] |
| 36 | phpcs | repo_scan | — | PROBABLE | tech_contains: [php] |
| 37 | spotbugs | repo_scan | — | PROBABLE | tech_contains: [java, kotlin] |
| 38 | wpscan | scan | vulnerability_scanning | CANDIDATE | tech_contains: [wordpress, wp-] |
| 39 | npm-audit | repo_scan | — | CANDIDATE | tech_contains: [javascript, typescript] |

### Skipped — Agent-internal, no CLI binary (4)
`register`, `login`, `intelligence-engine`, `attack-graph`, `report-generator`, `compliance-check`

## Key Decisions

| Decision | Rationale |
|---|---|
| `capabilities` added to both registries | Planner needs capability matching on TypeScript side; MCP needs it for tool discoverability |
| `signal_quality` lives in Python YAML only | It's execution metadata — the MCP server returns it with results; TypeScript ConfidenceEngine reads it from there |
| `requires` lives in Python YAML only | Same reasoning — it's pre-execution gating metadata attached to the tool itself |
| `priority` and `cost` added now but optional | Planner ranking can use `priority` as tiebreaker; `cost` enables "quick scan = low-cost only" |
| TypeScript `tool-definitions.yaml` keeps its own `scoring` | That scoring is planner-side (confidence_score + coverage_score combine for tool selection rank) — separate from `signal_quality` which is finding-level |
| Backward compat: old YAMLs without new fields still load | All new fields are optional; MCP server defaults gracefully |
