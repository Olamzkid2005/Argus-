export { AttackGraphVisualizer } from "./attack-map"
export type { AttackGraphVisualizerOptions, VisualizerCallbacks } from "./attack-map"
export { AttackDetailDrawer } from "./drawer"
export {
  mk, disc, ringEl, edge, svgText,
  SEV_ORDER, SEV_RANK, SEV_COLORS, RELATIONSHIP_COLORS,
  titleCase, esc,
} from "./svg-builders"
export type { SeverityLabel } from "./svg-builders"

export interface GraphNodeData {
  id: string
  type: "vulnerability" | "endpoint"
  data: {
    type?: string
    severity?: string
    endpoint?: string
    source_tool?: string
    url?: string
    [key: string]: unknown
  }
  cvss: number | null
  confidence: number | null
  prerequisites: string[]
  downstream_impacts: string[]
}

export interface GraphEdgeData {
  from_node: string
  to_node: string
  type: string
  correlation_factor: number
  relationship_type: string
}

export interface AttackPathData {
  risk_score: number
  nodes: GraphNodeData[]
  edges: GraphEdgeData[]
  chain_id?: string
  chain_name?: string
  [key: string]: unknown
}

export interface AttackGraphSnapshot {
  paths: AttackPathData[]
  metadata: {
    totalPaths: number
    totalFindings: number
    highestRiskScore: number
    chainsDetected: number
  }
}
