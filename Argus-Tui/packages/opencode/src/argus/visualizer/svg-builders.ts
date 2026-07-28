/**
 * SVG Builder Utilities — ported from ai-surface's `app.js` (~160 lines).
 *
 * Pure, zero-dependency SVG element creation helpers for the AttackGraphVisualizer.
 * Each function creates an SVG element via `document.createElementNS()` and returns
 * it pre-configured with the given attributes.
 */

const NS = "http://www.w3.org/2000/svg"

/** Create an SVG element with the given tag name. */
export function mk(tag: string): SVGElement {
  return document.createElementNS(NS, tag)
}

/**
 * Create a `<circle>` element (disc).
 * Modeled after ai-surface's `disc()` helper.
 */
export function disc(
  x: number,
  y: number,
  r: number,
  fill: string,
  stroke: string,
  sw: number,
  cls?: string,
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

/**
 * Create a `<circle>` element with transparent fill (ring/glow).
 * Modeled after ai-surface's `ringEl()` helper.
 */
export function ringEl(
  x: number,
  y: number,
  r: number,
  stroke: string,
  sw: number,
  op: number,
  cls?: string,
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

/**
 * Create a quadratic bezier `<path>` edge between two points.
 * Uses the same gentle-curve formula as ai-surface (line ~602 of app.js):
 *   qx = mx - dy * 0.12,  qy = my + dx * 0.12
 *
 * @param dashed - If true, applies `stroke-dasharray="6,4"` for chain-path edges.
 */
export function edge(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  sw: number,
  op: number,
  dashed = false,
): SVGPathElement {
  const l = mk("path") as SVGPathElement
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dx = x2 - x1
  const dy = y2 - y1
  const off = 0.12
  const qx = mx - dy * off
  const qy = my + dx * off
  l.setAttribute(
    "d",
    `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`,
  )
  l.setAttribute("class", `edge${dashed ? " edge-chain" : ""}`)
  l.setAttribute("opacity", String(op))
  if (dashed) l.setAttribute("stroke-dasharray", "6,4")
  return l
}

/**
 * Create a `<text>` element.
 * Modeled after ai-surface's `text()` helper.
 */
export function svgText(x: number, y: number, str: string, cls: string): SVGTextElement {
  const t = mk("text") as SVGTextElement
  t.setAttribute("x", String(x))
  t.setAttribute("y", String(y))
  t.setAttribute("class", cls)
  t.textContent = str
  return t
}

/**
 * Create an inline SVG icon from an icon key.
 *
 * ICONS entries are full SVG element strings (e.g. `<circle .../><path .../>`),
 * so we inject them via `innerHTML` on the root `<svg>` element. This matches
 * how ai-surface's original JS builds icons (inline HTML strings in template
 * literals).
 */
export function svgIcon(name: string, cls = ""): SVGElement {
  const svg = mk("svg") as SVGSVGElement
  svg.setAttribute("viewBox", "0 0 24 24")
  svg.setAttribute("fill", "none")
  svg.setAttribute("class", cls)
  svg.setAttribute("aria-hidden", "true")
  svg.innerHTML = ICONS[name] || ICONS.node
  return svg
}

/**
 * Severity color palette for Argus findings.
 * Maps Severity enum values to hex colors for node fills and badges.
 */
export const SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const
export type SeverityLabel = (typeof SEV_ORDER)[number]

export const SEV_RANK: Record<string, number> = {
  CRITICAL: 5,
  HIGH: 4,
  MEDIUM: 3,
  LOW: 2,
  INFO: 1,
}

export const SEV_COLORS: Record<string, string> = {
  CRITICAL: "#dc2626",
  HIGH: "#ea580c",
  MEDIUM: "#ca8a04",
  LOW: "#2563eb",
  INFO: "#6b7280",
}

/**
 * Relationship type edge colors.
 * Maps Argus's RelationshipType enum to colors for chain-path edges.
 */
export const RELATIONSHIP_COLORS: Record<string, string> = {
  causes: "#dc2626",
  amplifies: "#ea580c",
  enables: "#2563eb",
  depends_on: "#6b7280",
  mitigates: "#16a34a",
  independent: "#9ca3af",
}

/**
 * Inline SVG icon path data (ai-surface pattern).
 * Each icon is a full SVG element string (elements inside a 24x24 viewBox).
 * New icons added: chain (attack chain), bug (vulnerability), target (engagement).
 */
export const ICONS: Record<string, string> = {
  // Original ai-surface icons
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
  node: '<circle cx="12" cy="12" r="6"/>',
  vector: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.66 3.13 3 7 3s7-1.34 7-3V6" fill="none"/><path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3" fill="none"/>',
  file: '<path d="M5 3h8l6 6v12H5V3z" fill="none"/><path d="M13 3v6h6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  server: '<rect x="4" y="4" width="16" height="16" rx="2" fill="none"/><path d="M4 10h16M4 6h16M8 7h.01M8 11h.01M12 7h.01M12 11h.01"/>',
  key: '<circle cx="9" cy="12" r="5" fill="none"/><path d="M13 12h8v3h-2v2h-2v2h-3v-4l-1.5-1.5"/>',
  warn: '<circle cx="12" cy="12" r="10" fill="none"/><path d="M12 8v4M12 16v0"/>',
  info: '<circle cx="12" cy="12" r="10" fill="none"/><path d="M12 12v4M12 8v0"/>',
  search: '<circle cx="11" cy="11" r="7" fill="none"/><path d="M16 16l4 4"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  lock: '<rect x="8" y="11" width="8" height="7" rx="1" fill="none"/><path d="M9 11V8a3 3 0 116 0v3"/>',
  shield: '<path d="M12 2l9 4v7c0 5-9 8-9 8s-9-3-9-8V6l9-4z" fill="none"/>',

  // Argus-specific icons
  chain: '<path d="M8 8l8 8M16 8l-8 8" stroke-width="1.4"/><circle cx="8" cy="8" r="3" fill="none"/><circle cx="16" cy="8" r="3" fill="none"/><circle cx="8" cy="16" r="3" fill="none"/><circle cx="16" cy="16" r="3" fill="none"/>',
  bug: '<circle cx="12" cy="10" r="5" fill="none"/><path d="M7 14l-3 3M17 14l3 3M12 15v5M9 20h6"/>',
  target: '<circle cx="12" cy="12" r="9" fill="none"/><circle cx="12" cy="12" r="5" fill="none"/><circle cx="12" cy="12" r="1"/>',
  script: '<path d="M6 4h12v16H6V4z" fill="none"/><path d="M9 9h6M9 13h6M9 17h4"/>',
  verified: '<circle cx="12" cy="12" r="10" fill="none"/><path d="M8 12l3 3 5-5"/>',
}

/** Title-case a string (e.g. "mcp-server" → "MCP Server"). */
export function titleCase(s: string): string {
  return String(s || "")
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (m) => m.toUpperCase())
}

/** Escape HTML entities for safe innerHTML usage. */
export function esc(str: string): string {
  const div = document.createElement("div")
  div.appendChild(document.createTextNode(str))
  return div.innerHTML
}
