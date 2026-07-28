/**
 * Attack Detail Drawer — slide-in panel for finding and chain details.
 *
 * Adapted from ai-surface's `drawerHTML()` / `openDrawer()` (~120 lines).
 * Shows per-finding evidence, severity, prerequisites, impacts,
 * chain membership, and exploit scripts.
 */
import type { AttackPathData, GraphNodeData } from "../planner/types";
export declare class AttackDetailDrawer {
    private overlay;
    private panel;
    private content;
    private _open;
    constructor(container: HTMLElement);
    /** Open the drawer with a finding's detail view. */
    openFinding(finding: GraphNodeData, chainData?: AttackPathData): void;
    /** Open the drawer with a full chain detail view. */
    openChain(chain: AttackPathData): void;
    /** Render a chain membership section inside a finding drawer. */
    private renderChainSection;
    /** Risk score color (green → yellow → red). */
    private riskColor;
    open(): void;
    close(): void;
    get isOpen(): boolean;
}
