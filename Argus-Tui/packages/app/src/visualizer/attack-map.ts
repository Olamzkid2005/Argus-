/**
 * Attack Graph Visualizer — SVG radial cluster map of attack chains.
 * Ported from the opencode package's visualizer.
 */

import type { AttackGraphSnapshot, AttackPathData, GraphNodeData } from "./index"
import {
  mk, disc, ringEl, edge, svgText,
  SEV_RANK, SEV_COLORS, RELATIONSHIP_COLORS, titleCase,
} from "./svg-builders"

export interface VisualizerCallbacks {
  onNodeClick?: (nodeId: string) => void
  onHubClick?: (vulnType: string) => void
  onChainClick?: (chainId: string) => void
}

export interface AttackGraphVisualizerOptions {
  width?: number
  height?: number
  showChainEdges?: boolean
  cssClass?: string
  callbacks?: VisualizerCallbacks
}

const DEFAULT_W = 1000
const DEFAULT_H = 688

export class AttackGraphVisualizer {
  private svg: SVGSVGElement | null = null
  private g: SVGGElement | null = null
  private edgeLayer: SVGGElement | null = null
  private nodeLayer: SVGGElement | null = null
  private data: AttackGraphSnapshot | null = null
  private opts: Required<AttackGraphVisualizerOptions>
  private W = DEFAULT_W
  private H = DEFAULT_H
  private callbacks: Required<VisualizerCallbacks>
  private selectableNodes: SVGElement[] = []
  private focusedIndex = -1

  constructor(options?: AttackGraphVisualizerOptions) {
    this.opts = {
      width: options?.width ?? DEFAULT_W,
      height: options?.height ?? DEFAULT_H,
      showChainEdges: options?.showChainEdges ?? true,
      cssClass: options?.cssClass ?? "attack-map",
      callbacks: options?.callbacks ?? {},
    }
    this.W = this.opts.width
    this.H = this.opts.height
    this.callbacks = {
      onNodeClick: options?.callbacks?.onNodeClick ?? (() => {}),
      onHubClick: options?.callbacks?.onHubClick ?? (() => {}),
      onChainClick: options?.callbacks?.onChainClick ?? (() => {}),
    }
  }

  render(container: HTMLElement, data: AttackGraphSnapshot): void {
    this.data = data
    container.innerHTML = ""

    this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg") as SVGSVGElement
    this.svg.setAttribute("viewBox", `0 0 ${this.W} ${this.H}`)
    this.svg.setAttribute("preserveAspectRatio", "xMidYMid meet")
    this.svg.setAttribute("class", this.opts.cssClass)

    const g = mk("g") as SVGGElement
    g.setAttribute("class", "graph")
    this.svg.appendChild(g)
    this.g = g

    this.edgeLayer = mk("g") as SVGGElement
    this.edgeLayer.setAttribute("class", "edge-layer")
    this.nodeLayer = mk("g") as SVGGElement
    this.nodeLayer.setAttribute("class", "node-layer")
    g.appendChild(this.edgeLayer)
    g.appendChild(this.nodeLayer)

    if (!data.paths || data.paths.length === 0) {
      this.renderEmpty()
    } else {
      this.drawAllPaths()
      this.wireInteraction()
    }

    container.appendChild(this.svg)
  }

  update(container: HTMLElement, data: AttackGraphSnapshot): void {
    this.render(container, data)
  }

  private renderEmpty(): void {
    const cx = this.W / 2
    const cy = this.H / 2
    const g = this.g!
    g.appendChild(disc(cx, cy, 30, "var(--ag-hub-fill)", "var(--ag-edge-base)", 1))
    const t1 = svgText(cx, cy + 50, "No attack paths found", "empty-title")
    t1.setAttribute("text-anchor", "middle")
    t1.setAttribute("font-size", "18")
    g.appendChild(t1)
    const t2 = svgText(cx, cy + 74, "No vulnerability chains were detected.", "empty-sub")
    t2.setAttribute("text-anchor", "middle")
    t2.setAttribute("font-size", "13")
    g.appendChild(t2)
  }

  private drawAllPaths(): void {
    const { paths } = this.data!
    const cx = this.W / 2, cy = this.H / 2
    const minWH = Math.min(this.W, this.H)

    const byType = new Map<string, GraphNodeData[]>()
    for (const path of paths) {
      for (const node of path.nodes) {
        if (node.type === "vulnerability") {
          const vulnType = node.data.type || "UNKNOWN"
          if (!byType.has(vulnType)) byType.set(vulnType, [])
          byType.get(vulnType)!.push(node)
        }
      }
    }

    const cats = [...byType.keys()]
    const hubR = minWH * 0.205
    const leafBase = minWH * 0.40
    const leafMax = minWH * 0.47
    const sector = (Math.PI * 2) / Math.max(cats.length, 1)
    const startAngle = -Math.PI / 2

    // Center node
    const center = mk("g") as SVGGElement
    center.setAttribute("class", "node node-center")
    center.appendChild(disc(cx, cy, 34, "var(--ag-hub-fill)", "var(--ag-edge-base)", 1.5))
    center.appendChild(disc(cx, cy, 30, "var(--ag-hub-fill)", "none", 0))
    center.appendChild(svgText(cx, cy + 48, "Attack Graph", "lbl center-label"))
    const centerCount = svgText(cx, cy + 66, `${paths.length} path${paths.length !== 1 ? "s" : ""}`, "sub-lbl")
    centerCount.setAttribute("text-anchor", "middle")
    centerCount.setAttribute("font-size", "11")
    center.appendChild(centerCount)
    const maxRisk = this.data!.metadata.highestRiskScore
    const riskBadge = svgText(cx, cy - 44, `Risk ${maxRisk.toFixed(1)}`, "risk-badge")
    riskBadge.setAttribute("text-anchor", "middle")
    riskBadge.setAttribute("font-size", "11")
    riskBadge.setAttribute("font-weight", "bold")
    center.appendChild(riskBadge)
    this.nodeLayer!.appendChild(center)

    // Hubs + Leaves
    cats.forEach((type, i) => {
      const ang = startAngle + (i / cats.length) * Math.PI * 2
      const hx = cx + Math.cos(ang) * hubR
      const hy = cy + Math.sin(ang) * hubR
      const nodes = byType.get(type)!

      const hubEdge = edge(cx, cy, hx, hy, 1.7, 0.7)
      hubEdge.dataset.type = type
      this.edgeLayer!.appendChild(hubEdge)

      const hr = 13 + Math.min(nodes.length, 12) * 1.6
      const hub = mk("g") as SVGGElement
      hub.setAttribute("class", "node node-hub")
      hub.dataset.type = type
      hub.appendChild(ringEl(hx, hy, hr + 6, "var(--ag-hub-ring)", 1.2, 0.35))
      hub.appendChild(disc(hx, hy, hr, "var(--ag-hub-fill)", "var(--ag-edge-base)", 1.4))
      const count = svgText(hx, hy + 4, String(nodes.length), "count")
      count.setAttribute("text-anchor", "middle")
      count.setAttribute("font-size", "12")
      count.setAttribute("font-weight", "bold")
      hub.appendChild(count)

      const labelR = hubR + hr + 14
      const lx = cx + Math.cos(ang) * labelR
      const ly = cy + Math.sin(ang) * labelR
      const hl = svgText(lx, ly + 4, titleCase(type), "lbl hub-label")
      hl.setAttribute("text-anchor",
        Math.cos(ang) < -0.25 ? "end" : Math.cos(ang) > 0.25 ? "start" : "middle")
      hub.appendChild(hl)
      this.nodeLayer!.appendChild(hub)

      const n = nodes.length
      const arc = n <= 1 ? 0 : Math.min(sector * 0.74, 0.16 * n)
      const bands = Math.max(1, Math.ceil(n / 6))
      const bandGap = bands > 1 ? (leafMax - leafBase) / (bands - 1) : 0

      const chainedNodeIds = new Set<string>()
      for (const path of paths) {
        if (path.chain_id) {
          for (const node of path.nodes) chainedNodeIds.add(node.id)
        }
      }

      nodes.forEach((node, j) => {
        const band = j % bands
        const t = n === 1 ? 0 : (j / (n - 1)) - 0.5
        const la = ang + t * arc
        const lr = leafBase + band * bandGap
        const lx2 = cx + Math.cos(la) * lr
        const ly2 = cy + Math.sin(la) * lr

        const leafEdge = edge(hx, hy, lx2, ly2, 1.2, 0.5)
        leafEdge.dataset.type = type
        this.edgeLayer!.appendChild(leafEdge)

        const sev = node.data.severity
        const sevRank = SEV_RANK[sev ?? ""] ?? 0
        const r = sev ? 9 + sevRank * 1.7 : 7.5
        const fill = sev ? (SEV_COLORS[sev] ?? "var(--ag-sev-info)") : "var(--ag-sev-none)"
        const stroke = sev ? "transparent" : "var(--ag-edge-base)"
        const isChained = chainedNodeIds.has(node.id)

        const leaf = mk("g") as SVGGElement
        leaf.setAttribute("class", "node node-leaf")
        leaf.dataset.id = node.id
        leaf.dataset.type = type

        leaf.appendChild(disc(lx2, ly2, Math.max(r + 9, 17), "transparent", "none", 0))
        if (isChained) {
          leaf.appendChild(ringEl(lx2, ly2, r + 6, "var(--ag-edge-chain)", 2, 0.9))
        }
        leaf.appendChild(disc(lx2, ly2, r, fill, stroke, sev ? 0 : 1.4))

        if (n <= 8) {
          const showLeft = Math.cos(la) < 0
          const label = svgText(
            lx2 + (showLeft ? -(r + 7) : (r + 7)), ly2 + 4,
            node.data.endpoint ? shortLabel(node.data.endpoint, 18) : titleCase(node.data.type || ""),
            "lbl leaf-label",
          )
          label.setAttribute("text-anchor", showLeft ? "end" : "start")
          label.setAttribute("font-size", "10")
          leaf.appendChild(label)
        }

        const title = mk("title") as SVGTitleElement
        title.textContent = `${node.data.type ?? "Unknown"} · ${sev ?? "no severity"} · ${node.data.endpoint ?? ""}`
        leaf.appendChild(title)
        this.nodeLayer!.appendChild(leaf)
      })
    })

    // Chain edges
    if (this.opts.showChainEdges) {
      for (const path of paths) {
        if (!path.chain_id) continue
        const vulnNodes = path.nodes.filter(n => n.type === "vulnerability")
        for (let i = 0; i < vulnNodes.length - 1; i++) {
          const from = vulnNodes[i]
          const to = vulnNodes[i + 1]
          const fromEl = this.findNodeElement(from.id)
          const toEl = this.findNodeElement(to.id)
          if (fromEl && toEl) {
            const fromCx = parseFloat(fromEl.getAttribute("cx") ?? "0")
            const fromCy = parseFloat(fromEl.getAttribute("cy") ?? "0")
            const toCx = parseFloat(toEl.getAttribute("cx") ?? "0")
            const toCy = parseFloat(toEl.getAttribute("cy") ?? "0")
            const edgeData = path.edges.find(e => e.from_node === from.id && e.to_node === to.id)
            const relColor = edgeData
              ? (RELATIONSHIP_COLORS[edgeData.relationship_type] ?? "var(--ag-edge-chain)")
              : "var(--ag-edge-chain)"
            const chainEdge = edge(fromCx, fromCy, toCx, toCy, 2.0, 0.8, true)
            chainEdge.dataset.chainId = path.chain_id
            chainEdge.setAttribute("stroke", relColor)
            this.edgeLayer!.appendChild(chainEdge)
          }
        }
      }
    }
  }

  private findNodeElement(nodeId: string): SVGCircleElement | null {
    const g = this.nodeLayer!.querySelector(`[data-id="${CSS.escape(nodeId)}"]`) as SVGGElement | null
    if (!g) return null
    return g.querySelector('circle:not([fill="transparent"])')
  }

  private wireInteraction(): void {
    const g = this.g!
    const { onNodeClick, onHubClick, onChainClick } = this.callbacks

    // Build a flat list of selectable elements for keyboard navigation
    this.selectableNodes = [
      ...g.querySelectorAll<SVGElement>(".node-leaf, .node-hub, .edge-chain"),
    ]

    g.querySelectorAll(".node-leaf, .node-hub").forEach((node) => {
      node.addEventListener("mouseenter", () => {
        this.focusedIndex = -1
        this.focusCategory(g, (node as SVGElement).dataset.type ?? "")
      })
      node.addEventListener("mouseleave", () => this.unfocus(g))
    })

    g.addEventListener("click", (e) => {
      const target = e.target as SVGElement
      const node = target.closest?.(".node-leaf, .node-hub, .edge-chain") as SVGElement | null
      if (!node) {
        this.unfocus(g)
        return
      }
      this.focusedIndex = this.selectableNodes.indexOf(node)
      if (node.classList.contains("node-leaf")) {
        onNodeClick(node.dataset.id ?? "")
      } else if (node.classList.contains("node-hub")) {
        onHubClick(node.dataset.type ?? "")
      } else if (node.classList.contains("edge-chain") && node.dataset.chainId) {
        onChainClick(node.dataset.chainId)
      }
    })

    // Keyboard navigation — attached to the SVG (the focused element via tabindex) so keyboard events reach it
    this.svg!.addEventListener("keydown", (e) => {
      if (this.selectableNodes.length === 0) return

      switch (e.key) {
        case "Tab": {
          e.preventDefault()
          const dir = e.shiftKey ? -1 : 1
          this.focusedIndex = (this.focusedIndex + dir + this.selectableNodes.length) % this.selectableNodes.length
          this.focusNodeAtIndex(this.focusedIndex)
          break
        }
        case "ArrowRight":
        case "ArrowDown": {
          e.preventDefault()
          this.focusedIndex = (this.focusedIndex + 1) % this.selectableNodes.length
          this.focusNodeAtIndex(this.focusedIndex)
          break
        }
        case "ArrowLeft":
        case "ArrowUp": {
          e.preventDefault()
          this.focusedIndex = (this.focusedIndex - 1 + this.selectableNodes.length) % this.selectableNodes.length
          this.focusNodeAtIndex(this.focusedIndex)
          break
        }
        case "Enter":
        case " ": {
          e.preventDefault()
          const el = this.selectableNodes[this.focusedIndex]
          if (!el) break
          if (el.classList.contains("node-leaf")) {
            onNodeClick(el.dataset.id ?? "")
          } else if (el.classList.contains("node-hub")) {
            onHubClick(el.dataset.type ?? "")
          } else if (el.classList.contains("edge-chain") && el.dataset.chainId) {
            onChainClick(el.dataset.chainId)
          }
          break
        }
        case "Escape": {
          e.preventDefault()
          this.unfocus(g)
          this.focusedIndex = -1
          break
        }
      }
    })

    // Make the SVG focusable for keyboard events
    this.svg!.setAttribute("tabindex", "0")
    this.svg!.setAttribute("role", "application")
    this.svg!.setAttribute("aria-label", "Attack chain graph. Use Tab and arrow keys to navigate, Enter to select.")
  }

  private focusNodeAtIndex(index: number): void {
    const g = this.g!
    const el = this.selectableNodes[index]
    if (!el) return

    const cat = el.dataset.type ?? el.dataset.chainId ?? ""
    g.classList.add("dim")
    g.querySelectorAll(".related").forEach((n) => n.classList.remove("related"))

    if (el.classList.contains("edge-chain")) {
      g.querySelectorAll(".node, .edge").forEach((n) => {
        if ((n as SVGElement).dataset.chainId === el.dataset.chainId) {
          n.classList.add("related")
        }
      })
    } else {
      g.querySelectorAll(".node, .edge").forEach((n) => {
        if (n.classList.contains("node-center") || (n as SVGElement).dataset.type === cat) {
          n.classList.add("related")
        }
      })
    }

    g.querySelectorAll(".keyboard-focused").forEach((n) => n.classList.remove("keyboard-focused"))
    el.classList.add("keyboard-focused")
    el.scrollIntoView?.({ block: "nearest", behavior: "smooth" })
  }

  private focusCategory(g: SVGElement, cat: string): void {
    if (!cat) return
    g.classList.add("dim")
    g.querySelectorAll(".node, .edge").forEach((el) => {
      if (el.classList.contains("node-center") || (el as SVGElement).dataset.type === cat) {
        el.classList.add("related")
      }
    })
    g.querySelectorAll(".edge-chain").forEach((el) => {
      if ((el as SVGElement).dataset.chainId) el.classList.add("related")
    })
  }

  private unfocus(g: SVGElement): void {
    g.classList.remove("dim")
    g.querySelectorAll(".related").forEach((el) => el.classList.remove("related"))
    g.querySelectorAll(".keyboard-focused").forEach((el) => el.classList.remove("keyboard-focused"))
  }
}

function shortLabel(s: string, maxLen: number): string {
  if (s.length <= maxLen) return s
  return s.slice(0, maxLen - 3) + "..."
}
