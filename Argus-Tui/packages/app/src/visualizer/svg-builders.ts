/**
 * SVG Builder Utilities — ported from the opencode package's visualizer.
 * Pure, zero-dependency SVG element creation helpers.
 */

const NS = "http://www.w3.org/2000/svg"

export function mk(tag: string): SVGElement {
  return document.createElementNS(NS, tag)
}

export function disc(
  x: number, y: number, r: number,
  fill: string, stroke: string, sw: number, cls?: string,
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
  stroke: string, sw: number, op: number, cls?: string,
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
  sw: number, op: number, dashed = false,
): SVGPathElement {
  const l = mk("path") as SVGPathElement
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dx = x2 - x1
  const dy = y2 - y1
  const off = 0.12
  const qx = mx - dy * off
  const qy = my + dx * off
  l.setAttribute("d",
    `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`)
  l.setAttribute("class", `edge${dashed ? " edge-chain" : ""}`)
  l.setAttribute("opacity", String(op))
  if (dashed) l.setAttribute("stroke-dasharray", "6,4")
  return l
}

export function svgText(x: number, y: number, str: string, cls: string): SVGTextElement {
  const t = mk("text") as SVGTextElement
  t.setAttribute("x", String(x))
  t.setAttribute("y", String(y))
  t.setAttribute("class", cls)
  t.textContent = str
  return t
}

export const SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const
export type SeverityLabel = (typeof SEV_ORDER)[number]

export const SEV_RANK: Record<string, number> = {
  CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1,
}

export const SEV_COLORS: Record<string, string> = {
  CRITICAL: "#dc2626",
  HIGH: "#ea580c",
  MEDIUM: "#ca8a04",
  LOW: "#2563eb",
  INFO: "#6b7280",
}

export const RELATIONSHIP_COLORS: Record<string, string> = {
  causes: "#dc2626",
  amplifies: "#ea580c",
  enables: "#2563eb",
  depends_on: "#6b7280",
  mitigates: "#16a34a",
  independent: "#9ca3af",
}

export function titleCase(s: string): string {
  return String(s || "").replace(/[-_]/g, " ").replace(/\b\w/g, (m) => m.toUpperCase())
}

export function esc(str: string): string {
  const div = document.createElement("div")
  div.appendChild(document.createTextNode(str))
  return div.innerHTML
}
