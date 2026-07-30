/**
 * Attack Map Panel — Self-contained SolidJS component for the attack graph
 * visualization. Uses a window-level bridge to receive snapshot data from
 * the opencode package's scan-store, avoiding cross-package imports.
 *
 * The visualizer classes (AttackGraphVisualizer, AttackDetailDrawer) are
 * local copies adapted from the opencode package — pure DOM manipulation,
 * no framework dependency.
 */

import { createEffect, createSignal, onCleanup, Show } from "solid-js"
import { AttackGraphVisualizer, AttackDetailDrawer } from "@/visualizer/index"
import { getSnapshot, onAttackGraphUpdate } from "@/utils/attack-graph-bridge"

const ATTACK_GRAPH_EVENT = "attack-graph-update"

/**
 * Inline visualizer CSS (theme-aware, --ag- namespace).
 * Inlined to avoid cross-package CSS import issues.
 */
const VISUALIZER_CSS = [
  ":root{--ag-sev-critical:#dc2626;--ag-sev-high:#ea580c;--ag-sev-medium:#ca8a04;--ag-sev-low:#2563eb;--ag-sev-info:#6b7280;--ag-sev-none:#9ca3af;--ag-hub-fill:#1e293b;--ag-hub-fill-hover:#334155;--ag-hub-ring:#4f6dff;--ag-edge-base:#475569;--ag-edge-chain:#7c3aed;--ag-edge-causes:#dc2626;--ag-edge-enables:#2563eb;--ag-edge-amplifies:#ea580c;--ag-edge-mitigates:#16a34a;--ag-edge-depends:#6b7280;--ag-drawer-bg:#0f172a;--ag-drawer-text:#e2e8f0;--ag-drawer-width:420px;--ag-drawer-border:#334155;--ag-map-bg:transparent;--ag-map-radius:12px;--ag-font-sans:ui-sans-serif,system-ui,-apple-system,sans-serif;--ag-font-mono:ui-monospace,'SF Mono','Cascadia Code','JetBrains Mono',monospace;--ag-transition-fast:150ms ease;--ag-transition-normal:250ms ease}",
  '[data-theme="light"]{--ag-hub-fill:#f1f5f9;--ag-hub-fill-hover:#e2e8f0;--ag-drawer-bg:#fff;--ag-drawer-text:#1e293b;--ag-drawer-border:#e2e8f0;--ag-edge-base:#cbd5e1}',
  ".attack-map{display:block;width:100%;height:auto;background:var(--ag-map-bg);border-radius:var(--ag-map-radius);user-select:none}",
  ".attack-map .node{cursor:pointer;transition:opacity var(--ag-transition-fast)}",
  ".attack-map .node-center{cursor:default}",
  ".attack-map .lbl{font-family:var(--ag-font-sans);fill:var(--ag-drawer-text);pointer-events:none}",
  ".attack-map .sub-lbl{font-family:var(--ag-font-sans);fill:var(--ag-edge-base);pointer-events:none}",
  ".attack-map .risk-badge{font-family:var(--ag-font-sans);fill:var(--ag-edge-chain);pointer-events:none}",
  ".attack-map .count{font-family:var(--ag-font-sans);fill:var(--ag-drawer-text);pointer-events:none}",
  ".attack-map .edge{fill:none;stroke:var(--ag-edge-base);stroke-linecap:round;transition:opacity var(--ag-transition-fast);pointer-events:none}",
  ".attack-map .edge-chain{stroke:var(--ag-edge-chain);cursor:pointer;pointer-events:stroke}",
  ".attack-map .graph.dim .node:not(.related){opacity:.15}",
  ".attack-map .graph.dim .node.related{opacity:1}",
  ".attack-map .graph.dim .edge:not(.related){opacity:.08}",
  ".attack-map .graph.dim .edge.related{opacity:.8}",
  ".attack-map .empty-title{font-family:var(--ag-font-sans);fill:var(--ag-drawer-text);font-weight:600}",
  ".attack-map .empty-sub{font-family:var(--ag-font-sans);fill:var(--ag-edge-base)}",
  ".ag-drawer-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9998;opacity:0;pointer-events:none;transition:opacity var(--ag-transition-normal)}",
  ".ag-drawer-overlay.open{opacity:1;pointer-events:auto}",
  ".ag-drawer-panel{position:fixed;top:0;right:0;bottom:0;width:var(--ag-drawer-width);max-width:100vw;background:var(--ag-drawer-bg);color:var(--ag-drawer-text);border-left:1px solid var(--ag-drawer-border);z-index:9999;transform:translateX(100%);transition:transform var(--ag-transition-normal);display:flex;flex-direction:column;font-family:var(--ag-font-sans);overflow:hidden}",
  ".ag-drawer-panel.open{transform:translateX(0)}",
  ".ag-drawer-header{display:flex;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid var(--ag-drawer-border);flex-shrink:0}",
  ".ag-drawer-header h2{margin:0;font-size:16px;font-weight:600;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
  ".ag-drawer-close{background:none;border:none;color:var(--ag-edge-base);cursor:pointer;font-size:18px;padding:4px;line-height:1;border-radius:4px;transition:color var(--ag-transition-fast),background var(--ag-transition-fast)}",
  ".ag-drawer-close:hover{color:var(--ag-drawer-text);background:var(--ag-hub-fill-hover)}",
  ".ag-severity-badge{display:inline-block;padding:2px 8px;border-radius:4px;color:#fff;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}",
  ".ag-risk-score{font-size:13px;font-weight:700;color:var(--ag-edge-chain);white-space:nowrap}",
  ".ag-drawer-body{padding:16px 20px;overflow-y:auto;flex:1}",
  ".ag-detail-section{margin-bottom:20px}",
  ".ag-detail-section h3{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--ag-edge-base);margin:0 0 6px}",
  ".ag-endpoint{font-family:var(--ag-font-mono);font-size:13px;padding:6px 10px;background:var(--ag-hub-fill);border-radius:6px;display:inline-block;word-break:break-all}",
  ".ag-conf-bar{height:8px;background:var(--ag-hub-fill);border-radius:4px;overflow:hidden;margin-bottom:4px}",
  ".ag-conf-fill{height:100%;background:var(--ag-edge-chain);border-radius:4px;transition:width var(--ag-transition-normal)}",
  ".ag-conf-pct{font-size:12px;color:var(--ag-edge-base)}",
  ".ag-cvss{font-size:20px;font-weight:700;color:var(--ag-drawer-text)}",
  ".ag-list{list-style:none;padding:0;margin:0}",
  ".ag-list li{padding:4px 0;font-size:13px;position:relative;padding-left:16px}",
  ".ag-list li::before{content:'\\2022';position:absolute;left:4px;color:var(--ag-edge-base)}",
  ".ag-script-details{margin-top:4px}",
  ".ag-script-summary{font-size:12px;color:var(--ag-edge-chain);cursor:pointer;padding:4px 0;user-select:none}",
  ".ag-script-summary:hover{color:var(--ag-drawer-text)}",
  ".ag-script-pre{background:var(--ag-hub-fill);border:1px solid var(--ag-drawer-border);border-radius:6px;padding:10px 12px;overflow-x:auto;max-height:300px;overflow-y:auto;margin-top:6px}",
  ".ag-script-code{font-family:var(--ag-font-mono);font-size:12px;line-height:1.5;color:var(--ag-drawer-text);white-space:pre}",
  ".ag-step-list{margin-top:4px}",
  ".ag-step-list li{padding:3px 0 3px 16px}",
  ".ag-impact-text{font-size:13px;line-height:1.5;color:var(--ag-drawer-text);margin:4px 0}",
  ".ag-verification-status{display:flex;align-items:center;gap:6px;padding:6px 10px;border-radius:6px;font-size:13px;font-weight:600}",
  ".ag-verification-status.verified{background:rgba(22,163,74,.15);color:#16a34a}",
  ".ag-verification-status.unverified{background:rgba(107,114,128,.15);color:var(--ag-edge-base)}",
  ".ag-verification-icon{font-size:16px}",
  ".ag-verification-label{text-transform:uppercase;font-size:11px;letter-spacing:.5px}",
  ".ag-verification-conf{font-size:11px;font-weight:400;opacity:.7}",
  ".ag-verification-reason{font-size:12px;color:var(--ag-edge-base);margin:4px 0 0;padding-left:24px}",
  ".attack-map .keyboard-focused{outline:2px solid var(--ag-edge-chain);outline-offset:3px;border-radius:4px}",
  ".ag-risk-bar{height:8px;background:var(--ag-hub-fill);border-radius:4px;overflow:hidden;margin-bottom:4px}",
  ".ag-risk-fill{height:100%;border-radius:4px;transition:width var(--ag-transition-normal)}",
  ".ag-risk-value{font-size:12px;color:var(--ag-edge-base)}",
  ".ag-chain-flow{display:flex;flex-direction:column;gap:8px}",
  ".ag-chain-step{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--ag-hub-fill);border-radius:8px;transition:background var(--ag-transition-fast);cursor:pointer}",
  ".ag-chain-step:hover{background:var(--ag-hub-fill-hover)}",
  ".ag-step-num{width:24px;height:24px;border-radius:50%;background:var(--ag-edge-base);color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}",
  ".ag-step-body{flex:1;min-width:0}",
  ".ag-step-type{font-size:13px;font-weight:600;display:block}",
  ".ag-step-sev{font-size:11px;font-weight:700;text-transform:uppercase}",
  ".ag-step-endpoint{font-family:var(--ag-font-mono);font-size:11px;color:var(--ag-edge-base);display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
  ".ag-chain-badge{display:inline-block;padding:4px 10px;background:var(--ag-hub-fill);border:1px solid var(--ag-edge-chain);border-radius:6px;font-size:12px;color:var(--ag-edge-chain);font-weight:600;cursor:pointer;transition:background var(--ag-transition-fast)}",
  ".ag-chain-badge:hover{background:var(--ag-hub-fill-hover)}",
  ".ag-chain-position{font-size:12px;color:var(--ag-edge-base);margin-top:4px}",
  ".ag-chain-risk{font-size:12px;margin-top:4px}",
  ".ag-chain-path-mini{display:flex;align-items:center;gap:4px;margin-top:8px;flex-wrap:wrap}",
  ".ag-chain-mini-step{display:inline-block;padding:2px 8px;border-radius:4px;color:#fff;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.3px;opacity:.7;transition:opacity var(--ag-transition-fast)}",
  ".ag-chain-mini-step.current{opacity:1;box-shadow:0 0 0 2px var(--ag-drawer-text)}",
  ".ag-chain-arrow{color:var(--ag-edge-base);font-size:12px}",
  ".ag-btn{display:inline-flex;align-items:center;justify-content:center;padding:8px 16px;border:1px solid var(--ag-drawer-border);background:var(--ag-hub-fill);color:var(--ag-drawer-text);border-radius:6px;font-size:13px;font-family:var(--ag-font-sans);cursor:pointer;transition:background var(--ag-transition-fast),border-color var(--ag-transition-fast)}",
  ".ag-btn:hover{background:var(--ag-hub-fill-hover);border-color:var(--ag-edge-base)}",
  ".ag-btn-small{padding:4px 10px;font-size:12px;margin-top:8px}",
  ".ag-drawer-body::-webkit-scrollbar{width:6px}",
  ".ag-drawer-body::-webkit-scrollbar-track{background:transparent}",
  ".ag-drawer-body::-webkit-scrollbar-thumb{background:var(--ag-drawer-border);border-radius:3px}",
  ".ag-drawer-body::-webkit-scrollbar-thumb:hover{background:var(--ag-edge-base)}",
].join("")

let cssInjected = false

export function AttackMapPanel() {
  let visualizer: AttackGraphVisualizer | undefined
  let drawer: AttackDetailDrawer | undefined

  // Signal-based ref — use createSignal so the ref change is tracked
  const [el, setEl] = createSignal<HTMLDivElement | undefined>()
  const [hasData, setHasData] = createSignal(false)
  const [tick, setTick] = createSignal(0) // bumped on every event to force re-render

  // Inject CSS once
  if (!cssInjected) {
    const style = document.createElement("style")
    style.textContent = VISUALIZER_CSS
    document.head.appendChild(style)
    cssInjected = true
  }

  // Listen for CustomEvent from scan-store's window bridge.
  // Keeps a stable handler reference for proper cleanup.
  createEffect(() => {
    const handler = () => {
      setTick((c) => c + 1)
      setHasData(!!getSnapshot()?.paths?.length)
    }
    window.addEventListener(ATTACK_GRAPH_EVENT, handler)
    // Also check current state on mount
    handler()
    onCleanup(() => window.removeEventListener(ATTACK_GRAPH_EVENT, handler))
  })

  // Watch for data changes + container availability.
  // Reads tick() + el() so it re-runs on every event AND when the container mounts.
  createEffect(() => {
    tick() // subscribe to every event
    const data = getSnapshot()
    const container = el()
    if (!data?.paths?.length || !container) return

    setHasData(true)

    // Initialize once
    if (!visualizer) {
      drawer = new AttackDetailDrawer(document.body)
      visualizer = new AttackGraphVisualizer({
        callbacks: {
          onNodeClick: (nodeId: string) => {
            const snap = getSnapshot()
            if (!snap || !drawer) return
            for (const path of snap.paths) {
              const node = path.nodes.find((n) => n.id === nodeId)
              if (node) {
                drawer.openFinding(node, path)
                return
              }
            }
          },
          onHubClick: () => {},
          onChainClick: (chainId: string) => {
            const snap = getSnapshot()
            if (!snap || !drawer) return
            const chain = snap.paths.find((p) => p.chain_id === chainId)
            if (chain) drawer.openChain(chain)
          },
        },
      })
    }

    // Close drawer on data refresh, then re-render
    if (drawer?.isOpen) drawer.close()
    visualizer.render(container, data)
  })

  onCleanup(() => {
    if (drawer) drawer.close()
    visualizer = undefined
    drawer = undefined
  })

  return (
    <Show
      when={hasData()}
      fallback={
        <div class="h-full w-full flex flex-col items-center justify-center p-8 text-center gap-4">
          <div class="text-14-medium text-text-weak">No attack paths found</div>
          <div class="text-13-regular text-text-weaker max-w-md">
            Run an assessment to discover vulnerability chains.
            Attack chains will appear here after the replan cycle completes.
          </div>
        </div>
      }
    >
      <div
        ref={setEl}
        class="size-full overflow-hidden"
        style={{ "min-height": "400px" }}
      />
    </Show>
  )
}
