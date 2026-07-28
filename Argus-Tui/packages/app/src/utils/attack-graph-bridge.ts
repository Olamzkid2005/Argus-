/**
 * Attack Graph Window Bridge — shared utility for reading the attack graph
 * snapshot from the window-level bridge set by scan-store.ts.
 */

import type { AttackGraphSnapshot } from "@/visualizer/index"

const ATTACK_GRAPH_EVENT = "attack-graph-update"

export function getSnapshot(): AttackGraphSnapshot | null {
  try {
    return ((window as any).__argus_attack_graph_snapshot__ as AttackGraphSnapshot) ?? null
  } catch {
    return null
  }
}

export function onAttackGraphUpdate(handler: () => void): () => void {
  window.addEventListener(ATTACK_GRAPH_EVENT, handler)
  return () => window.removeEventListener(ATTACK_GRAPH_EVENT, handler)
}

export function triggerAttackGraphUpdate(): void {
  window.dispatchEvent(new CustomEvent(ATTACK_GRAPH_EVENT))
}
