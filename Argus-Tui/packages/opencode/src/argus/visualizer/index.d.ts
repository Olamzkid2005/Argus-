/**
 * Attack Graph Visualizer — barrel export.
 *
 * Exports all visualizer components for easy imports:
 * ```typescript
 * import { AttackGraphVisualizer, AttackDetailDrawer } from "../visualizer"
 * ```
 */
export { AttackGraphVisualizer } from "./attack-map";
export type { AttackGraphVisualizerOptions, VisualizerCallbacks } from "./attack-map";
export { AttackDetailDrawer } from "./drawer";
export { mk, disc, ringEl, edge, svgText, svgIcon, SEV_ORDER, SEV_RANK, SEV_COLORS, RELATIONSHIP_COLORS, ICONS, titleCase, esc, } from "./svg-builders";
export type { SeverityLabel } from "./svg-builders";
export type { AttackGraphSnapshot, AttackPathData, GraphNodeData, GraphEdgeData } from "../planner/types";
