/**
 * Attack Graph Visualizer — SVG radial cluster map of Argus attack chains.
 *
 * Inspired by ai-surface's `drawMap()` (~160 lines in `app.js`) which renders
 * a deterministic, zero-dependency radial cluster layout using pure SVG trigonometry.
 *
 * Adaptation for Argus:
 *   ai-surface Layer          →  Argus Attack Chain Layer
 *   ─────────────────────────────────────────────────────
 *   scan root (center)        →  engagement target / "Attack Graph"
 *   category hub (Ring 1)     →  vulnerability type hub (XSS, SSRF, IDOR...)
 *   finding leaf (Ring 2)     →  individual finding instance
 *   severity color            →  Argus Severity enum colors
 *   risk ring (assessed glow) →  chain membership indicator (dashed edges)
 *   evidence drawer           →  finding detail + chain exploit script
 *
 * Layout: deterministic trigonometric radial cluster (no physics, no D3.js).
 * - Center: engagement target summary
 * - Ring 1: vulnerability type hubs (evenly spaced)
 * - Ring 2: individual finding leaves (banded for dense categories)
 * - Dashed edges: chain path connections between vulnerabilities
 */
import type { AttackGraphSnapshot } from "../planner/types";
/** Callback types for visualizer interactions. */
export interface VisualizerCallbacks {
    onNodeClick?: (nodeId: string) => void;
    onHubClick?: (vulnType: string) => void;
    onChainClick?: (chainId: string) => void;
}
/** Configuration options for the AttackGraphVisualizer. */
export interface AttackGraphVisualizerOptions {
    /** viewBox width (default: 1000) */
    width?: number;
    /** viewBox height (default: 688) */
    height?: number;
    /** Whether to render chain-path edges as dashed lines (default: true) */
    showChainEdges?: boolean;
    /** CSS class for the root SVG element (default: "attack-map") */
    cssClass?: string;
    callbacks?: VisualizerCallbacks;
}
export declare class AttackGraphVisualizer {
    private svg;
    private g;
    private edgeLayer;
    private nodeLayer;
    private data;
    private opts;
    private W;
    private H;
    private callbacks;
    constructor(options?: AttackGraphVisualizerOptions);
    /**
     * Render the attack graph into a container element.
     * If data is empty (no paths), renders a friendly empty state.
     */
    render(container: HTMLElement, data: AttackGraphSnapshot): void;
    /** Re-render with new data (e.g. after replan). */
    update(container: HTMLElement, data: AttackGraphSnapshot): void;
    private renderEmpty;
    private drawAllPaths;
    /** Find the first `<circle>` inside a leaf node element by data-id. */
    private findNodeElement;
    private wireInteraction;
    /** Highlight a category, dim everything else (from ai-surface wireMapInteraction). */
    private focusCategory;
    /** Remove all highlights (from ai-surface unfocus). */
    private unfocus;
}
