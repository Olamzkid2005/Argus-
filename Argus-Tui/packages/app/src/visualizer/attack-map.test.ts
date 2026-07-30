/**
 * Tests for AttackGraphVisualizer — SVG radial cluster map of attack chains.
 *
 * Focuses on the keyboard navigation feature added to wireInteraction():
 *   - Tab / Shift+Tab cycling
 *   - Arrow key navigation
 *   - Enter / Space activation
 *   - Escape unfocus
 *   - Accessibility attributes
 *   - CSS class management (dim, related, keyboard-focused)
 *   - Click tracking of focusedIndex
 *   - Mouse hover reset of focusedIndex
 */

import { beforeEach, describe, expect, test } from "bun:test"
import { AttackGraphVisualizer, type VisualizerCallbacks } from "./attack-map"
import type { AttackGraphSnapshot, AttackPathData } from "./index"

// ──────────────────────────────────────────────
//  Fixtures
// ──────────────────────────────────────────────

const SAMPLE_NODES = {
  xss_1: {
    id: "vuln_001",
    type: "vulnerability" as const,
    data: { type: "xss", severity: "HIGH", endpoint: "/login" },
    cvss: 7.5,
    confidence: 0.95,
    prerequisites: [],
    downstream_impacts: [],
  },
  xss_2: {
    id: "vuln_002",
    type: "vulnerability" as const,
    data: { type: "xss", severity: "MEDIUM", endpoint: "/search" },
    cvss: 5.0,
    confidence: 0.85,
    prerequisites: [],
    downstream_impacts: [],
  },
  idor_1: {
    id: "vuln_003",
    type: "vulnerability" as const,
    data: { type: "idor", severity: "CRITICAL", endpoint: "/api/users/{id}" },
    cvss: 9.0,
    confidence: 0.98,
    prerequisites: [],
    downstream_impacts: [],
  },
}

const SAMPLE_PATHS: AttackPathData[] = [
  {
    risk_score: 8.5,
    chain_id: "chain_1",
    chain_name: "XSS → Data Exfil",
    nodes: [SAMPLE_NODES.xss_1, SAMPLE_NODES.xss_2],
    edges: [
      {
        from_node: "vuln_001",
        to_node: "vuln_002",
        type: "chain",
        correlation_factor: 0.85,
        relationship_type: "enables",
      },
    ],
  },
  {
    risk_score: 9.2,
    chain_id: "chain_2",
    chain_name: "IDOR → PrivEsc",
    nodes: [SAMPLE_NODES.idor_1],
    edges: [],
  },
]

const SNAPSHOT: AttackGraphSnapshot = {
  paths: SAMPLE_PATHS,
  metadata: {
    totalPaths: 2,
    totalFindings: 3,
    highestRiskScore: 9.2,
    chainsDetected: 2,
  },
}

const EMPTY_SNAPSHOT: AttackGraphSnapshot = {
  paths: [],
  metadata: {
    totalPaths: 0,
    totalFindings: 0,
    highestRiskScore: 0,
    chainsDetected: 0,
  },
}

// ──────────────────────────────────────────────
//  Helpers
// ──────────────────────────────────────────────

function createContainer(): HTMLElement {
  const el = document.createElement("div")
  el.setAttribute("data-testid", "attack-map-container")
  return el
}

function renderVisualizer(
  snapshot: AttackGraphSnapshot = SNAPSHOT,
  callbacks?: VisualizerCallbacks,
): { container: HTMLElement; svg: SVGSVGElement } {
  const container = createContainer()
  const viz = new AttackGraphVisualizer({ width: 800, height: 600, callbacks })
  viz.render(container, snapshot)
  const svg = container.querySelector("svg.attack-map")! as SVGSVGElement
  return { container, svg }
}

function triggerKeydown(
  svg: SVGSVGElement,
  key: string,
  options?: { shiftKey?: boolean },
): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    shiftKey: options?.shiftKey ?? false,
  } satisfies KeyboardEventInit)
  svg.dispatchEvent(event)
  return event
}

/** Returns the index of the currently focused selectable node (-1 if none). */
function getFocusedIndex(svg: SVGSVGElement): number {
  const focused = svg.querySelector(".keyboard-focused")
  if (!focused) return -1
  const all = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
  return Array.from(all).indexOf(focused as SVGElement)
}

// ──────────────────────────────────────────────
//  Tests
// ──────────────────────────────────────────────

describe("AttackGraphVisualizer keyboard navigation", () => {
  let svg: SVGSVGElement

  beforeEach(() => {
    svg = renderVisualizer().svg
  })

  // ── Rendering ──

  test("renders SVG element with attack-map class", () => {
    expect(svg).toBeTruthy()
    expect(svg.getAttribute("class")).toBe("attack-map")
  })

  test("renders empty state when no paths provided", () => {
    const { svg: emptySvg } = renderVisualizer(EMPTY_SNAPSHOT)
    expect(emptySvg.querySelector(".empty-title")).toBeTruthy()
    expect(emptySvg.querySelector(".empty-sub")).toBeTruthy()
  })

  // ── Accessibility Attributes ──

  test("sets tabindex, role and aria-label on SVG for keyboard focus", () => {
    expect(svg.getAttribute("tabindex")).toBe("0")
    expect(svg.getAttribute("role")).toBe("application")
    expect(svg.getAttribute("aria-label")).toBe(
      "Attack chain graph. Use Tab and arrow keys to navigate, Enter to select.",
    )
  })

  // ── Graph structure (selectable nodes) ──

  test("creates node-leaf, node-hub and edge-chain elements", () => {
    const leaves = svg.querySelectorAll(".node-leaf")
    const hubs = svg.querySelectorAll(".node-hub")
    const chainEdges = svg.querySelectorAll(".edge-chain")

    expect(leaves.length).toBe(3) // 3 vuln nodes
    expect(hubs.length).toBe(2) // 2 vuln types (xss, idor)
    expect(chainEdges.length).toBe(1) // chain_1 has 2 nodes → 1 edge
  })

  // ── Tab key: cycle forward ──

  test("Tab key increments the focus index and shows keyboard-focused class", () => {
    expect(getFocusedIndex(svg)).toBe(-1)

    triggerKeydown(svg, "Tab")
    const idx1 = getFocusedIndex(svg)
    expect(idx1).toBeGreaterThanOrEqual(0)

    triggerKeydown(svg, "Tab")
    const idx2 = getFocusedIndex(svg)
    expect(idx2).toBe(idx1 + 1)
  })

  test("Tab key wraps around to the first node after the last", () => {
    const allSelectable = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
    const total = allSelectable.length

    // Tab to the last element
    for (let i = 0; i < total; i++) {
      triggerKeydown(svg, "Tab")
    }
    expect(getFocusedIndex(svg)).toBe(total - 1)

    // One more Tab wraps to first
    triggerKeydown(svg, "Tab")
    expect(getFocusedIndex(svg)).toBe(0)
  })

  test("Shift+Tab decrements the focus index (wrapping)", () => {
    triggerKeydown(svg, "Tab") // focusedIndex = 0
    expect(getFocusedIndex(svg)).toBe(0)

    // Shift+Tab wraps to the last
    triggerKeydown(svg, "Tab", { shiftKey: true })
    const allSelectable = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
    expect(getFocusedIndex(svg)).toBe(allSelectable.length - 1)
  })

  // ── Arrow keys ──

  test("ArrowRight moves to next selectable node", () => {
    triggerKeydown(svg, "Tab")
    const before = getFocusedIndex(svg)

    triggerKeydown(svg, "ArrowRight")
    expect(getFocusedIndex(svg)).toBe(before + 1)
  })

  test("ArrowDown also moves forward (same as ArrowRight)", () => {
    triggerKeydown(svg, "Tab")
    const before = getFocusedIndex(svg)

    triggerKeydown(svg, "ArrowDown")
    expect(getFocusedIndex(svg)).toBe(before + 1)
  })

  test("ArrowLeft moves to previous selectable node", () => {
    triggerKeydown(svg, "Tab")
    triggerKeydown(svg, "ArrowRight")
    const before = getFocusedIndex(svg)

    triggerKeydown(svg, "ArrowLeft")
    expect(getFocusedIndex(svg)).toBe(before - 1)
  })

  test("ArrowUp also moves backward (same as ArrowLeft)", () => {
    triggerKeydown(svg, "Tab")
    triggerKeydown(svg, "ArrowDown")
    const before = getFocusedIndex(svg)

    triggerKeydown(svg, "ArrowUp")
    expect(getFocusedIndex(svg)).toBe(before - 1)
  })

  test("Arrow keys wrap around at boundaries", () => {
    triggerKeydown(svg, "Tab") // focusedIndex = 0

    // ArrowLeft wraps to last
    const selectable = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
    triggerKeydown(svg, "ArrowLeft")
    expect(getFocusedIndex(svg)).toBe(selectable.length - 1)
  })

  // ── Enter / Space callbacks ──

  test("Enter triggers callback on the currently focused selectable node", () => {
    let captureCount = 0
    let capturedId = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onNodeClick: (id) => { captureCount++; capturedId = id },
    })

    // Click on a leaf first to set focusedIndex to a known element
    const leaf = cbSvg.querySelector(".node-leaf") as SVGElement
    leaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(captureCount).toBe(1) // click fires onNodeClick

    triggerKeydown(cbSvg, "Enter")
    expect(captureCount).toBe(2) // Enter also fires onNodeClick
    expect(capturedId).toBe("vuln_001")
  })

  test("Space triggers callback on the currently focused selectable node", () => {
    let captureCount = 0
    let capturedId = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onNodeClick: (id) => { captureCount++; capturedId = id },
    })

    // Click on a leaf first to set focusedIndex
    const leaf = cbSvg.querySelector(".node-leaf") as SVGElement
    leaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(captureCount).toBe(1)

    triggerKeydown(cbSvg, " ")
    expect(captureCount).toBe(2)
    expect(capturedId).toBe("vuln_001")
  })

  test("Enter triggers onHubClick when a hub is focused", () => {
    let hubTriggered = false
    let capturedType = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onHubClick: (type) => { hubTriggered = true; capturedType = type },
    })

    // Click on a hub to set focusedIndex
    const hub = cbSvg.querySelector(".node-hub") as SVGElement
    hub.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(hubTriggered).toBe(true)
    expect(capturedType).toBe("xss")

    // Reset tracker
    hubTriggered = false
    triggerKeydown(cbSvg, "Enter")
    expect(hubTriggered).toBe(true)
  })

  test("Enter triggers onChainClick when an edge-chain is focused", () => {
    let chainTriggered = false
    let capturedChainId = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onChainClick: (id) => { chainTriggered = true; capturedChainId = id },
    })

    const edge = cbSvg.querySelector(".edge-chain") as SVGElement
    edge.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(chainTriggered).toBe(true)
    expect(capturedChainId).toBe("chain_1")

    chainTriggered = false
    triggerKeydown(cbSvg, "Enter")
    expect(chainTriggered).toBe(true)
  })

  // ── Escape ──

  test("Escape clears keyboard focus and dim state", () => {
    triggerKeydown(svg, "Tab") // focus something
    expect(getFocusedIndex(svg)).toBeGreaterThanOrEqual(0)

    triggerKeydown(svg, "Escape")
    expect(getFocusedIndex(svg)).toBe(-1)
    expect(svg.querySelector(".graph")!.classList.contains("dim")).toBe(false)
  })

  // ── focusNodeAtIndex class management ──

  test("focusNodeAtIndex adds and removes keyboard-focused class", () => {
    triggerKeydown(svg, "Tab")
    const idx1 = getFocusedIndex(svg)

    triggerKeydown(svg, "Tab")
    const idx2 = getFocusedIndex(svg)

    expect(idx1).not.toBe(idx2)
    // The previously focused element should no longer have the class
    const all = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
    expect(all[idx1].classList.contains("keyboard-focused")).toBe(false)
    expect(all[idx2].classList.contains("keyboard-focused")).toBe(true)
  })

  test("focusNodeAtIndex adds dim class to the graph and related class to matching nodes", () => {
    const graph = svg.querySelector(".graph")!
    expect(graph.classList.contains("dim")).toBe(false)

    // Click on a leaf first to set focusedIndex, then Tab to trigger focusNodeAtIndex
    const leaf = svg.querySelector(".node-leaf") as SVGElement
    leaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    triggerKeydown(svg, "Tab") // triggers focusNodeAtIndex on the leaf

    expect(graph.classList.contains("dim")).toBe(true)

    // Center node should always be related when focusing a leaf or hub
    const center = svg.querySelector(".node-center")
    expect(center?.classList.contains("related")).toBe(true)
  })

  // ── Click updates focusedIndex ──

  test("clicking a node updates focusedIndex so subsequent Tab advances from that position", () => {
    const leaves = svg.querySelectorAll(".node-leaf")
    const secondLeaf = leaves[1] as SVGElement

    // Click sets focusedIndex (click handler doesn't add keyboard-focused class)
    secondLeaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))

    // Tab from this position should advance one step beyond the clicked node
    triggerKeydown(svg, "Tab")
    expect(secondLeaf.classList.contains("keyboard-focused")).toBe(false) // no longer at index 1
    const idx = getFocusedIndex(svg)
    const all = svg.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain")
    expect(idx).toBe(Array.from(all).indexOf(secondLeaf) + 1)
  })

  test("clicking the background unfocuses all", () => {
    triggerKeydown(svg, "Tab") // focus something
    expect(svg.querySelector(".keyboard-focused")).toBeTruthy()

    // Click on the graph area (not on a node) — listener is on g
    const graph = svg.querySelector(".graph")!
    graph.dispatchEvent(new MouseEvent("click", { bubbles: true }))

    expect(svg.querySelector(".keyboard-focused")).toBeNull()
    expect(graph.classList.contains("dim")).toBe(false)
  })

  test("click triggers onNodeClick callback", () => {
    let clickedId = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onNodeClick: (id) => { clickedId = id },
    })

    const firstLeaf = cbSvg.querySelector(".node-leaf") as SVGElement
    firstLeaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(clickedId).toBe("vuln_001")
  })

  test("click triggers onHubClick callback", () => {
    let clickedType = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onHubClick: (type) => { clickedType = type },
    })

    const firstHub = cbSvg.querySelector(".node-hub") as SVGElement
    firstHub.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(clickedType).toBe("xss")
  })

  test("click triggers onChainClick callback for edge-chain", () => {
    let clickedChainId = ""
    const { svg: cbSvg } = renderVisualizer(SNAPSHOT, {
      onChainClick: (id) => { clickedChainId = id },
    })

    const edgeChain = cbSvg.querySelector(".edge-chain") as SVGElement
    edgeChain.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(clickedChainId).toBe("chain_1")
  })

  // ── Mouse hover resets focusedIndex ──

  test("mouseenter triggers focusCategory (dim + related)", () => {
    const hub = svg.querySelector(".node-hub") as SVGElement
    hub.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }))

    const graph = svg.querySelector(".graph")!
    expect(graph.classList.contains("dim")).toBe(true)

    // Nodes matching the hub's type should have "related"
    const hubType = hub.dataset.type
    const matchingLeaves = svg.querySelectorAll<SVGElement>(`.node-leaf[data-type="${hubType}"]`)
    matchingLeaves.forEach((leaf) => {
      expect(leaf.classList.contains("related")).toBe(true)
    })
  })

  test("mouseleave unfocuses all", () => {
    const hub = svg.querySelector(".node-hub") as SVGElement
    hub.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }))
    expect(svg.querySelector(".graph")!.classList.contains("dim")).toBe(true)

    hub.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }))
    expect(svg.querySelector(".graph")!.classList.contains("dim")).toBe(false)
    expect(svg.querySelector(".related")).toBeNull()
  })

  // ── Edge case: no selectable nodes ──

  test("keyboard events are no-op when there are no selectable nodes", () => {
    const { svg: emptySvg } = renderVisualizer(EMPTY_SNAPSHOT)

    // Should not throw — the empty state doesn't wire interaction
    triggerKeydown(emptySvg, "Tab")
    triggerKeydown(emptySvg, "ArrowRight")
    triggerKeydown(emptySvg, "Enter")
    triggerKeydown(emptySvg, "Escape")
  })

  // ── update re-renders ──

  test("update re-renders with new data", () => {
    const container = createContainer()
    const viz = new AttackGraphVisualizer()
    viz.render(container, SNAPSHOT)

    viz.update(container, EMPTY_SNAPSHOT)
    const updatedSvg = container.querySelector("svg.attack-map")!
    expect(updatedSvg.querySelector(".empty-title")).toBeTruthy()
    expect(updatedSvg.querySelector(".empty-sub")).toBeTruthy()
  })

  // ── VisualizerOptions callbacks default to no-ops ──

  test("default callbacks do not throw when triggered", () => {
    const container = createContainer()
    const viz = new AttackGraphVisualizer()
    viz.render(container, SNAPSHOT)
    const defaultSvg = container.querySelector("svg.attack-map")! as SVGSVGElement

    const firstLeaf = defaultSvg.querySelector(".node-leaf") as SVGElement
    firstLeaf.dispatchEvent(new MouseEvent("click", { bubbles: true }))

    triggerKeydown(defaultSvg, "Tab")
    triggerKeydown(defaultSvg, "Enter")
    triggerKeydown(defaultSvg, "Escape")

    // Should not throw — default callbacks are no-ops
  })

  // ── Focus behavior for chain edges ──

  test("focusing an edge-chain highlights all nodes in that chain", () => {
    const edgeChain = svg.querySelector(".edge-chain") as SVGElement

    // First Tab from initial state (focusedIndex = -1) moves to index 0
    // The edge-chain is first in DOM order (appended to edgeLayer before nodeLayer)
    triggerKeydown(svg, "Tab")

    expect(edgeChain.classList.contains("keyboard-focused")).toBe(true)
    const graph = svg.querySelector(".graph")!
    expect(graph.classList.contains("dim")).toBe(true)
  })
})


