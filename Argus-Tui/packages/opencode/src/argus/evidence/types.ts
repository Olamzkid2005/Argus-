// Note: This file uses snake_case for SQLite/disk persistence.
// The camelCase equivalents are in shared/types.ts for in-memory/API transfer.
// See shared/types.ts for EvidencePackage and ArtifactRef.
export type ArtifactType = "screenshot" | "request" | "response" | "har" | "log"

export interface ArtifactEntry {
  path: string
  hash: string
  type: ArtifactType
  size_bytes: number
}

export interface EvidenceManifest {
  package_id: string
  engagement_id: string
  created_at: string
  artifacts: ArtifactEntry[]
  package_hash: string
  /** Operator identity who collected this evidence (e.g., "cli_user", "autonomous_agent").
   *  Part of chain-of-custody tracking per audit item 67. */
  operator?: string
  /** Source tool/verifier that generated this evidence (e.g., "xss_verifier", "sqlmap"). */
  source_tool?: string
  /** The assessment phase during which this evidence was collected (e.g., "scan", "verify"). */
  phase?: string
  /** Target URL or endpoint that the evidence relates to. */
  target_url?: string
  /** Parent finding identifier that this evidence package supports. */
  parent_finding_id?: string
  /** Previous package_id hash reference for building a verifiable chain.
   *  When set, the package_hash of the prior evidence package is stored here,
   *  creating a linked chain that can be validated end-to-end. */
  previous_package_hash?: string
}

export interface IntegrityReport {
  valid: boolean
  packageId: string
  manifestHash: string
  computedHash: string
  errors: string[]
}
