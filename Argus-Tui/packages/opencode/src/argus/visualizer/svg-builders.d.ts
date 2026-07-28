/**
 * SVG Builder Utilities — ported from ai-surface's `app.js` (~160 lines).
 *
 * Pure, zero-dependency SVG element creation helpers for the AttackGraphVisualizer.
 * Each function creates an SVG element via `document.createElementNS()` and returns
 * it pre-configured with the given attributes.
 */
/** Create an SVG element with the given tag name. */
export declare function mk(tag: string): SVGElement;
/**
 * Create a `<circle>` element (disc).
 * Modeled after ai-surface's `disc()` helper.
 */
export declare function disc(x: number, y: number, r: number, fill: string, stroke: string, sw: number, cls?: string): SVGCircleElement;
/**
 * Create a `<circle>` element with transparent fill (ring/glow).
 * Modeled after ai-surface's `ringEl()` helper.
 */
export declare function ringEl(x: number, y: number, r: number, stroke: string, sw: number, op: number, cls?: string): SVGCircleElement;
/**
 * Create a quadratic bezier `<path>` edge between two points.
 * Uses the same gentle-curve formula as ai-surface (line ~602 of app.js):
 *   qx = mx - dy * 0.12,  qy = my + dx * 0.12
 *
 * @param dashed - If true, applies `stroke-dasharray="6,4"` for chain-path edges.
 */
export declare function edge(x1: number, y1: number, x2: number, y2: number, sw: number, op: number, dashed?: boolean): SVGPathElement;
/**
 * Create a `<text>` element.
 * Modeled after ai-surface's `text()` helper.
 */
export declare function svgText(x: number, y: number, str: string, cls: string): SVGTextElement;
/**
 * Create an inline SVG icon from an icon key.
 *
 * ICONS entries are full SVG element strings (e.g. `<circle .../><path .../>`),
 * so we inject them via `innerHTML` on the root `<svg>` element. This matches
 * how ai-surface's original JS builds icons (inline HTML strings in template
 * literals).
 */
export declare function svgIcon(name: string, cls?: string): SVGElement;
/**
 * Severity color palette for Argus findings.
 * Maps Severity enum values to hex colors for node fills and badges.
 */
export declare const SEV_ORDER: readonly ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
export type SeverityLabel = (typeof SEV_ORDER)[number];
export declare const SEV_RANK: Record<string, number>;
export declare const SEV_COLORS: Record<string, string>;
/**
 * Relationship type edge colors.
 * Maps Argus's RelationshipType enum to colors for chain-path edges.
 */
export declare const RELATIONSHIP_COLORS: Record<string, string>;
/**
 * Inline SVG icon path data (ai-surface pattern).
 * Each icon is a full SVG element string (elements inside a 24x24 viewBox).
 * New icons added: chain (attack chain), bug (vulnerability), target (engagement).
 */
export declare const ICONS: Record<string, string>;
/** Title-case a string (e.g. "mcp-server" → "MCP Server"). */
export declare function titleCase(s: string): string;
/** Escape HTML entities for safe innerHTML usage. */
export declare function esc(str: string): string;
