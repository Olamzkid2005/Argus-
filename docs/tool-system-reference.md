# Argus Tool System — Complete Reference

## Overview

Argus has **two parallel tool systems** — a deterministic planner on the TypeScript side and an LLM-driven agent on the Python side. They share the same tool binaries but select and invoke them differently.

```
┌──────────────────────────────────────────────────────────┐
│                     TOOL BINARIES                        │
│  nuclei, nmap, whatweb, subfinder, ffuf, sqlmap, ...     │
│  Installed on PATH (brew, apt, go install, etc.)         │
└──────────────┬───────────────────────────┬───────────────┘
               │                           │
               ▼                           ▼
┌──────────────────────────┐   ┌──────────────────────────┐
│  PYTHON SIDE             │   │  TYPESCRIPT SIDE          │
│                          │   │                          │
│  tools/definitions/*.yaml│   │  tool-definitions.yaml    │
│  (47 tools, full detail) │   │  (33 tools, planner use) │
│        ↓                 │   │        ↓                 │
│  tool_definitions.py     │   │  Planner selects tools   │
│  (68 tools, all phases)  │   │  by capability match     │
│        ↓                 │   │        ↓                 │
│  MCP Server (stdio)      │   │  Executor calls MCP      │
│  - list_tools            │   │  via JSON-RPC over stdio │
│  - call_tool             │◄──┤        ↓                 │
│  - agent_plan (new)      │   │  Python runs subprocess  │
│        ↓                 │   │                          │
│  ReActAgent (LLM-driven) │   │  (ReActAgent NOT used)   │
│  - picks next tool       │   │                          │
│  - observes output       │   │                          │
│  - loops until done      │   │                          │
└──────────────────────────┘   └──────────────────────────┘
```

---

## 1. Tool Definition (Python YAML)

**Location:** `argus-workers/tools/definitions/<tool>.yaml`

Each tool gets its own YAML file with full metadata. The MCP server reads these at startup.

### Anatomy of a tool definition

```yaml
# argus-workers/tools/definitions/nmap.yaml
name: nmap                      # Unique identifier, must match binary name
command: nmap                   # Binary to execute (must be on PATH)
description: >
  Network Mapper — port scanning, service detection, OS fingerprinting.

args:                           # Static args passed on every invocation
  - -oX
  - -                           # Output XML to stdout (for parsing)

parameters:                     # Dynamic args from the planner / LLM
  - name: target
    flag: null                  # Positional arg (no flag prefix)
    type: string
    description: Target IP or hostname
    required: true
  - name: ports
    flag: -p
    type: string
    description: Port range (e.g. 1-1000, 80,443)
    default: 1-1000
  - name: scan_type
    flag: -s
    type: string
    enum: [sS, sT, sV, sC, A]
    default: sV
    description: Scan type (SYN, Connect, Version, etc.)

capabilities:                   # What this tool can do (maps to planner phases)
  - port_scanning
  - technology_detection

signal_quality: CONFIRMED       # Confidence tier: CONFIRMED | PROBABLE | CANDIDATE
timeout: 600                    # Execution timeout in seconds
enabled: true

requires:                       # Gates — conditions that must be met
  target_scheme: any            # http, https, any
  tech_contains: []             # e.g. ["apache"] — only runs if tech detected
  recon_signals: []             # e.g. ["open_ports"] — only runs if recon found ports

priority: 50                    # Ranking weight (higher = preferred when multiple tools match)
cost: medium                    # low | medium | high — execution cost tier

risk_level: low                 # low | medium | high — destructive potential
metadata:
  author: nmap-dev
  homepage: https://nmap.org
  license: NPSL
```

### All YAML fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique identifier, matches binary |
| `command` | string | ✅ | CLI binary name |
| `description` | string | | Human-readable description |
| `args` | string[] | | Static CLI arguments (always passed) |
| `parameters` | object[] | | Named parameters the planner/LLM can set |
| `parameters[].name` | string | ✅ | Parameter name for the planner |
| `parameters[].flag` | string | | CLI flag (e.g. `-u`, `--url`). `null` = positional |
| `parameters[].type` | string | | `string`, `integer`, `boolean`, `enum` |
| `parameters[].description` | string | | Help text |
| `parameters[].required` | bool | | Is this required? |
| `parameters[].default` | any | | Default value |
| `parameters[].enum` | string[] | | Valid values for enum type |
| `capabilities` | string[] | ✅ | What planner capabilities this satisfies |
| `signal_quality` | enum | | `CONFIRMED` \| `PROBABLE` \| `CANDIDATE` |
| `timeout` | int | | Seconds before kill |
| `enabled` | bool | | Is this tool active? |
| `requires.target_scheme` | string | | `http` \| `https` \| `any` |
| `requires.tech_contains` | string[] | | Tech stack must contain at least one |
| `requires.recon_signals` | string[] | | Recon must have found these signals |
| `priority` | int | | 0-100, higher preferred |
| `cost` | enum | | `low` \| `medium` \| `high` |
| `risk_level` | enum | | `low` \| `medium` \| `high` |
| `metadata` | object | | Author, homepage, license |

### Full tool inventory (47 tools)

**Recon (19):** `whatweb`, `subfinder`, `httpx`, `dnsx`, `shuffledns`, `alterx`, `chaos`, `uncover`, `amass`, `naabu`, `waybackurls`, `gau`, `katana`, `gospider`, `ffuf`, `sn1per`, `masscan`, `github-endpoints`, `wafw00f`

**Scanning (10):** `nmap`, `nikto`, `nuclei`, `wpscan`, `commix`, `jwt_tool`, `arjun`, `sqlmap`, `dalfox`, `testssl`

**Secret/Cloud (5):** `gitleaks`, `trufflehog`, `s3scanner`, `bucket_upload`, `cloud_enum`

**SAST/SCA (9):** `semgrep`, `trivy`, `bandit`, `govulncheck`, `brakeman`, `gosec`, `eslint`, `phpcs`, `spotbugs`

**Dependency (2):** `npm-audit`, `pip-audit`

**Analysis (2):** `intelligence-engine`, `attack-graph`

---

## 2. Tool Registration (Python)

**Location:** `argus-workers/tool_definitions.py` (line 81+)

The `ToolDefinition` dataclass (25 fields) registers all tools programmatically:

```python
@dataclass
class ToolDefinition:
    name: str
    description: str
    phases: list                    # which workflow phases (recon, scan, deep_scan, ...)
    binary: str                     # CLI binary name
    default_args: list[str]         # static args
    parameters: list[dict]          # dynamic params (same as YAML)
    timeout: int
    signal_quality: str
    requires: dict
    risk_level: str
    estimated_cost: str
    metadata: dict
    # ...plus 14 more fields
```

Tools are registered via `_register()` calls:

```python
# tool_definitions.py line ~156
TOOLS: dict[str, ToolDefinition] = {}

def _register(tool: ToolDefinition) -> None:
    TOOLS[tool.name] = tool

# Each tool is registered explicitly:
_register(ToolDefinition(
    name="nuclei",
    description="Fast vulnerability scanner with YAML templates",
    phases=["recon", "scan", "deep_scan"],
    binary="nuclei",
    default_args=["-json", "-silent"],
    parameters=[...],
    timeout=300,
    signal_quality="CONFIRMED",
    requires={},
    risk_level="low",
    estimated_cost="low",
    metadata={},
))
```

**Why two registration paths (YAML + Python)?**

| Path | Reader | Purpose |
|------|--------|---------|
| `tools/definitions/*.yaml` | MCP Server (`mcp_server.py`) | Runtime tool execution — builds CLI commands, validates args |
| `tool_definitions.py` | ReActAgent, IntelligenceEngine | LLM context — provides tool descriptions to the agent for planning |

Both must be kept in sync. There is currently **no automated check** for drift.

---

## 3. Tool Discovery & MCP Server

**Location:** `argus-workers/mcp_server.py`

### Startup sequence

```python
class MCPToolServer:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def load_tools(self):
        """Scan tools/definitions/*.yaml at startup."""
        import glob
        for yaml_path in glob.glob("tools/definitions/*.yaml"):
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
            # Validate against blocklist
            if data["command"] in BLOCKLIST:  # no bash, python, curl, etc.
                continue
            self._tools[data["name"]] = data
```

### MCP Protocol (JSON-RPC 2.0 over stdio)

The TypeScript side spawns `mcp_server.py` as a subprocess and communicates via stdin/stdout:

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "call_tool",
  "params": {
    "name": "nuclei",
    "arguments": {
      "target": "https://example.com",
      "templates": "cves"
    }
  }
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "content": "{\"template\":\"CVE-2021-41773\",\"host\":\"https://example.com\",\"matched\":\"/cgi-bin/.%2e/%2e%2e/\"}",
    "isError": false,
    "meta": {
      "signal_quality": "CONFIRMED",
      "duration_ms": 3421,
      "tool": "nuclei"
    }
  }
}
```

### Methods

| Method | Params | Returns | Line |
|--------|--------|---------|------|
| `ping` | — | `"pong"` | 430 |
| `list_tools` | — | `ToolDefinition[]` | 431 |
| `call_tool` | `{name, arguments}` | `ToolResult` | 433 |
| `agent_plan` | `{target, context}` | `{tool, args, reasoning, done}` | (new) |
| `agent_observe` | `{output}` | `{tool, args, reasoning, done}` | (new) |

### Tool execution flow (`call_tool`, lines 266-396)

```
1. Look up tool by name in self._tools
2. Build command: [tool.command] + tool.args + flattened parameters
   → e.g. ["nuclei", "-json", "-silent", "-u", "https://example.com", "-t", "cves"]
3. Validate all arguments against shell injection regex
4. Build locked-down environment (strip API keys, set PATH)
5. Run: subprocess.run(cmd, capture_output=True, timeout=tool.timeout)
6. Parse stdout into MCPToolResult
7. Return {content, isError, meta}
```

**Security:** The blocklist prevents running `bash`, `python`, `curl`, `wget`, `perl`, `ruby` as tools. Arguments are validated against a shell injection character set.

---

## 4. TypeScript-Side Tool Registration

**Location:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`

This is a **separate, smaller** file (33 tools) that the planner uses to map capabilities to tools. It does NOT include execution details (commands, args, parameters) — only capability mappings and scoring.

```yaml
- name: nuclei
  label: Nuclei Vulnerability Scanner
  capabilities:                     # ← What planner phases this satisfies
    - vulnerability_scanning
    - template_scanning
  requires_auth: false
  destructive: false
  supports_api: true
  supports_web: true
  timeout_seconds: 300
  scoring:
    confidence_score: 85           # How reliable are the findings?
    coverage_score: 90             # How broad is the coverage?
  signal_quality: CONFIRMED
  requires:
    tech_contains: []              # Gate: only run if tech matches
    target_scheme: any
  priority: 80
  cost: low
```

### How the TypeScript side uses this

**Planner** (`planner.ts:72`):
```typescript
const tools = toolRegistry.selectBest(phase.requiredCapabilities, targetType, gateContext)
// Returns: ToolDef[] — all tools that match the required capabilities and pass gates
// Ranked by: (confidence_score + coverage_score) then by priority
```

**Executor** (`executor.ts:133`):
```typescript
const tools = this.toolRegistry.getToolsByCapability(cap)
for (const tool of tools) {
  const result = await this.bridge.callTool(tool.name, { target, capability: cap, config })
  // ...parse output, promote confidence, store findings...
}
```

**MCP Bridge** (`mcp-client.ts:283`):
```typescript
async callTool(name: string, args: Record<string, any>): Promise<ToolResult> {
  const response = await this.sendRequest("call_tool", { name, arguments: args })
  return this.transformResult(response)
}
```

### Missing tools (Python has, TypeScript doesn't)

These 14+ tools exist in `tools/definitions/*.yaml` and `tool_definitions.py` but are MISSING from `tool-definitions.yaml`:

| Tool | Capability |
|------|-----------|
| `whatweb` | `technology_detection` |
| `wpscan` | `vulnerability_scanning` |
| `dalfox` | `sqli_detection` |
| `testssl` | `vulnerability_scanning` |
| `amass` | `web_recon` |
| `gitleaks` | *(no capability — needs `secret_detection`)* |
| `trufflehog` | *(no capability — needs `secret_detection`)* |
| `trivy` | `vulnerability_scanning` |
| `bandit` | *(no capability — needs `sast`)* |
| `semgrep` | *(no capability — needs `sast`)* |
| `gosec` | *(no capability — needs `sast`)* |
| `brakeman` | *(no capability — needs `sast`)* |
| `eslint` | *(no capability — needs `sast`)* |
| `spotbugs` | *(no capability — needs `sast`)* |

---

## 5. Planning: How Tools Are Selected

### Deterministic path (current default)

```
User runs: /assess https://example.com

1. strategy.ts:40 → determineRequiredCapabilities(targetType, authState, techStack)
   Returns: [WEB_RECON, PORT_SCANNING, TECHNOLOGY_DETECTION, VULNERABILITY_SCANNING, ...]

2. registry.ts:33 → WorkflowRegistry.findByCapabilities(capabilities)
   Finds best-matching workflow YAML (e.g., full_assessment.yaml)

3. planner.ts:72 → toolRegistry.selectBest(phase.requiredCapabilities, targetType, gateContext)
   For each phase, resolves capabilities → concrete tools:
   - WEB_RECON → [subfinder, gau, waybackurls, httpx, katana, ...]
   - PORT_SCANNING → [nmap, naabu]
   - VULNERABILITY_SCANNING → [nuclei, nikto, ...]

4. planner.ts:77-79 → Filters phases with zero tools (unless fail_fast)
   ⚠️ If a capability has NO tools mapped (like browser_verification),
      the phase is filtered out and produces nothing.

5. executor.ts:87 → execute(phase)
   For each capability → for each tool → call bridge.callTool(name, args)
```

### LLM-driven path (planned, Step 0.3-0.5)

```
1. Flow enters executeLLMDriven(phase)

2. bridge.agentPlan({target, phase, techStack, previousFindings, executedTools})
   → Python ReActAgent receives context
   → ReActAgent builds prompt with:
        - Full tool list from tool_definitions.py (68 tools, with descriptions)
        - Current phase capabilities
        - What's already been run
        - What findings exist so far
   → LLM returns: {tool: "nuclei", args: {templates: "cves"}, reasoning: "Apache detected..."}

3. bridge.callTool(decision.tool, decision.arguments)
   → Same MCP call_tool as deterministic path

4. bridge.agentObserve(output)
   → Feed tool output back to LLM
   → LLM returns next action or {done: true}
```

### Capability → Tool mapping

**File:** `Argus-Tui/packages/opencode/src/argus/shared/capabilities.ts`

Current capabilities (21) and which tools map to them:

| Capability | Tools in TypeScript `tool-definitions.yaml` |
|------------|---------------------------------------------|
| `web_recon` | subfinder, gau, waybackurls, amass*, gospider, wafw00f, httpx, katana, nikto |
| `port_scanning` | nmap, naabu |
| `technology_detection` | whatweb* |
| `content_discovery` | ffuf, katana, gospider |
| `vulnerability_scanning` | nuclei, nikto, testssl*, trivy*, semgrep*, bandit*, pip-audit |
| `template_scanning` | nuclei |
| `http_probe` | httpx |
| `api_probing` | arjun |
| `sqli_detection` | dalfox*, sqlmap |
| `database_exfiltration` | sqlmap |
| `jwt_analysis` | jwt_tool |
| `ssrf_check` | commix |
| `browser_verification` | **(NONE — this is why BOLA ran empty)** |
| `report_generation` | **(NONE — done in TypeScript code)** |

*`*` = tool exists in Python YAML but MISSING from TypeScript tool-definitions.yaml*

---

## 6. Execution: How Tools Actually Run

### Full call chain

```
[TypeScript]
executor.ts → bridge.callTool("nuclei", {target, templates: "cves"})
    │
    ▼
mcp-client.ts: sendRequest("call_tool", {name: "nuclei", arguments: {target, templates}})
    │
    ▼  (JSON-RPC over stdin/stdout)
[Python]
mcp_server.py: call_tool(params)
    │
    ├── 1. Look up tool: self._tools["nuclei"] → ToolDefinition
    │
    ├── 2. Build command:
    │      ["nuclei", "-json", "-silent", "-u", "https://example.com", "-t", "cves"]
    │
    ├── 3. Validate args: no shell injection chars
    │
    ├── 4. Build env: PATH augmented (venv/bin, ~/go/bin, /opt/homebrew/bin)
    │      Strip: API_KEYS, OPENAI_API_KEY, AWS_SECRET_ACCESS_KEY, etc.
    │
    ├── 5. Run: subprocess.run(cmd, capture_output=True, timeout=300)
    │      On timeout → SIGTERM → 5s grace → SIGKILL
    │
    ├── 6. Parse stdout → MCPToolResult {content, isError, meta}
    │
    └── 7. Return JSON-RPC response
    │
    ▼
[TypeScript]
mcp-client.ts: transformResult(response) → ToolResult {success, data, error, durationMs, signalQuality}
    │
    ▼
executor.ts: parse tool output → NormalizedFinding[]
    │
    ├── For each finding: confidenceEngine.promote() → adjust confidence
    ├── Save to EngagementStore (SQLite)
    └── Aggregate into PhaseExecutionResult
```

### Circuit breaker (`mcp-client.ts`)

- 3 consecutive `call_tool` failures → circuit opens for 5 minutes
- Subsequent calls return immediately with `{success: false, error: "circuit open"}`
- After 5 minutes, half-open → one test call → if success, close circuit
- Different tools have independent circuit breakers

---

## 7. Output Processing

### Current state (ad-hoc)

The executor parses tool output in TypeScript using tool-specific logic scattered across the codebase. There is **no unified parser**.

```typescript
// executor.ts (approximate)
if (toolName === "nuclei") {
  const lines = result.data.split("\n").filter(Boolean)
  for (const line of lines) {
    const parsed = JSON.parse(line) // nuclei outputs JSON lines
    findings.push({
      title: parsed.info.name,
      severity: mapSeverity(parsed.info.severity),
      description: parsed.info.description,
      tool: "nuclei",
      evidence: [{ type: "http", content: parsed.matched }],
    })
  }
} else if (toolName === "nmap") {
  // parse XML output...
}
```

### Planned state (Step 0.8)

Per-tool parsers on the Python side that return structured findings directly:

```python
# tool_core/parser/parsers/nuclei.py
def parse(output: str) -> list[NormalizedFinding]:
    findings = []
    for line in output.splitlines():
        data = json.loads(line)
        findings.append(NormalizedFinding(
            title=data["info"]["name"],
            severity=SEVERITY_MAP[data["info"]["severity"]],
            confidence=CONFIDENCE_MAP[data.get("signal_quality", "PROBABLE")],
            cwe=data["info"].get("classification", {}).get("cwe"),
            description=data["info"].get("description", ""),
            tool="nuclei",
            evidence=[ArtifactRef(type="http", content=data.get("matched", ""))],
        ))
    return findings
```

---

## 8. The ReActAgent (LLM-Driven Path)

**Location:** `argus-workers/agent/react_agent.py`

This is the **Python-side LLM agent** — currently disconnected from the CLI/TUI path.

### How it works

```
1. Target + Phase Context
         │
         ▼
2. Build prompt with:
   - Target info (URL, tech stack, auth state)
   - Tool descriptions from tool_definitions.py (68 tools)
   - Current phase capabilities
   - Previous findings (if any)
   - Executed tools list
         │
         ▼
3. LLM returns AgentAction:
   {tool: "nuclei", arguments: {templates: "cves"}, reasoning: "Apache 2.4.49...", done: false}
         │
         ▼
4. Execute tool via registry.call(action.tool, action.arguments)
   (same subprocess.run as MCP server)
         │
         ▼
5. Summarize output → feed back to LLM as observation
         │
         ▼
6. LLM returns next AgentAction or {done: true}
         │
         ▼
7. Loop until done or max_iterations reached
```

### Prompt structure (what the LLM sees)

```
You are a security assessment agent. You have the following tools available:

<tool name="nuclei">
  Description: Fast vulnerability scanner with YAML templates
  Capabilities: vulnerability_scanning, template_scanning
  Parameters: target (required), templates (optional), ...
  Signal quality: CONFIRMED
</tool>
<tool name="nmap">
  Description: Network Mapper
  Capabilities: port_scanning, technology_detection
  Parameters: target (required), ports (default: 1-1000), ...
  Signal quality: CONFIRMED
</tool>
... (all 68 tools)

Current target: https://example.com
Tech stack: [apache, php, mysql]
Phase: vulnerability_scanning
Already executed: [subfinder, httpx, whatweb]
Previous findings:
  - [MEDIUM] Apache 2.4.49 detected (CVE-2021-41773)
  - [INFO] PHP 7.4 detected

Decide which tool to run next. Respond with:
{"tool": "...", "arguments": {...}, "reasoning": "...", "done": false}
```

### Deterministic fallback

When the LLM is unavailable (API down, no key configured), the agent falls back to iterating through phase tools sequentially — same as the current TypeScript executor.

---

## 9. How to Create a New Tool — End-to-End

### Example: Adding `testssl` for TLS scanning

#### Step 1 — Create Python YAML definition

**File:** `argus-workers/tools/definitions/testssl.yaml` (new)

```yaml
name: testssl
command: testssl
description: TLS/SSL security scanner — checks cipher strength, protocol support, vulnerabilities
args:
  - --quiet
  - --jsonfile
  - /dev/stdout
parameters:
  - name: target
    flag: null
    type: string
    description: Target host:port
    required: true
  - name: severity
    flag: --severity
    type: string
    enum: [LOW, MEDIUM, HIGH, CRITICAL]
    default: MEDIUM
    description: Minimum severity to report
capabilities:
  - vulnerability_scanning
signal_quality: CONFIRMED
timeout: 300
enabled: true
requires:
  target_scheme: any
  tech_contains: []
priority: 60
cost: medium
risk_level: low
metadata:
  homepage: https://testssl.sh
```

#### Step 2 — Register in Python `tool_definitions.py`

**File:** `argus-workers/tool_definitions.py`

```python
_register(ToolDefinition(
    name="testssl",
    description="TLS/SSL security scanner",
    phases=["scan", "deep_scan"],
    binary="testssl",
    default_args=["--quiet", "--jsonfile", "/dev/stdout"],
    parameters=[
        {"name": "target", "flag": None, "type": "string", "required": True},
        {"name": "severity", "flag": "--severity", "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"], "default": "MEDIUM"},
    ],
    timeout=300,
    signal_quality="CONFIRMED",
    requires={},
    risk_level="low",
    estimated_cost="medium",
    metadata={"homepage": "https://testssl.sh"},
))
```

#### Step 3 — Add to TypeScript `tool-definitions.yaml`

**File:** `Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml`

```yaml
- name: testssl
  label: testssl TLS Scanner
  capabilities:
    - vulnerability_scanning
  requires_auth: false
  destructive: false
  supports_api: true
  supports_web: true
  timeout_seconds: 300
  scoring:
    confidence_score: 85
    coverage_score: 70
  signal_quality: CONFIRMED
  requires:
    tech_contains: []
    target_scheme: any
  priority: 60
  cost: medium
```

#### Step 4 — Add capability enum if needed

`testssl` maps to `vulnerability_scanning` which already exists. Skip this step.

If you were adding a tool for a NEW capability (e.g., `secret_detection` for `gitleaks`):

**File:** `Argus-Tui/packages/opencode/src/argus/shared/capabilities.ts`

```typescript
export enum Capability {
  // ...existing values...
  SECRET_DETECTION = "secret_detection",
}
```

#### Step 5 — Update workflow YAML if needed

If you want `testssl` to run in a specific workflow phase:

**File:** `Argus-Tui/packages/opencode/src/argus/workflows/full_assessment.yaml`

```yaml
- name: TLS Scanning
  required_capabilities:
    - vulnerability_scanning
  execution: sequential
  error_recovery: skip_and_continue
```

No change needed if an existing phase already requires `vulnerability_scanning` — the planner will automatically pick `testssl` when it's the best match.

#### Step 6 — Install the binary

```bash
# macOS
brew install testssl

# Linux
apt install testssl.sh  # or download from https://testssl.sh
```

The MCP server discovers tools via PATH (augmented with `~/go/bin`, `/opt/homebrew/bin`, `venv/bin`).

#### Step 7 — Verify

```bash
# Python side: tool loads in MCP server
cd argus-workers && python mcp_server.py
# Should log: "Loaded tool definition: testssl"

# TypeScript side: planner can select it
cd Argus-Tui/packages/opencode
bun run src/argus/main.ts doctor
# Should show testssl in toolchain check

# Full assessment should now run testssl when vulnerability_scanning is needed
bun run src/argus/main.ts assess https://example.com
```

### Files checklist per new tool

| # | File | Action | Required? |
|---|------|--------|-----------|
| 1 | `argus-workers/tools/definitions/<tool>.yaml` | Create | ✅ Always |
| 2 | `argus-workers/tool_definitions.py` | Add `_register()` call | ✅ Always |
| 3 | `Argus-Tui/.../workflows/tool-definitions.yaml` | Add entry | ✅ Always |
| 4 | `Argus-Tui/.../shared/capabilities.ts` | Add enum value | Only if new capability |
| 5 | `Argus-Tui/.../workflows/<workflow>.yaml` | Add phase | Only if new workflow needed |
| 6 | System PATH | Install binary | ✅ Always |

---

## 10. Summary: The Complete Tool Lifecycle

```
TOOL DEFINITION
    │
    ├── Python YAML (tools/definitions/*.yaml) ──→ MCP Server loads at startup
    │       ↓
    ├── Python tool_definitions.py ──→ ReActAgent uses for LLM context
    │
    └── TypeScript tool-definitions.yaml ──→ Planner uses for capability matching
            ↓
TOOL SELECTION
    │
    ├── Deterministic path:
    │       Planner → workflow YAML → capability lookup → tool list
    │
    └── LLM-driven path (planned):
            ReActAgent → LLM decides → agent_plan returns tool + args
            ↓
TOOL EXECUTION
    │
    └── MCP Bridge (TypeScript) → JSON-RPC → MCP Server (Python)
            ↓
    subprocess.run(tool.command + tool.args + parameters)
            ↓
    stdout/stderr captured → parsed → NormalizedFinding[]
            ↓
FINDING PERSISTENCE
    │
    ├── EngagementStore.saveFindings() → SQLite
    ├── ConfidenceEngine.promote() → adjust confidence
    └── IntelligenceEngine.enrich() → add CVE, EPSS, threat intel (Python side)
```
