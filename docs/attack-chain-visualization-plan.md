# Argus Attack Chain Visualization — Convergence Plan

> **Inspired by:** `ai-surface`'s radial cluster map (`src/ai_surface/ui/app.js`, ~1,900 lines of vanilla SVG)
> **Target:** Argus's existing `AttackGraph` Python engine + `AttackChain`/`ChainPhasePlan` TS types → an interactive, zero-dependency attack chain visualizer

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [The Core Concept: What We're Borrowing from ai-surface](#2-the-core-concept)
3. [Data Flow Architecture](#3-data-flow-architecture)
4. [Layout Algorithm: ai-surface → Attack Chain Adaptation](#4-layout-algorithm)
5. [Visual Encoding System](#5-visual-encoding-system)
6. [Interaction Model](#6-interaction-model)
7. [Implementation Workstreams](#7-implementation-workstreams)
8. [Code Snippets: Key Implementations](#8-code-snippets)
9. [Integration Points with Existing Systems](#9-integration-points)
10. [Sequencing & Effort](#10-sequencing--effort)
11. [Appendix A: ai-surface `drawMap()` Annotated Reference](#appendix-a)
12. [Appendix B: Complete API Schema for the Visualization Bridge](#appendix-b)

---

## 1. Current State Analysis

### What Argus Already Has (Backend — Python)

**`attack_graph.py`** — A fully operational graph engine with:
- `Node` (id, type, data, cvss, confidence, prerequisites, downstream_impacts)
- `Edge` (from_node, to_node, edge_type, correlation_factor, relationship_type)
- `Path` (nodes, edges) 
- `AttackGraph.find_chains()` — chain detection from 8 `CHAIN_RULES` templates
- `AttackGraph.compute_risk()` — risk scoring with confidence decay
- `AttackGraph.to_snapshot_dict()` — serializes to `{ "paths": [ { nodes, edges, risk_score } ] }`

**`attack_graph_db.py`** — Persistence via `attack_paths` table with:
- Full JSONB storage of path nodes/edges
- Chain exploit script preservation across re-saves
- `load_graph()` reconstruction from DB

**`chain_exploit_generator.py`** — LLM-driven weaponized script generation

**`attack_composition/planner.py`** — Converts chains to phase plans

### What Argus Already Has (Frontend — TypeScript)

**`planner/types.ts`** — Data interfaces already exist:
```typescript
interface AttackChain {
  chain_id: string
  name: string
  severity: string
  correlation_factor: number
  prerequisite_type: string
  chain_type: string
  description: string
}

interface ChainPhasePlan {
  chain_id: string
  name: string
  severity: string
  risk_score: number
  prerequisite_finding_types: string[]
  suggested_capabilities: string[]
  description: string
}
```

**`planner/planner.ts`** — `WorkflowPlanner.replan()` already uses chain plans:
- Creates `PhaseExecutionRequest` from `chainPlans` 
- Generates `chain-{replanCount}-{chain_id}` phase IDs
- Maps suggested capabilities to actual `Capability` enum values

**`engagement/types.ts`** — `EngagementState` stores full engagement lifecycle

**`engagement/store.ts`** — Provides `getEngagementDetail()` via `IEngagementStore`

### What's Missing

| Feature | Status |
|---------|--------|
| Python-side graph data → TS-side visualization API | ❌ No bridge exists |
| Interactive radial cluster map rendering | ❌ No graph UI component |
| Chain highlighting (hover/click/selections) | ❌ Missing |
| File-path evidence browsing per node | ❌ Partial (findings list only) |
| Drill-down drawer for chain details | ❌ Missing |
| Theme-aware SVG rendering | ❌ Missing |
| Real-time chain discovery streaming | ❌ Missing |

### What ai-surface Brings (The Reference)

The `ui/app.js` file (~1,900 lines) provides a production-quality reference for:

1. **Radial cluster layout** (~160 lines for `drawMap()`):
   - Deterministic trigonometry (no physics, no D3.js)
   - 3-layer hierarchy: center → category hubs → finding leaves
   - Auto-scaling radii, banding for dense categories
   - Severity-based node sizing and color

2. **Interaction model** (~80 lines for `wireMapInteraction()`, `wireDrawer()`):
   - Hover dims out-of-category nodes (CSS class `dim`/`related`)
   - Click leaf → opens detail drawer with finding evidence
   - Click hub → jumps to filtered findings tab
   - Keyboard-accessible tab navigation

3. **Detail drawer** (~120 lines for `drawerHTML()`, `openDrawer()`):
   - Slide-in panel with evidence, risk flags, code snippets
   - Per-finding audit results and bridge links

4. **App shell** (~300 lines for topbar, hero, tabs, theme toggle):
   - Two-color theme (light/dark) via CSS variables
   - Tabbed workspace (Overview, Findings, Audits, Validate)
   - Welcome screen vs. loaded report state

**Zero dependencies.** No React, no Vue, no D3.js, no build step. Pure SVG + vanilla JS.

---

## 2. The Core Concept: What We're Borrowing from ai-surface

### The Adaptation: AI Surface Map → Attack Chain Map

```
ai-surface Layer           →  Argus Attack Chain Layer
─────────────────────────────────────────────────────
scan root (center node)    →  engagement target URL/domain
category hub (Ring 1)      →  vulnerability type hub (XSS, SSRF, IDOR, RCE...)
finding leaf (Ring 2)      →  individual finding instance (type + endpoint)
severity color             →  Argus Severity enum (CRITICAL/HIGH/MEDIUM/LOW/INFO)
risk ring (assessed glow)  →  chain membership indicator
evidence drawer            →  finding detail + exploit chain script + PoC
bridge links (upgrade)     →  chain verification links (ChainExploitGenerator)
```

### What Changes Conceptually

| ai-surface | Argus Adaptation | Reasoning |
|------------|-----------------|-----------|
| Single-center radial | **Multi-center radial** — one cluster per attack chain | Argus has multiple independent chains, not one scan root |
| Fixed depth (center → hub → leaf) | **Variable depth** — chain paths of N nodes | Attack chains cascade (e.g., XSS → CSRF → ATO = 3 vulns) |
| Category grouping only | **Relationship-typed edges** — CAUSES, AMPLIFIES, ENABLES, DEPENDS_ON | Argus has typed edges, not just "belongs to" |
| Static report data | **Live data from MCP bridge** | Chains discovered during execution, not pre-scanned |
| Severity-based legends | **Risk-score-based legends** (0.0-10.0) | Argus uses CVSS-like risk scoring |
| Single report JSON | **Time-series snapshots** — chain state at each replan | Chains evolve as new findings are added |

---

## 3. Data Flow Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                        PYTHON BACKEND                             │
│                                                                    │
│  AttackGraph                                                       │
│  ├─ add_finding() ──→ Node, Edge                                  │
│  ├─ find_chains() ──→ Chain detections                            │
│  ├─ compute_risk() ──→ Risk scores                                │
│  └─ to_snapshot_dict() ──→ { paths: [{ nodes, edges, risk }] }   │
│         │                                                         │
│         ▼                                                         │
│  AttackGraphRepository.save_paths()                               │
│         │                                                         │
│         ▼                                                         │
│  PostgreSQL: attack_paths table                                   │
│  - path_nodes (JSONB: nodes + edges)                              │
│  - risk_score, normalized_severity                                │
│  - chain_exploit_script (optional)                                │
│         │                                                         │
│         ▼                                                         │
│  MCP Bridge (mcp_server.py)                                       │
│  └─ tool: "get_attack_graph_snapshot"                             │
│         │                                                         │
│         ▼                                                         │
├────────────────────────────────────────────────────────────────────┤
│                       TYPESCRIPT FRONTEND                         │
│                                                                    │
│  PlannerContext.attackChains[]      ◄── MCP bridge response       │
│  PlannerContext.chainPlans[]                                       │
│         │                                                         │
│         ▼                                                         │
│  AttackGraphVisualizer (NEW)                                      │
│  ├─ parseGraphData() ──→ Normalized graph for rendering           │
│  ├─ drawAttackMap() ──→ SVG radial cluster                        │
│  ├─ wireInteraction() ──→ Hover/click/drawer                      │
│  └─ renderDrawer() ──→ Finding + chain detail                     │
│         │                                                         │
│         ▼                                                         │
│  TUI Integration (status-popover, titlebar, session pages)        │
│  └─ Embed in engagement detail view                               │
└────────────────────────────────────────────────────────────────────┘
```

### Key Data Bridge: `to_snapshot_dict()` Output Schema

The existing `AttackGraph.to_snapshot_dict()` already produces the exact JSON needed:

```json
{
  "paths": [
    {
      "risk_score": 8.5,
      "nodes": [
        {
          "id": "vuln_XSS_/api/users",
          "type": "vulnerability",
          "data": { "type": "XSS", "severity": "HIGH", "endpoint": "/api/users", "source_tool": "dalfox" },
          "cvss": 7.5,
          "confidence": 0.85,
          "prerequisites": ["user_interaction", "no_csp"],
          "downstream_impacts": ["session_theft", "credential_capture"]
        },
        {
          "id": "endpoint_/api/users",
          "type": "endpoint",
          "data": { "url": "/api/users" },
          "cvss": null,
          "confidence": null
        }
      ],
      "edges": [
        {
          "from_node": "vuln_XSS_/api/users",
          "to_node": "endpoint_/api/users",
          "type": "independent",
          "correlation_factor": 1.0,
          "relationship_type": "RelationshipType.AMPLIFIES"
        }
      ]
    }
  ]
}
```

**No backend changes needed.** The data is already structured for visualization. The only new code is on the TypeScript side.

---

## 4. Layout Algorithm: ai-surface → Attack Chain Adaptation

### 4.1 Base Layout (Copied from ai-surface)

The core `drawMap()` algorithm from ai-surface uses deterministic trigonometry:

```
                    ┌──────────────────────┐
                    │   Target: example.com │  ← Center node (engagement target)
                    │    (risk score: 8.2)  │    Radius: 34px, gradient fill
                    └──────────────────────┘
                           ╱    │    ╲        ← Quadratic bezier edges
                          ╱     │     ╲             (hubEdge)
                    ┌─────┐ ┌─────┐ ┌─────┐
                    │ XSS │ │SSRF │ │IDOR │  ← Ring 1: Vulnerability type hubs
                    │Hub  │ │Hub  │ │Hub  │    Radius: 0.205 × viewBox min
                    └──┬──┘ └──┬──┘ └──┬──┘    Size: 13 + min(childCount, 12) × 1.6
                     ╱│╲      ╱│╲      ╱│╲
                    ╱ │ ╲    ╱ │ ╲    ╱ │ ╲
                  ┌┐ ┌┐ ┌┐ ┌┐ ┌┐ ┌┐ ┌┐ ┌┐ ┌┐
                  ││ ││ ││ ││ ││ ││ ││ ││ ││  ← Ring 2: Individual findings
                  └┘ └┘ └┘ └┘ └┘ └┘ └┘ └┘ └┘    Radius: 0.40-0.47 × viewBox min
                                                    Banded when > 6 findings per hub
```

### 4.2 Adaptation: Multi-Chain Clustering

The key difference: Argus has multiple **independent chain clusters**, not one monolithic center. Each chain gets its own sub-cluster:

```
                    ┌──────────────────┐
                    │  Engagement Overview │  ← Center: summary + metrics
                    └──────────────────┘
                    ╱        │          ╲
                   ╱         │           ╲
             ┌─────────┐ ┌─────────┐ ┌─────────┐
             │Chain 1  │ │Chain 2  │ │Chain 3  │  ← Per-chain clusters
             │SSRF→RCE │ │XSS→ATO  │ │IDOR→PE  │    Each chain is a sub-radial
             └────┬────┘ └────┬────┘ └────┬────┘
                 ╱│╲         ╱│╲         ╱│╲
                ╱ │ ╲       ╱ │ ╲       ╱ │ ╲
              ┌┐ ┌┐ ┌┐    ┌┐ ┌┐ ┌┐    ┌┐ ┌┐ ┌┐
              ││ ││ ││    ││ ││ ││    ││ ││ ││
```

### 4.3 Detailed Layout Parameters

```javascript
// ── Adapted from ai-surface's drawMap() layout constants ──

const W = 1000, H = 688;               // viewBox (16:11)
const cx = W / 2, cy = H / 2;          // center
const minWH = Math.min(W, H);           // 688

// ── If single engagement center (no chain grouping) ──
const hubR = minWH * 0.205;             // ~141px — vulnerability type hubs
const leafBase = minWH * 0.40;          // ~275px — innermost findings
const leafMax = minWH * 0.47;           // ~323px — outermost for dense categories
const sector = (Math.PI * 2) / cats.length;  // per-category wedge
const startAngle = -Math.PI / 2;        // start at top (12 o'clock)

// ── If chain-clustered layout (multiple chains) ──
const chainCenterR = minWH * 0.18;      // chain cluster centers on a ring
const chainHubR = minWH * 0.14;         // within each chain, hub radius from chain center
const chainLeafBase = minWH * 0.22;     // leaves within each chain
const chainLeafMax = minWH * 0.28;
```

### 4.4 Node Positioning: The Trigonometry (from ai-surface)

```javascript
// ── Hub positioning (Ring 1) ──
cats.forEach((cat, i) => {
  const ang = startAngle + (i / cats.length) * Math.PI * 2;
  const hx = cx + Math.cos(ang) * hubR;
  const hy = cy + Math.sin(ang) * hubR;
  // ...
});

// ── Leaf positioning (Ring 2) — adapted for chain depth ──
leaves.forEach((f, j) => {
  const n = leaves.length;
  const arc = n <= 1 ? 0 : Math.min(sector * 0.74, 0.16 * n);
  const bands = Math.max(1, Math.ceil(n / 6));
  const bandGap = bands > 1 ? (leafMax - leafBase) / (bands - 1) : 0;
  
  const band = j % bands;
  const t = n === 1 ? 0 : (j / (n - 1)) - 0.5;
  const la = ang + t * arc;
  const lr = leafBase + band * bandGap;
  const lx2 = cx + Math.cos(la) * lr;
  const ly2 = cy + Math.sin(la) * lr;
});
```

**Key addition for chain paths:** Instead of all leaves at the same depth from their hub, chain-path nodes follow a **flow direction** — the second vulnerability in a chain is placed further out (higher radius) and visually connected via a distinct edge style (dashed, colored by relationship type):

```javascript
// ── Chain-aware leaf positioning ──
leaves.forEach((f, j) => {
  // Standard leaf position first
  const baseR = leafBase + band * bandGap;
  
  // If this finding is part of a chain, shift outward based on position in chain
  const chainDepth = f.chain_position ?? 0;  // 0 = first, 1 = second, etc.
  const depthOffset = chainDepth * 18;        // 18px per chain step
  const lr = baseR + depthOffset;
  
  // ...
  // Edge from hub: solid for regular, dashed for chain links
  const isChainEdge = f.chain_id != null;
  // render with appropriate stroke-dasharray if chained
});
```

---

## 5. Visual Encoding System

### 5.1 Node Encoding (adapted from ai-surface conventions)

| Attribute | ai-surface Convention | Argus Adaptation |
|-----------|---------------------|------------------|
| **Center** | Scan root name | Engagement target URL (shortened) |
| **Hub radius** | `13 + min(children, 12) × 1.6` | Same — vulnerability count |
| **Leaf radius** | `assessed ? 9 + SEV_RANK × 1.7 : 7.5` | Same — but SEV_RANK uses Argus Severity enum |
| **Leaf fill** | Severity color (assessed) / neutral (inventory) | Severity color (all Argus findings have severity) |
| **Stroke** | `transparent` (assessed) / `var(--line-2)` (inventory) | `var(--line-2)` for endpoint nodes |
| **Ring glow** | Assessed risk glow | Chain membership glow |
| **Hit target** | `Math.max(r + 9, 17)` transparent disc | Same — ensures small nodes clickable |

### 5.2 Color Palette (Argus-specific)

```javascript
// ── Based on Argus Severity enum — adapt from ai-surface's CSS vars ──
const SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const SEV_RANK = { CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1 };
const SEV_COLORS = {
  CRITICAL: "#dc2626",  // red
  HIGH:     "#ea580c",  // orange
  MEDIUM:   "#ca8a04",  // amber/yellow
  LOW:      "#2563eb",  // blue
  INFO:     "#6b7280",  // gray
};

// ── Relationship type edge colors ──
const RELATIONSHIP_COLORS = {
  CAUSES:     "#dc2626",  // red — causal link
  AMPLIFIES:  "#ea580c",  // orange — amplifies severity
  ENABLES:    "#2563eb",  // blue — enables follow-up
  DEPENDS_ON: "#6b7280",  // gray — prerequisite
  MITIGATES:  "#16a34a",  // green — reduces risk
  INDEPENDENT: "#9ca3af", // light gray — no relationship
};
```

### 5.3 Edge Styles

| Edge Type | ai-surface | Argus Adaptation |
|-----------|-----------|------------------|
| Center → Hub | Quadratic bezier, `opacity: 0.7` | Same — engagement → vuln type |
| Hub → Leaf | Quadratic bezier, `opacity: 0.5` | Same — vuln type → finding |
| Chain path (vuln → vuln) | N/A | **Dashed** bezier, colored by relationship type |
| Preview/ghost path | N/A | **Dotted**, low opacity for non-selected paths |

### 5.4 Icon Set (from ai-surface, adapted)

ai-surface ships with 20+ SVG icons as inline path data in `ICONS`:
- `chip` (LLM SDKs), `agent` (agents), `plug` (MCP), `route` (gateways)
- `server` (infra), `key` (secrets), `globe` (APIs), `vector` (vector stores)
- `file` (evidence), `arrow` (navigation), `lock` (auth), `shield` (audit)
- `warn` (risk), `info` (informational), `search` (search), `close` (close)
- `sun`/`moon` (theme), `download` (export), `caret` (collapse)

Argus can reuse the same icon infrastructure with new icons for:
- `chain` (attack chain), `bug` (vulnerability), `target` (engagement)
- `script` (exploit script), `poc` (proof of concept)
- `sandbox` (sandbox verification), `verified` (confirmed)

---

## 6. Interaction Model

### 6.1 Hover Behavior (from ai-surface `wireMapInteraction()`)

```javascript
function focusCategory(g, cat) {
  g.classList.add("dim");
  g.querySelectorAll(".node").forEach((n) => {
    if (n.classList.contains("node-center") || n.dataset.cat === cat)
      n.classList.add("related");
  });
  g.querySelectorAll(".edge").forEach((e) => {
    if (e.dataset.cat === cat) e.classList.add("related");
  });
}

function unfocus(g) {
  g.classList.remove("dim");
  g.querySelectorAll(".related").forEach((n) => n.classList.remove("related"));
}
```

**Argus adaptations:**
- **Hover hub** → highlights all findings of that vulnerability type + all chain edges involving those findings
- **Hover leaf** → highlights that finding's chain path (prerequisites + downstream impacts)
- **Hover chain path edge** → highlights the full chain (all nodes in the chain light up)
- **Dim** → 0.15 opacity (ai-surface uses CSS `:not(.related) { opacity: 0.15 }`)

### 6.2 Click Behavior

| Element | ai-surface Action | Argus Action |
|---------|------------------|-------------|
| Center node | — (no click handler) | Open engagement summary |
| Hub (vuln type) | Jump to Findings tab, filtered by category | Jump to findings list, filtered by vulnerability type |
| Leaf (finding) | Open detail drawer with evidence | Open detail drawer with finding + chain info + exploit script |
| Chain path edge | N/A | Open chain detail panel (nodes, risk score, script) |
| Empty space | — | Deselect everything, return to overview |

### 6.3 Detail Drawer (from ai-surface `drawerHTML()`)

The ai-surface drawer (slide-in from right) shows per-finding:
- Surface name, category, severity badge
- Risk flags table (FLAG_LABELS mapping)
- Evidence files and code snippets
- Audit results (secrets, trust score, OWASP mappings)
- Bridge links (upgrade CTAs)

**Argus drawer shows per-finding:**
- Finding type, severity, endpoint, confidence %
- **Chain membership** (which chains this finding belongs to)
- Prerequisites (what must be true for this to be exploitable)
- Downstream impacts (what this enables)
- **Chain exploit script** (if generated by `ChainExploitGenerator`)
- **PoC** (if generated by `PoCGenerator`)
- Evidence (request/response, payload, file paths)
- **Verification status** (sandbox-verified? runtime-confirmed?)
- Downstream path exploration (linked findings)

### 6.4 Keyboard Navigation (from ai-surface `wireTabs()`)

ai-surface implements full keyboard-accessible tab navigation:
```
ArrowRight / ArrowDown  →  Next tab
ArrowLeft  / ArrowUp    →  Previous tab
Home                    →  First tab
End                     →  Last tab
```

Argus adds keyboard graph navigation:
```
Tab                    →  Cycle through nodes (focus ring on selected)
Arrow keys             →  Move selection to adjacent node
Enter / Space          →  Open selected node's drawer
Escape                 →  Close drawer, return to overview
```

---

## 7. Implementation Workstreams

### Workstream V1: Data Bridge (1 day)

**Goal:** Make attack graph data available to the frontend for rendering.

**Files:** `mcp_server.py` (new MCP tool), `planner/types.ts` (extend PlannerContext)

1. **Add MCP tool `get_attack_graph_snapshot`** that:
   - Accepts `engagement_id`
   - Calls `AttackGraphRepository.load_graph(engagement_id)`
   - Returns `graph.to_snapshot_dict()`
   - Includes chain metadata (chain_id, name, correlation_factor per path)

2. **Extend `PlannerContext`** with processed graph data:
   ```typescript
   // In planner/types.ts
   export interface PlannerContext {
     // ... existing fields
     attackGraph?: AttackGraphSnapshot  // NEW: full graph data for visualization
   }
   
   export interface AttackGraphSnapshot {
     paths: AttackPathData[]
     metadata: {
       totalPaths: number
       totalFindings: number
       highestRiskScore: number
       chainsDetected: number
     }
   }
   
   export interface AttackPathData {
     risk_score: number
     nodes: GraphNodeData[]
     edges: GraphEdgeData[]
     chain_id?: string
     chain_name?: string
   }
   ```

3. **Wire into the UI event bridge** so `onProgress` events carry graph snapshots when they change.

### Workstream V2: SVG Renderer (2 days)

**Goal:** Build the standalone SVG attack chain graph renderer.

**File:** `packages/opencode/src/argus/visualizer/attack-map.ts` (NEW)

1. **Port ai-surface's SVG builder helpers:**
   ```typescript
   // SVG helpers (direct port from ai-surface's app.js)
   const NS = "http://www.w3.org/2000/svg"
   function mk(tag: string): SVGElement { return document.createElementNS(NS, tag) }
   function disc(x, y, r, fill, stroke, sw, cls): SVGCircleElement { ... }
   function ringEl(x, y, r, stroke, sw, op, cls): SVGCircleElement { ... }
   function edge(x1, y1, x2, y2, sw, op, dashed?): SVGPathElement { ... }
   function text(x, y, str, cls): SVGTextElement { ... }
   ```

2. **Implement `drawAttackMap()`** — adapted from ai-surface's `drawMap()`:
   - Parse `AttackGraphSnapshot` into `byVulnType` groups (analogous to `byCat`)
   - Calculate hub/leaf positions using the same trigonometry
   - Add chain path edges (dashed, colored by relationship type)
   - Add legend (severity, relationship types, chain paths)
   - Handle empty, single-node, and dense states

3. **Implement `wireMapInteraction()`** — adapted from ai-surface:
   - Hover dim/highlight (CSS class toggling)
   - Click → drawer via callback
   - Keyboard navigation

4. **CSS variables:**
   ```css
   :root {
     --sev-critical: #dc2626;
     --sev-high: #ea580c;
     --sev-medium: #ca8a04;
     --sev-low: #2563eb;
     --sev-info: #6b7280;
     --sev-none: #9ca3af;
     /* hub */
     --hub-fill: #1e293b;
     --hub-fill-hover: #334155;
     /* edges */
     --edge-chain: #7c3aed;
     --edge-causes: #dc2626;
     --edge-enables: #2563eb;
     --edge-amplifies: #ea580c;
     --edge-mitigates: #16a34a;
     --edge-depends: #6b7280;
     /* brand */
     --brand: #7c5cff;
     --brand-2: #4f6dff;
   }
   ```

### Workstream V3: Detail Drawer (1 day)

**Goal:** Per-finding and per-chain detail panel, adapted from ai-surface's drawer.

**File:** `packages/opencode/src/argus/visualizer/drawer.ts` (NEW)

1. **Finding detail view:**
   - Finding type + severity badge (from ai-surface `severityColor()`)
   - Endpoint URL / file path
   - CVSS score, confidence bar
   - Prerequisites list (with satisfaction status)
   - Downstream impacts list
   - Chain membership badges (clickable → jump to chain)
   - Evidence panel (request/response/code snippets)

2. **Chain detail view** (NEW — no ai-surface equivalent):
   - Chain name + overall severity + risk score
   - Step-by-step chain visualization (mini-linear flow diagram)
   - Per-step finding details with expand/collapse
   - Exploit script panel (syntax-highlighted, collapsible)
   - Verification status (sandbox-verified? runtime-confirmed?)
   - "Verify in sandbox" button (calls ChainExploitGenerator API)

3. **Drawer behavior** (from ai-surface `openDrawer()`):
   - Slide-in from right with CSS transition (`transform: translateX(0)`)
   - Overlay backdrop (semi-transparent, click to close)
   - Escape key to close
   - Tab trapping inside drawer

### Workstream V4: TUI Integration (1 day)

**Goal:** Embed the graph in the Argus code editor experience.

**Files:** `packages/app/src/pages/session.tsx`, `packages/app/src/components/status-popover.tsx`

1. **Session page integration:**
   - Add an "Attack Map" tab/section next to findings
   - Fetch graph data via MCP bridge on engagement load
   - Re-render when replan produces new chains

2. **Status popover integration:**
   - Show mini-map thumbnail in the engagement status popover
   - Click to expand full map view
   - Chain count badge

### Workstream V5: ai-surface Integration (Bridge to V2 of the Plan)

Once the Argus-native visualizer is built, integrate ai-surface's actual findings:

1. After running `ai-surface scan . --output json`, parse the JSON
2. Map ai-surface's 8 categories + findings → Argus `VulnerabilityFinding` schema
3. Add these findings to the `AttackGraph` alongside conventional findings
4. The visualizer will automatically render them as additional hubs + leaves

---

## 8. Code Snippets: Key Implementations

### 8.1 Complete SVG Builder (Ported from ai-surface)

```typescript
// packages/opencode/src/argus/visualizer/svg-builders.ts

const NS = "http://www.w3.org/2000/svg"

export function mk(tag: string): SVGElement {
  return document.createElementNS(NS, tag)
}

export function disc(
  x: number, y: number, r: number, 
  fill: string, stroke: string, sw: number, cls?: string
): SVGCircleElement {
  const c = mk("circle") as SVGCircleElement
  c.setAttribute("cx", String(x))
  c.setAttribute("cy", String(y))
  c.setAttribute("r", String(r))
  c.setAttribute("fill", fill)
  c.setAttribute("stroke", stroke)
  c.setAttribute("stroke-width", String(sw))
  if (cls) c.setAttribute("class", cls)
  return c
}

export function ringEl(
  x: number, y: number, r: number,
  stroke: string, sw: number, op: number, cls?: string
): SVGCircleElement {
  const c = mk("circle") as SVGCircleElement
  c.setAttribute("cx", String(x))
  c.setAttribute("cy", String(y))
  c.setAttribute("r", String(r))
  c.setAttribute("fill", "none")
  c.setAttribute("stroke", stroke)
  c.setAttribute("stroke-width", String(sw))
  c.setAttribute("opacity", String(op))
  if (cls) c.setAttribute("class", cls)
  return c
}

export function edge(
  x1: number, y1: number, x2: number, y2: number,
  sw: number, op: number, dashed = false
): SVGPathElement {
  const l = mk("path") as SVGPathElement
  // Gentle quadratic curve for organic feel (same formula as ai-surface)
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
  const dx = x2 - x1, dy = y2 - y1
  const off = 0.12
  const qx = mx - dy * off, qy = my + dx * off
  l.setAttribute("d", `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`)
  l.setAttribute("class", dashed ? "edge edge-chain" : "edge")
  l.setAttribute("opacity", String(op))
  if (dashed) l.setAttribute("stroke-dasharray", "6,4")
  return l
}

export function text(x: number, y: number, str: string, cls: string): SVGTextElement {
  const t = mk("text") as SVGTextElement
  t.setAttribute("x", String(x))
  t.setAttribute("y", String(y))
  t.setAttribute("class", cls)
  t.textContent = str
  return t
}
```

### 8.2 Core Draw Function (Adapted for Argus)

```typescript
// packages/opencode/src/argus/visualizer/attack-map.ts

export interface AttackGraphVisualizerOptions {
  width?: number           // viewBox width (default 1000)
  height?: number          // viewBox height (default 688)
  onNodeClick?: (nodeId: string) => void
  onHubClick?: (vulnType: string) => void
  onChainClick?: (chainId: string) => void
}

export class AttackGraphVisualizer {
  private svg: SVGSVGElement | null = null
  private g: SVGGElement | null = null
  private edgeLayer: SVGGElement | null = null
  private nodeLayer: SVGGElement | null = null
  private data: AttackGraphSnapshot | null = null
  private options: Required<AttackGraphVisualizerOptions>
  private W = 1000
  private H = 688

  constructor(options?: AttackGraphVisualizerOptions) {
    this.options = {
      width: options?.width ?? 1000,
      height: options?.height ?? 688,
      onNodeClick: options?.onNodeClick ?? (() => {}),
      onHubClick: options?.onHubClick ?? (() => {}),
      onChainClick: options?.onChainClick ?? (() => {}),
    }
    this.W = this.options.width
    this.H = this.options.height
  }

  render(container: HTMLElement, data: AttackGraphSnapshot): void {
    this.data = data
    container.innerHTML = ""
    
    this.svg = document.createElementNS(NS, "svg") as SVGSVGElement
    this.svg.setAttribute("viewBox", `0 0 ${this.W} ${this.H}`)
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet")
    
    const g = mk("g") as SVGGElement
    g.setAttribute("class", "graph")
    this.svg.appendChild(g)
    this.g = g
    
    this.edgeLayer = mk("g") as SVGGElement
    this.nodeLayer = mk("g") as SVGGElement
    g.appendChild(this.edgeLayer)
    g.appendChild(this.nodeLayer)
    
    this.drawAllPaths()
    this.wireInteraction()
    
    container.appendChild(this.svg)
  }

  private drawAllPaths(): void {
    const { paths } = this.data!
    if (paths.length === 0) {
      this.renderEmpty()
      return
    }

    const cx = this.W / 2, cy = this.H / 2
    const minWH = Math.min(this.W, this.H)

    // Collect all unique vulnerability types as hubs
    const byType = new Map<string, GraphNodeData[]>()
    for (const path of paths) {
      for (const node of path.nodes) {
        if (node.type === "vulnerability") {
          const vulnType = node.data.type
          if (!byType.has(vulnType)) byType.set(vulnType, [])
          byType.get(vulnType)!.push(node)
        }
      }
    }

    const cats = [...byType.keys()]
    const hubR = minWH * 0.205
    const leafBase = minWH * 0.40
    const leafMax = minWH * 0.47
    const sector = (Math.PI * 2) / cats.length
    const startAngle = -Math.PI / 2

    // ── Draw center node (engagement target or "Attack Graph") ──
    const center = mk("g") as SVGGElement
    center.setAttribute("class", "node node-center")
    center.appendChild(disc(cx, cy, 34, "var(--hub-fill)", "var(--line-2)", 1.5))
    center.appendChild(disc(cx, cy, 30, "url(#coreGrad)", "none", 0))
    center.appendChild(text(cx, cy + 60, "Attack Graph", "lbl"))
    this.nodeLayer!.appendChild(center)

    // ── Draw hubs + leaves for each vulnerability type ──
    cats.forEach((type, i) => {
      const ang = startAngle + (i / cats.length) * Math.PI * 2
      const hx = cx + Math.cos(ang) * hubR
      const hy = cy + Math.sin(ang) * hubR
      const nodes = byType.get(type)!

      // Edge center → hub
      const hubEdge = edge(cx, cy, hx, hy, 1.7, 0.7)
      hubEdge.dataset.type = type
      this.edgeLayer!.appendChild(hubEdge)

      // Hub disc
      const hr = 13 + Math.min(nodes.length, 12) * 1.6
      const hub = mk("g") as SVGGElement
      hub.setAttribute("class", "node node-hub")
      hub.dataset.type = type
      hub.appendChild(ringEl(hx, hy, hr + 6, "var(--brand-2)", 1.2, 0.35))
      hub.appendChild(disc(hx, hy, hr, "var(--hub-fill)", "var(--line-2)", 1.4))
      hub.appendChild(text(hx, hy + 4, String(nodes.length), "count"))
      
      // Hub label (outside, auto-positioned)
      const lx = cx + Math.cos(ang) * (hubR + hr + 14)
      const ly = cy + Math.sin(ang) * (hubR + hr + 14)
      const hl = text(lx, ly + 4, titleCase(type), "lbl")
      hl.setAttribute("text-anchor", 
        Math.cos(ang) < -0.25 ? "end" : Math.cos(ang) > 0.25 ? "start" : "middle")
      hub.appendChild(hl)
      this.nodeLayer!.appendChild(hub)

      // ── Leaves ──
      const n = nodes.length
      const arc = n <= 1 ? 0 : Math.min(sector * 0.74, 0.16 * n)
      const bands = Math.max(1, Math.ceil(n / 6))
      const bandGap = bands > 1 ? (leafMax - leafBase) / (bands - 1) : 0

      nodes.forEach((node, j) => {
        const band = j % bands
        const t = n === 1 ? 0 : (j / (n - 1)) - 0.5
        const la = ang + t * arc
        const lr = leafBase + band * bandGap
        const lx2 = cx + Math.cos(la) * lr
        const ly2 = cy + Math.sin(la) * lr

        // Edge hub → leaf
        const leafEdge = edge(hx, hy, lx2, ly2, 1.2, 0.5)
        leafEdge.dataset.type = type
        this.edgeLayer!.appendChild(leafEdge)

        // Determine if this node is part of a chain
        const isChained = paths.some(p => 
          p.chain_id && p.nodes.some(n => n.id === node.id))
        
        const sev = node.data.severity
        const sevRank = SEV_RANK[sev] ?? 0
        const r = sev ? 9 + sevRank * 1.7 : 7.5
        const fill = sev ? SEV_COLORS[sev] : "var(--node-fill)"
        const stroke = sev ? "transparent" : "var(--line-2)"

        const leaf = mk("g") as SVGGElement
        leaf.setAttribute("class", "node node-leaf")
        leaf.dataset.id = node.id
        leaf.dataset.type = type

        // Hit target (generous, same as ai-surface)
        leaf.appendChild(disc(lx2, ly2, Math.max(r + 9, 17), "transparent", "none", 0))

        if (isChained) {
          // Chain membership glow
          leaf.appendChild(ringEl(lx2, ly2, r + 6, "var(--edge-chain)", 2, 0.9))
        }

        leaf.appendChild(disc(lx2, ly2, r, fill, stroke, sev ? 0 : 1.4))

        // Label if not too crowded
        if (n <= 8) {
          const showLeft = Math.cos(la) < 0
          const label = text(
            lx2 + (showLeft ? -(r + 7) : (r + 7)), ly2 + 4,
            shortName(node.data.type), "lbl"
          )
          label.setAttribute("text-anchor", showLeft ? "end" : "start")
          leaf.appendChild(label)
        }
        
        // Tooltip
        const title = mk("title") as SVGTitleElement
        title.textContent = `${node.data.type} · ${sev ?? "no severity"} · ${node.data.endpoint}`
        leaf.appendChild(title)

        this.nodeLayer!.appendChild(leaf)
      })
    })

    // ── Draw chain edges (dashed, between vulnerability nodes) ──
    for (const path of paths) {
      if (!path.chain_id) continue
      const vulnNodes = path.nodes.filter(n => n.type === "vulnerability")
      for (let i = 0; i < vulnNodes.length - 1; i++) {
        const from = vulnNodes[i]
        const to = vulnNodes[i + 1]
        // Find element positions from DOM (stored in dataset)
        const fromEl = this.nodeLayer!.querySelector(`[data-id="${from.id}"]`) as SVGGElement
        const toEl = this.nodeLayer!.querySelector(`[data-id="${to.id}"]`) as SVGGElement
        if (fromEl && toEl) {
          const fromCircle = fromEl.querySelector("circle")!
          const toCircle = toEl.querySelector("circle")!
          const chainEdge = edge(
            parseFloat(fromCircle.getAttribute("cx")!),
            parseFloat(fromCircle.getAttribute("cy")!),
            parseFloat(toCircle.getAttribute("cx")!),
            parseFloat(toCircle.getAttribute("cy")!),
            2.0, 0.8, true  // dashed
          )
          chainEdge.dataset.chainId = path.chain_id
          this.edgeLayer!.appendChild(chainEdge)
        }
      }
    }
  }

  private renderEmpty(): void {
    // Same pattern as ai-surface's empty state
    const empty = document.createElement("div")
    empty.className = "map-empty"
    empty.innerHTML = `<div class="big">No attack paths found</div>
      <div>No vulnerability chains were detected in this engagement.</div>`
    this.g!.parentElement!.insertBefore(empty, this.g)
  }

  private wireInteraction(): void {
    // ... same pattern as ai-surface wireMapInteraction()
    // ... + chain-edge hover highlighting
  }
}
```

### 8.3 Detail Drawer (Adapted for Attack Chains)

```typescript
// packages/opencode/src/argus/visualizer/drawer.ts

export class AttackDetailDrawer {
  private overlay: HTMLElement
  private panel: HTMLElement
  private content: HTMLElement
  
  constructor(container: HTMLElement) {
    this.overlay = document.createElement("div")
    this.overlay.className = "drawer-overlay"
    this.overlay.addEventListener("click", () => this.close())
    
    this.panel = document.createElement("aside")
    this.panel.className = "drawer-panel"
    this.panel.setAttribute("role", "dialog")
    this.panel.setAttribute("aria-modal", "true")
    
    this.content = document.createElement("div")
    this.content.className = "drawer-content"
    
    this.panel.appendChild(this.content)
    container.appendChild(this.overlay)
    container.appendChild(this.panel)
  }

  openFinding(finding: GraphNodeData, chainData?: AttackPathData): void {
    const sev = finding.data.severity
    this.content.innerHTML = `
      <div class="drawer-header">
        <span class="severity-badge" style="background:${SEV_COLORS[sev] ?? "var(--sev-none)"}">
          ${esc(sev ?? "INFO")}
        </span>
        <h2>${esc(finding.data.type)}</h2>
        <button class="drawer-close" data-action="close">${esc(/* close icon */ "")}</button>
      </div>
      <div class="drawer-body">
        <section class="detail-section">
          <h3>Endpoint</h3>
          <code>${esc(finding.data.endpoint)}</code>
        </section>
        <section class="detail-section">
          <h3>Confidence</h3>
          <div class="confidence-bar">
            <div class="confidence-fill" style="width:${(finding.confidence ?? 0.5) * 100}%"></div>
          </div>
          <span>${((finding.confidence ?? 0.5) * 100).toFixed(0)}%</span>
        </section>
        ${finding.prerequisites?.length ? `
          <section class="detail-section">
            <h3>Prerequisites</h3>
            <ul>${finding.prerequisites.map(p => `<li>${esc(p)}</li>`).join("")}</ul>
          </section>
        ` : ""}
        ${finding.downstream_impacts?.length ? `
          <section class="detail-section">
            <h3>Downstream Impacts</h3>
            <ul>${finding.downstream_impacts.map(i => `<li>${esc(i)}</li>`).join("")}</ul>
          </section>
        ` : ""}
        ${chainData ? this.renderChainSection(chainData) : ""}
      </div>`
    
    this.open()
  }

  openChain(chain: AttackPathData): void {
    this.content.innerHTML = `
      <div class="drawer-header">
        <h2>${esc(chain.chain_name ?? `Chain: ${chain.chain_id}`)}</h2>
        <div class="risk-score">Risk: ${chain.risk_score.toFixed(1)}</div>
        <button class="drawer-close" data-action="close">✕</button>
      </div>
      <div class="drawer-body">
        <section class="detail-section">
          <h3>Attack Path (${chain.nodes.length} nodes)</h3>
          <div class="chain-flow">
            ${chain.nodes.filter(n => n.type === "vulnerability").map((n, i) => `
              <div class="chain-step" data-node-id="${esc(n.id)}">
                <span class="step-num">${i + 1}</span>
                <span class="step-type">${esc(n.data.type)}</span>
                <span class="step-sev" style="color:${SEV_COLORS[n.data.severity] ?? "var(--sev-none)"}">
                  ${esc(n.data.severity)}
                </span>
                <code>${esc(n.data.endpoint)}</code>
              </div>
            `).join("")}
          </div>
        </section>
        ${chain.chain_exploit_script ? this.renderScriptSection(chain.chain_exploit_script) : ""}
      </div>`
    
    this.open()
  }

  private renderChainSection(chain: AttackPathData): string {
    return `
      <section class="detail-section chain-section">
        <h3>Attack Chain</h3>
        <div class="chain-badge" data-chain-id="${esc(chain.chain_id ?? "")}">
          ${esc(chain.chain_name ?? "Unnamed Chain")}
        </div>
        <div class="chain-risk">Risk score: ${chain.risk_score.toFixed(1)}</div>
        ${chain.chain_exploit_script ? `
          <button class="btn btn-small" data-action="show-script">View Exploit Script</button>
        ` : ""}
      </section>`
  }

  private renderScriptSection(script: any): string {
    return `
      <section class="detail-section">
        <h3>Exploit Script</h3>
        <details>
          <summary>Show script (${script.script?.length ?? 0} chars)</summary>
          <pre><code>${esc(script.script ?? "")}</code></pre>
        </details>
        ${script.steps?.length ? `
          <h4>Steps</h4>
          <ol>${script.steps.map(s => `<li>${esc(s.summary ?? s.step ?? "")}</li>`).join("")}</ol>
        ` : ""}
        ${script.impact_summary ? `
          <h4>Impact</h4>
          <p>${esc(script.impact_summary)}</p>
        ` : ""}
      </section>`
  }

  open(): void {
    this.overlay.classList.add("open")
    this.panel.classList.add("open")
    document.body.style.overflow = "hidden"
  }

  close(): void {
    this.overlay.classList.remove("open")
    this.panel.classList.remove("open")
    document.body.style.overflow = ""
  }
}
```

---

## 9. Integration Points with Existing Systems

### 9.1 MCP Server Bridge

In `mcp_server.py`, add a new tool that serves graph data:

```python
# In mcp_server.py — new tool registration
@mcp.tool()
async def get_attack_graph_snapshot(engagement_id: str) -> dict:
    """Get the attack graph snapshot for visualization.
    
    Returns the serialized attack graph with nodes, edges, paths,
    risk scores, and chain metadata for the frontend visualizer.
    """
    from attack_graph_db import AttackGraphRepository
    repo = AttackGraphRepository()
    graph = repo.load_graph(engagement_id)
    if not graph:
        return {"paths": [], "metadata": {"totalPaths": 0, "totalFindings": 0, "highestRiskScore": 0, "chainsDetected": 0}}
    
    snapshot = graph.to_snapshot_dict()
    chains = graph.find_chains()
    
    # Enrich paths with chain metadata
    for path_data in snapshot.get("paths", []):
        for chain in chains:
            prereq_type = chain["prereq_node"].data.get("type", "")
            chain_type = chain["chain_node"].data.get("type", "")
            path_types = [n.get("data", {}).get("type", "") for n in path_data.get("nodes", []) if n.get("type") == "vulnerability"]
            if prereq_type in path_types and chain_type in path_types:
                path_data["chain_id"] = chain["chain_id"]
                path_data["chain_name"] = chain["name"]
                break
    
    return {
        "paths": snapshot.get("paths", []),
        "metadata": {
            "totalPaths": len(snapshot.get("paths", [])),
            "totalFindings": len(graph.nodes),
            "highestRiskScore": max((p.get("risk_score", 0) for p in snapshot.get("paths", [])), default=0),
            "chainsDetected": len(chains),
        }
    }
```

### 9.2 Planner Integration

In `planner.ts`, the existing `replan()` method already populates `chainPlans`. Add graph data to the progress events:

```typescript
// In planner.ts replan() — emit graph data when chains are detected
if (context.chainPlans && context.chainPlans.length > 0) {
  emitProgress?.({
    type: "attack_graph_update",
    label: context.target,
    chainCount: context.chainPlans.length,
    chainPlans: context.chainPlans,
    // The visualizer listens for this event and re-renders
  })
}
```

### 9.3 Engagement Store

The existing `getEngagementDetail()` in `engagement/store.ts` already returns findings + evidence. Add attack graph data:

```typescript
// In engagement/store.ts
async getEngagementDetail(engagementId: string): Promise<EngagementDetail | null> {
  const engagement = this.getEngagement(engagementId)
  if (!engagement) return null
  
  const findings = this.getFindings(engagementId)
  const evidence = this.getEvidenceByEngagement(engagementId)
  const auditLog = this.getAuditLog(engagementId)
  const attackGraph = await this.fetchAttackGraph(engagementId)  // via MCP
  
  return { engagement, findings, evidence, auditLog, attackGraph }
}
```

---

## 10. Sequencing & Effort

```
Week 1:
  V1 (data bridge, 1d)  ──────────────────┐
                                          ▼
  V2 (SVG renderer, 2d) ←────────── Requires graph data schema
                                          │
Week 2:                                   │
  V3 (detail drawer, 1d) ←──────── Requires V2's node click events
                                          │
  V4 (TUI integration, 1d) ←─────── Requires V2 + V3
                                          │
Week 3 (optional, follow-on):             │
  V5 (ai-surface integration, 2d) ← May use V2/V3 for rendering
```

**Total for V1-V4 (core visualization): ~5 days.**
**Total including V5 (full AI surface convergence): ~7 days.**

### Dependencies

| Workstream | Depends On | Blocked By |
|-----------|-----------|------------|
| V1 (data bridge) | Existing AttackGraph + planner/types.ts | Nothing |
| V2 (SVG renderer) | V1's data schema | V1 |
| V3 (detail drawer) | V2's click events | V2 |
| V4 (TUI integration) | V2 + V3 | V2, V3 |
| V5 (ai-surface) | V1 (for graph data), existing ai-surface integration plan | ai-surface CLI + parser |

### Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Graph data too large for real-time rendering (1000+ nodes) | Low | ai-surface handles 200+ nodes well; Argus chains are typically 2-10 nodes per path |
| SVG performance degrades with many edge paths | Low | ai-surface uses pure SVG with no physics; O(n) rendering |
| MCP bridge latency for graph snapshots | Medium | Cache snapshots; re-fetch only on replan events |
| CSS variable conflicts with existing theme system | Medium | Namespace all vars under `--ag-` prefix |

---

## Appendix A: ai-surface `drawMap()` Annotated Reference

Full annotated breakdown of the ai-surface `drawMap()` function (lines 558-733 of `app.js`):

### Constants & Setup

```javascript
const W = 1000, H = 688;                 // viewBox
const cx = W / 2, cy = H / 2;
const byCat = {};                         // group findings by category
FINDINGS.forEach((f) => { (byCat[f.category] = byCat[f.category] || []).push(f); });
const cats = Object.keys(byCat);          // unique category keys
```

### Radius Calculations

```javascript
const minWH = Math.min(W, H);               // 688
const hubR = minWH * 0.205;                 // ~141px — Ring 1
const leafBase = minWH * 0.40;              // ~275px — Ring 2 start
const leafMax = minWH * 0.47;               // ~323px — Ring 2 max
const sector = (Math.PI * 2) / cats.length; // angular wedge per category
const startAngle = -Math.PI / 2;            // start from top
```

### SVG Layer Setup

```javascript
const NS = "http://www.w3.org/2000/svg";
const svg = document.createElementNS(NS, "svg");
svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
const g = document.createElementNS(NS, "g"); g.setAttribute("class", "graph");
const edgeLayer = mk(NS, "g");
const nodeLayer = mk(NS, "g");
g.appendChild(edgeLayer); g.appendChild(nodeLayer);
```

### Center Node

```javascript
// Outter disc + inner gradient disc + label below
const center = mk(NS, "g");
center.appendChild(disc(NS, cx, cy, 34, "var(--hub-fill)", "var(--line-2)", 1.5));
center.appendChild(disc(NS, cx, cy, 30, "url(#coreGrad)", "none", 0));
center.appendChild(text(NS, cx, cy + 60, rootName(), "lbl"));
```

### Hub + Leaf Generation

```javascript
cats.forEach((cat, i) => {
  const ang = startAngle + (i / cats.length) * Math.PI * 2;
  const hx = cx + Math.cos(ang) * hubR;
  const hy = cy + Math.sin(ang) * hubR;
  const leaves = byCat[cat];
  const hr = 13 + Math.min(leaves.length, 12) * 1.6;
  
  // Hub edge, disc, ring, label...
  
  leaves.forEach((f, j) => {
    const n = leaves.length;
    const arc = n <= 1 ? 0 : Math.min(sector * 0.74, 0.16 * n);
    const bands = Math.max(1, Math.ceil(n / 6));
    const bandGap = bands > 1 ? (leafMax - leafBase) / (bands - 1) : 0;
    
    const band = j % bands;
    const t = n === 1 ? 0 : (j / (n - 1)) - 0.5;
    const la = ang + t * arc;
    const lr = leafBase + band * bandGap;
    const lx2 = cx + Math.cos(la) * lr;
    const ly2 = cy + Math.sin(la) * lr;
    
    // Node disc, ring, label, title...
  });
});
```

### Quadratic Bezier Edge

```javascript
function edge(NS, x1, y1, x2, y2, sw, op) {
  const l = mk(NS, "path");
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const dx = x2 - x1, dy = y2 - y1;
  const off = 0.12;
  const qx = mx - dy * off, qy = my + dx * off;
  l.setAttribute("d", `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`);
  l.setAttribute("class", "edge");
  l.setAttribute("opacity", op);
  return l;
}
```

### Interaction Wiring

```javascript
function wireMapInteraction() {
  const g = document.querySelector("#map-wrap .graph");
  g.querySelectorAll(".node-leaf, .node-hub").forEach((node) => {
    node.addEventListener("mouseenter", () => focusCategory(g, node.dataset.cat));
    node.addEventListener("mouseleave", () => unfocus(g));
  });
  g.addEventListener("click", (e) => {
    const node = e.target.closest(".node-leaf, .node-hub");
    if (!node) return;
    if (node.classList.contains("node-leaf")) {
      openDrawer(Number(node.dataset.id));
    } else {
      state.cat = node.dataset.cat;
      setTab("findings");
    }
  });
}
```

### CSS Dim/Highlight Pattern

```css
.graph.dim .node:not(.related) { opacity: 0.15; }
.graph.dim .node.related { opacity: 1; }
.graph.dim .edge:not(.related) { opacity: 0.08; }
.graph.dim .edge.related { opacity: 0.8; }
```

---

## Appendix B: Complete API Schema for the Visualization Bridge

### MCP Tool: `get_attack_graph_snapshot`

**Input:**
```json
{
  "engagement_id": "uuid-string"
}
```

**Output:**
```json
{
  "paths": [
    {
      "risk_score": 8.5,
      "nodes": [
        {
          "id": "vuln_XSS_/api/users",
          "type": "vulnerability",
          "data": {
            "type": "XSS",
            "severity": "HIGH",
            "endpoint": "/api/users",
            "source_tool": "dalfox"
          },
          "cvss": 7.5,
          "confidence": 0.85,
          "prerequisites": ["user_interaction", "no_csp"],
          "downstream_impacts": ["session_theft", "credential_capture"]
        },
        {
          "id": "endpoint_/api/users",
          "type": "endpoint",
          "data": { "url": "/api/users" },
          "cvss": null,
          "confidence": null,
          "prerequisites": [],
          "downstream_impacts": []
        }
      ],
      "edges": [
        {
          "from_node": "vuln_XSS_/api/users",
          "to_node": "endpoint_/api/users",
          "type": "independent",
          "correlation_factor": 1.0,
          "relationship_type": "AMPLIFIES"
        }
      ],
      "chain_id": "chain_2",
      "chain_name": "XSS + CSRF → Account Takeover"
    }
  ],
  "metadata": {
    "totalPaths": 5,
    "totalFindings": 12,
    "highestRiskScore": 9.2,
    "chainsDetected": 3
  }
}
```

### UI Event: `attack_graph_update`

Emitted by the planner during `replan()` when chains are detected.

```typescript
interface AttackGraphUpdateEvent {
  type: "attack_graph_update"
  label: string              // target URL
  chainCount: number
  chainPlans: ChainPhasePlan[]
  snapshot?: AttackGraphSnapshot  // full graph data (expensive, may omit)
}
```

### CSS Variables for Theming

```css
:root {
  /* Severity palette */
  --ag-sev-critical: #dc2626;
  --ag-sev-high: #ea580c;
  --ag-sev-medium: #ca8a04;
  --ag-sev-low: #2563eb;
  --ag-sev-info: #6b7280;
  --ag-sev-none: #9ca3af;
  
  /* Hub */
  --ag-hub-fill: #1e293b;
  --ag-hub-fill-hover: #334155;
  --ag-hub-ring: #4f6dff;
  
  /* Edges */
  --ag-edge-base: #475569;
  --ag-edge-chain: #7c3aed;
  --ag-edge-causes: #dc2626;
  --ag-edge-enables: #2563eb;
  --ag-edge-amplifies: #ea580c;
  --ag-edge-mitigates: #16a34a;
  --ag-edge-depends: #6b7280;
  
  /* Drawer */
  --ag-drawer-bg: #0f172a;
  --ag-drawer-text: #e2e8f0;
  --ag-drawer-width: 420px;
  
  /* Map */
  --ag-map-bg: transparent;
  --ag-map-radius: 12px;
}

[data-theme="light"] {
  --ag-hub-fill: #f1f5f9;
  --ag-hub-fill-hover: #e2e8f0;
  --ag-drawer-bg: #ffffff;
  --ag-drawer-text: #1e293b;
  --ag-edge-base: #cbd5e1;
}
```

---

> **Next steps:** Start with Workstream V1 (data bridge) — no UI code needed, purely extending the MCP bridge + TypeScript types. Then V2 (SVG renderer) can proceed in parallel with porting ai-surface's `drawMap()` to TypeScript. V3 (drawer) and V4 (TUI integration) follow sequentially.
